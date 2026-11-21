"""Choosing which knowledge-base entries the model is shown (app/llm/retrieval.py): a lookup for the report, a keyword search
for the chat, and in both cases only entries this reading allows."""

from __future__ import annotations

import pytest
from test_standin import hands_for

from app.llm import kb, retrieval
from app.llm.knowledge import FEATURE_ORDER


def detected(hands, line):
    return any(next(f for f in h.features if f.id == line).status == 'detected' for h in hands.values())


@pytest.fixture(scope='module')
def hands():
    # fate and sun are not detected on either hand of this reading, which is what the "left out" tests need
    out = hands_for('rd_000000000000000a', 0.95, 0.95)
    assert not detected(out, 'fate') and not detected(out, 'sun') and detected(out, 'heart')
    return out


def test_the_report_lookup_names_only_what_was_detected(hands):
    ids = {e.id for e in retrieval.entries_for_findings(hands)}
    assert {'heart.general', 'head.general', 'life.general'} <= ids
    assert not any(i.startswith(('fate.', 'sun.')) for i in ids)  # nothing for a line that was not clearly seen
    for hand in hands.values():
        for f in hand.features:
            if f.status == 'detected':
                for e in retrieval.line_entries(f.id, f.traits):
                    assert e.id in ids
    assert all(retrieval.allowed(e, hands) for e in retrieval.entries_for_findings(hands))


def test_a_faint_line_gets_no_entry_about_how_clear_it_is(hands):
    from app.schemas import FeatureTraits

    ids = [e.id for e in retrieval.line_entries('heart', FeatureTraits(length='long', curve='gentle', clarity='faint'))]
    assert ids == ['heart.general', 'heart.length.long', 'heart.curve.gentle']


def test_a_trait_this_reading_does_not_show_is_not_allowed(hands):
    shown = {next(f for f in h.features if f.id == 'heart').traits.length for h in hands.values()}
    for length in ('short', 'medium', 'long'):
        entry = kb.line_entry('heart', 'length', length)
        assert retrieval.allowed(entry, hands) == (length in shown)


def test_general_entries_are_always_allowed(hands):
    for entry in kb.of_kind('theme') + kb.of_kind('compare') + kb.of_kind('limits'):
        assert retrieval.allowed(entry, hands)


def test_a_question_finds_the_entries_about_what_it_asks(hands):
    def top(question, k=2):
        return [e.id for e in retrieval.retrieve(question, hands)][:k]

    assert top('What does my heart line traditionally represent?', 1) == ['heart.general']
    assert top('Can you explain my life line in more detail?', 1) == ['life.general']
    assert 'theme.career' in top('What does palmistry say about my career?')
    assert 'theme.financial' in top('What are the traditional interpretations of my financial prospects?')
    assert top('Is palmistry scientific?', 1) == ['limits.not_science']
    assert top('What differences are visible between my left and right palms?', 1) == ['compare.differ']


def test_a_line_that_was_not_seen_is_never_offered_even_when_asked_about(hands):
    for question in ('What does my fate line mean?', 'Tell me about the sun line', 'What is my destiny line?'):
        ids = [e.id for e in retrieval.retrieve(question, hands)]
        assert not any(i.startswith(('fate.', 'sun.')) for i in ids), question


def test_a_follow_up_with_no_topic_uses_the_question_before_it(hands):
    assert retrieval.retrieve('why?', hands) == []
    ids = [e.id for e in retrieval.retrieve('why?', hands, earlier='What does my heart line traditionally represent?')]
    assert ids and ids[0].startswith('heart.')
    # a question that has a topic of its own does not borrow the earlier one
    ids = [e.id for e in retrieval.retrieve('What about my career?', hands, earlier='What does my heart line traditionally represent?')]
    assert 'theme.career' in ids and not any(i.startswith('heart.') for i in ids)


def test_the_search_is_repeatable_and_returns_at_most_k(hands):
    first = [e.id for e in retrieval.retrieve('head line and life line and heart line', hands, k=4)]
    assert first == [e.id for e in retrieval.retrieve('head line and life line and heart line', hands, k=4)]
    assert len(first) <= 4


def test_bm25_scores_by_rarity_and_ignores_words_that_say_nothing():
    assert retrieval.tokens('What does my heart line traditionally represent?') == ['heart', 'line']
    assert retrieval.stem('lines') == 'line' and retrieval.stem('feelings') == 'feeling' and retrieval.stem('class') == 'class'
    index = retrieval.index()
    assert index.search('zzzz qqqq') == []  # a word that is in no entry matches nothing
    rare = index.score(retrieval.tokens('pseudoscience'), [e.id for e in index.items].index('limits.not_science'))
    common = index.score(retrieval.tokens('line'), [e.id for e in index.items].index('limits.not_science'))
    assert rare > common


def test_the_lines_named_in_a_question_come_first(hands):
    ids = [e.id for e in retrieval.retrieve('Compare my head line with my heart line', hands)]
    assert ids[:2] == ['heart.general', 'head.general'] or set(ids[:2]) == {'heart.general', 'head.general'}


def test_the_feature_order_is_the_reports_order():
    assert FEATURE_ORDER == ['heart', 'head', 'life', 'fate', 'sun']
