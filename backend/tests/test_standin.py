"""The stand-in line finder and report writer. They are not the real thing, but the rules they keep are the rules the
real ones must keep, so the rules are tested here and will keep being tested when Phase 2 and 3 replace the insides."""

from __future__ import annotations

import pytest

from app.core.rand import hash_string, rng
from app.cv.images import CheckedPhoto
from app.cv.pipeline import make_reading
from app.cv.standin import build_analysis, plan_statuses
from app.llm.knowledge import FEATURE_ORDER, THEMES
from app.llm.report import build_report
from app.schemas import PhotoQuality, PhotoSize

SIDES = ('left', 'right')


def quality(score: float, palm_visible: bool = True) -> PhotoQuality:
    level = 'good' if score > 0.9 else 'fair' if score > 0.5 else 'poor'
    return PhotoQuality(sharpness=level, lighting=level, resolution='good', palmVisible=palm_visible, score=score)


def hands_for(seed_text: str, ql: float = 1.0, qr: float = 1.0, palm_right: bool = True):
    seed = hash_string(seed_text)
    q = {'left': quality(ql), 'right': quality(qr, palm_right)}
    size = PhotoSize(width=800, height=1000)
    plan = plan_statuses(seed, q)
    return {s: build_analysis(s, plan[s], size, q[s], seed) for s in SIDES}


SEEDS = [f'rd_{i:016x}' for i in range(60)]


def test_the_random_numbers_are_the_websites_own_so_a_reading_is_repeatable():
    assert [round(rng(12345)(), 10)] == [0.9797282678]
    assert hash_string('rd_test') == hash_string('rd_test') and hash_string('a') != hash_string('b')
    a = hands_for('rd_same')
    b = hands_for('rd_same')
    assert {s: h.model_dump() for s, h in a.items()} == {s: h.model_dump() for s, h in b.items()}


@pytest.mark.parametrize('seed', SEEDS[:20])
def test_every_hand_has_the_five_lines_in_order_with_nothing_invented(seed):
    for side, hand in hands_for(seed, 0.7, 0.9).items():
        assert [f.id for f in hand.features] == FEATURE_ORDER
        for f in hand.features:
            if f.status == 'not_visible':
                assert f.path == [] and f.confidence is None and f.traits.model_dump() == {}  # nothing is made up for a line that was not seen
            else:
                assert 12 <= len(f.path) <= 80 and f.confidence is not None and 0 < f.confidence <= 1
                assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in f.path), (f.id, side)
            if f.status == 'uncertain':
                assert set(f.traits.model_dump()) <= {'clarity'}  # an uncertain line may only carry "faint"
            if f.status == 'detected':
                assert f.traits.length and f.traits.curve and f.traits.clarity in ('clear', 'deep')
            box = f.searchArea
            assert 0 <= box.x <= 1 and 0 <= box.y <= 1 and box.x + box.w <= 1.001 and box.y + box.h <= 1.001
            assert f.method.startswith('sample-detector')


def test_the_clear_lines_are_never_promoted_from_a_guess():
    for seed in SEEDS:
        for hand in hands_for(seed, 1.0, 1.0).values():
            for f in hand.features:
                if f.status == 'uncertain':
                    assert f.confidence < 0.7  # a guess scores like a guess


def test_every_reading_shows_at_least_one_uncertain_and_one_unseen_line():
    for seed in SEEDS:
        statuses = [f.status for h in hands_for(seed, 0.95, 0.95).values() for f in h.features]
        assert 'uncertain' in statuses and 'not_visible' in statuses, seed


def test_a_worse_photo_finds_fewer_lines():
    def found(q: float) -> int:
        return sum(f.status == 'detected' for seed in SEEDS for h in hands_for(seed, q, q).values() for f in h.features)

    assert found(1.0) > found(0.5) > found(0.25)
    # the heart and life lines are the clearest in real hands: a decent photo always finds them
    for seed in SEEDS:
        for h in hands_for(seed, 0.7, 0.7).values():
            assert {f.id: f.status for f in h.features}['heart'] == 'detected'


def test_the_hand_shape_follows_whether_the_hand_was_in_view():
    hands = hands_for('rd_shape', 1.0, 1.0, palm_right=False)
    assert hands['left'].palmShape.status == 'detected' and hands['right'].palmShape.status == 'not_visible'
    assert hands['right'].palmShape.palmRatio is None and hands['right'].palmShape.traits.model_dump() == {}
    poor = hands_for('rd_shape', 0.4, 0.4)
    assert poor['left'].palmShape.status == 'uncertain' and poor['left'].palmShape.traits.model_dump() == {}


def report_for(seed_text: str, ql=1.0, qr=1.0):
    hands = hands_for(seed_text, ql, qr)
    return hands, build_report(hands, '2026-01-01T00:00:00.000Z')


@pytest.mark.parametrize('seed', SEEDS[:20])
def test_the_report_only_speaks_about_what_was_seen(seed):
    hands, report = report_for(seed, 0.8, 0.8)
    for section in report.sections:
        for side in SIDES:
            seen = getattr(section.observed, side).status
            said = getattr(section.traditional, side)
            assert (said is None) == (seen == 'not_visible'), (section.featureId, side)  # unseen: nothing said. Seen or uncertain: something.
            if seen == 'uncertain':
                assert said.startswith('Only a rough hint') and 'could not be read' in said
            if seen == 'detected':
                assert said.startswith('Your ')
    for theme in report.themes:
        detected = {
            src
            for src in ('heart', 'head', 'life', 'fate', 'sun', 'shape')
            if any((h.palmShape.status if src == 'shape' else next(f for f in h.features if f.id == src).status) == 'detected' for h in hands.values())
        }
        assert set(theme.basedOn) <= detected  # a theme leans only on what was clearly seen...
        assert set(theme.basedOn).isdisjoint(theme.leftOut)  # ...and says what it left out
        assert set(theme.basedOn) | set(theme.leftOut) == set(next(t for t in THEMES if t.id == theme.themeId).sources)
        assert (theme.traditional is None) == (not theme.basedOn)
        if theme.traditional:
            assert theme.label == 'traditional' and theme.traditional.startswith(next(t for t in THEMES if t.id == theme.themeId).intro)
            if theme.leftOut:
                assert 'Left out' in theme.traditional


def test_the_report_keeps_the_disclaimer_and_gives_no_orders_and_no_alarms():
    _, report = report_for('rd_advice')
    assert 'not a science' in report.disclaimer and 'never as medical, financial, legal or relationship advice' in report.disclaimer
    text = ' '.join([report.summary, *(t.traditional or '' for t in report.themes)]).lower()
    for phrase in ('you should', 'you must', 'diagnos', 'invest', 'illness', 'divorce', 'betray', 'next year', 'within '):
        assert phrase not in text, phrase
    assert 'you will' in text  # it foretells: that is what a reading is for
    future = next(t for t in report.themes if t.themeId == 'future')
    assert future.traditional is None or 'not every step' in future.traditional  # the honest line, in the reader's voice


def test_the_life_line_text_never_talks_about_lifespan():
    for seed in SEEDS:
        _, report = report_for(seed)
        life = next(s for s in report.sections if s.featureId == 'life')
        for said in (life.traditional.left, life.traditional.right):
            if said:
                assert 'live longer' not in said and 'die' not in said.lower().split()
                assert 'lifespan' not in said or 'not about lifespan' in said  # the tradition's line is a theme of energy, never of how long anyone lives


def test_the_uncertainty_list_matches_the_findings():
    hands, report = report_for('rd_uncertain', 0.6, 0.6)
    unseen = sum(f.status == 'not_visible' for h in hands.values() for f in h.features)
    unsure = sum(f.status == 'uncertain' for h in hands.values() for f in h.features)
    assert sum(': not visible.' in u for u in report.uncertainty) == unseen
    assert sum(': uncertain.' in u for u in report.uncertainty) >= unsure
    assert any('photo was' in u for u in report.uncertainty)  # a middling photo is mentioned


def test_other_creases_are_drawn_but_never_named():
    for seed in SEEDS[:20]:
        hands, report = report_for(seed, 1.0, 1.0)
        for h in hands.values():
            for crease in h.otherCreases:
                assert len(crease.path) >= 2 and 0 < crease.confidence < 1 and 'not named' in crease.observation
            if h.otherCreases:
                assert any('not match one of the five main lines' in u for u in report.uncertainty)


def test_make_reading_is_repeatable_and_labelled_as_a_sample():
    photos = {}
    for side in SIDES:
        photos[side] = CheckedPhoto(side=side, result=None, width=800, height=1000, quality=quality(0.9))  # type: ignore[arg-type]
    a = make_reading('rd_fixed', 'prf_1', photos, '2026-01-01T00:00:00.000Z')  # type: ignore[arg-type]
    b = make_reading('rd_fixed', 'prf_1', photos, '2026-01-01T00:00:00.000Z')  # type: ignore[arg-type]
    assert a == b and a.meta.mock is True and a.meta.provider == 'sample'
    assert a.meta.knowledgeBase and a.meta.prompt and a.meta.pipeline
