"""The evaluation protocol of the palm lock (protocol.py, scripts/palm_evaluate.py): the split of each person's photos, a threshold
that comes from the validation photos and nothing else, the numbers the brief asks for (FAR, FRR, accuracy and its balance, latency,
trial counts, a confusion matrix), "not measurable" for a zero denominator, and Invalid Image counted apart.

Drawn hands stand in for people (see synth.py): four people, seven photos each, taken at different turns, sizes and brightness.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from synth import found, render

from app.cv.biometric import visuals
from app.cv.biometric.config import DEFAULT
from app.cv.biometric.engine import Problem, extract_from_image
from app.cv.biometric.match import CalibrationError, load_calibration, save_calibration
from app.cv.biometric.protocol import (
    Confusion,
    EvaluationError,
    Rate,
    Shot,
    Split,
    attempts_csv,
    confusion_at,
    d_prime,
    evaluate,
    natural_key,
    report_lines,
    roc_curve,
)

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'palm_evaluate.py'
LOOKS = [(0, 480, 1.0), (12, 430, 0.9), (-15, 520, 1.1), (25, 460, 1.0), (-6, 500, 0.95), (-20, 450, 1.05), (8, 490, 0.92)]
PEOPLE = ['drawn1', 'drawn2', 'drawn3', 'drawn4']
PHOTO_MS = 1000.0


@pytest.fixture(scope='module')
def shots() -> list[Shot]:
    out: list[Shot] = []
    split = Split()
    for p, person in enumerate(PEOPLE):
        for k, role in enumerate(split.roles(len(LOOKS))):
            angle, scale, gain = LOOKS[k]
            img, placed = render(angle=angle, scale=scale, seed=100 + p)
            rng = np.random.default_rng(1000 * p + k)
            img = np.clip(img.astype(np.float32) * gain + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
            result = extract_from_image(img, found(placed).points, 'right', DEFAULT)
            assert not isinstance(result, Problem), result
            out.append(Shot(person, f'{person}/{k + 1}', role, 'right', result, PHOTO_MS))
    return out


class Tick:
    """A clock that moves 5 ms every time it is read."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.005
        return self.now


@pytest.fixture(scope='module')
def ev(shots):
    return evaluate(shots, clock=Tick())


def spoil(shots: list[Shot], victim: Shot, code: str = 'no_hand') -> list[Shot]:
    """The same photos, with one of them no longer judgeable."""
    return [replace(s, result=Problem(code, 'no hand in this photo')) if s is victim else s for s in shots]


# ------------------------------------------------------------------ the pieces


def test_photos_are_taken_in_number_order_not_in_text_order() -> None:
    assert sorted(['10.jpg', '2.jpg', '1.jpg', '9.JPG'], key=natural_key) == ['1.jpg', '2.jpg', '9.JPG', '10.jpg']


def test_the_split_gives_three_to_the_lock_two_to_the_threshold_and_the_rest_to_the_test() -> None:
    assert Split().roles(7) == ['enrol'] * 3 + ['validate'] * 2 + ['test'] * 2
    assert Split().roles(9) == ['enrol'] * 3 + ['validate'] * 2 + ['test'] * 4
    assert Split().roles(4) == ['enrol'] * 3 + ['validate']
    assert Split().roles(0) == []
    assert Split(4, 1).roles(7) == ['enrol'] * 4 + ['validate'] + ['test'] * 2


def test_a_rate_with_nothing_to_divide_by_is_not_measurable_not_zero() -> None:
    none = Rate(0, 0)
    assert none.value is None and none.interval() is None
    assert none.text() == 'not measurable' and none.short() == 'not measurable'
    assert Rate(0, 20).text() == '0.0% (0 of 20)'


def test_no_errors_in_a_few_trials_still_leaves_room_for_error() -> None:
    low, high = Rate(0, 180).interval()
    assert low == 0.0 and 0.018 < high < 0.022
    low, high = Rate(0, 20).interval()
    assert 0.15 < high < 0.17


def test_the_confusion_matrix_gives_far_frr_and_accuracy_with_the_test_balance() -> None:
    c = Confusion(genuine_accepted=18, genuine_rejected=2, impostor_accepted=3, impostor_rejected=177)
    assert (c.genuine, c.impostor, c.total) == (20, 180, 200)
    assert c.far == Rate(3, 180) and c.frr == Rate(2, 20) and c.accuracy == Rate(195, 200)
    assert c.balanced_accuracy == pytest.approx((1 - 3 / 180 + 1 - 2 / 20) / 2)
    assert c.same_answer_accuracy == Rate(180, 200)  # a lock that refused everybody would score 90%


def test_an_empty_confusion_matrix_measures_nothing() -> None:
    c = Confusion()
    assert c.far.value is None and c.frr.value is None and c.accuracy.value is None and c.balanced_accuracy is None
    only_genuine = Confusion(genuine_accepted=3)
    assert only_genuine.far.value is None and only_genuine.frr.value == 0.0 and only_genuine.balanced_accuracy is None


def test_a_score_equal_to_the_threshold_is_accepted() -> None:
    c = confusion_at(np.array([0.5, 0.4]), np.array([0.5, 0.1]), 0.5)
    assert (c.genuine_accepted, c.genuine_rejected, c.impostor_accepted, c.impostor_rejected) == (1, 1, 1, 1)


def test_separation_and_the_curve_need_both_kinds_of_attempt() -> None:
    assert d_prime(np.array([]), np.array([0.1, 0.2])) is None
    assert d_prime(np.array([0.9, 0.95]), np.array([0.1, 0.2])) > 5
    far, frr = roc_curve(np.array([0.9, 0.8]), np.array([0.1, 0.2]))
    assert far[0] == 1.0 and frr[0] == 0.0  # accept everybody
    assert far[-1] == 0.0 and frr[-1] == 1.0  # refuse everybody


# ------------------------------------------------------------------ the evaluation


def test_every_test_photo_is_tried_against_every_lock(ev, shots) -> None:
    tests = {s.label for s in shots if s.role == 'test'}
    assert {a.photo for a in ev.attempts} == tests
    assert len(ev.attempts_of(True)) == len(tests)
    assert len(ev.attempts_of(False)) == len(tests) * (len(PEOPLE) - 1)
    assert all(a.genuine == (a.photo.split('/')[0] == a.lock) for a in ev.attempts)
    assert all(p.locked for p in ev.people)


def test_the_counts_add_up_and_the_lock_gave_one_of_three_outcomes(ev) -> None:
    c = ev.confusion
    scored = [a for a in ev.attempts if a.outcome in ('success', 'failed')]
    assert c.total == len(scored) == len(ev.attempts)
    assert {a.outcome for a in ev.attempts} <= {'success', 'failed', 'invalid_image'}
    assert c.genuine_accepted == sum(a.genuine and a.outcome == 'success' for a in ev.attempts)
    assert c.impostor_accepted == sum((not a.genuine) and a.outcome == 'success' for a in ev.attempts)


def test_the_fused_row_of_the_ablation_is_what_the_lock_itself_decided(ev) -> None:
    assert [v.key for v in ev.variants] == ['crease', 'compcode', 'lbp', 'fusion']
    assert ev.fusion.test == ev.confusion
    assert ev.fusion.threshold == ev.calibration.threshold
    assert {v.key: v.role for v in ev.variants} == {'crease': 'decides', 'compcode': 'decides', 'lbp': 'spare', 'fusion': 'decides'}
    assert all(v.test.total == ev.confusion.total for v in ev.variants)


def test_the_threshold_in_use_is_one_of_the_rows_of_the_sweep(ev) -> None:
    assert ev.calibration.threshold in [t for t, _ in ev.sweep]
    far = [row.far.value for _, row in ev.sweep]
    assert far == sorted(far, reverse=True)  # a stricter threshold never accepts more impostors


def test_the_threshold_comes_from_the_validation_photos_and_nothing_else(shots, ev) -> None:
    without_the_test = evaluate([s for s in shots if s.role != 'test'])
    assert without_the_test.calibration.threshold == ev.calibration.threshold
    assert without_the_test.calibration.normalisers == ev.calibration.normalisers
    # ... and the validation photos did make a difference: the counts behind the threshold are theirs
    assert ev.validation_genuine == len(PEOPLE) * 2
    assert ev.validation_impostor == len(PEOPLE) * 2 * (len(PEOPLE) - 1)


def test_without_test_photos_nothing_is_measurable(shots) -> None:
    ev0 = evaluate([s for s in shots if s.role != 'test'])
    assert ev0.attempts == [] and ev0.confusion == Confusion()
    text = '\n'.join(report_lines(ev0))
    assert 'FAR  not measurable' in text and 'FRR  not measurable' in text and 'Accuracy  not measurable' in text
    assert 'Mean latency: not measurable' in text
    assert all(v.test_eer is None and v.d_prime is None for v in ev0.variants)


def test_an_invalid_image_is_counted_apart_and_is_neither_a_failure_nor_a_success(shots, ev) -> None:
    victim = next(s for s in shots if s.person == 'drawn2' and s.role == 'test')
    ev2 = evaluate(spoil(shots, victim))
    invalid = [a for a in ev2.attempts if a.outcome == 'invalid_image']
    assert len(invalid) == len(PEOPLE)  # the one photo, against each lock
    assert all(a.score is None for a in invalid)
    assert sum(a.genuine for a in invalid) == 1
    assert ev2.invalid['no_hand'] == len(PEOPLE)
    assert ev2.confusion.genuine == ev.confusion.genuine - 1
    assert ev2.confusion.impostor == ev.confusion.impostor - (len(PEOPLE) - 1)
    text = '\n'.join(report_lines(ev2))
    assert 'Invalid Image: 1 genuine, 3 impostor' in text


def test_a_person_without_three_usable_enrolment_photos_has_no_lock_but_is_still_tried_as_an_impostor(shots) -> None:
    first = next(s for s in shots if s.person == 'drawn4' and s.role == 'enrol')
    ev2 = evaluate(spoil(shots, first))
    row = next(p for p in ev2.people if p.person == 'drawn4')
    assert not row.locked and 'enrolment' in row.why_not and row.invalid == ('no_hand',)
    mine = [a for a in ev2.attempts if a.person == 'drawn4']
    assert mine and not any(a.genuine for a in mine)
    assert {a.lock for a in mine} == {'drawn1', 'drawn2', 'drawn3'}
    assert not any(a.lock == 'drawn4' for a in ev2.attempts)
    assert 'not made' in '\n'.join(report_lines(ev2))


def test_enrolment_photos_that_do_not_match_each_other_are_refused_as_the_website_would_and_the_rest_carry_on(shots) -> None:
    stranger = next(s for s in shots if s.person == 'drawn2' and s.role == 'enrol')
    target = next(s for s in shots if s.person == 'drawn1' and s.role == 'enrol')
    mixed = [replace(s, result=stranger.result) if s is target else s for s in shots]
    ev2 = evaluate(mixed)
    row = next(p for p in ev2.people if p.person == 'drawn1')
    assert not row.locked and row.why_not.startswith('the lock was not made')
    assert {p.person for p in ev2.people if p.locked} == {'drawn2', 'drawn3', 'drawn4'}
    assert not any(a.lock == 'drawn1' for a in ev2.attempts)
    assert any(a.person == 'drawn1' for a in ev2.attempts)


def test_with_only_one_lock_left_there_are_no_different_person_attempts_so_it_stops(shots) -> None:
    two = [s for s in shots if s.person in ('drawn1', 'drawn2')]
    stranger = next(s for s in two if s.person == 'drawn2' and s.role == 'enrol')
    target = next(s for s in two if s.person == 'drawn1' and s.role == 'enrol')
    with pytest.raises(EvaluationError, match='Fewer than two locks'):
        evaluate([replace(s, result=stranger.result) if s is target else s for s in two])


def test_the_evaluation_says_what_is_missing_instead_of_inventing_a_number(shots) -> None:
    with pytest.raises(EvaluationError, match='At least two people'):
        evaluate([s for s in shots if s.person == 'drawn1'])
    with pytest.raises(EvaluationError, match='validation'):
        evaluate([s for s in shots if s.role != 'validate'])
    with pytest.raises(EvaluationError, match='between 3 and 5'):
        evaluate(shots, split=Split(2, 2))
    with pytest.raises(EvaluationError, match='validation photo'):
        evaluate(shots, split=Split(3, 0))


def test_latency_is_the_whole_way_from_the_photo_to_the_outcome(ev) -> None:
    assert all(a.verify_ms == 5.0 and a.ms == PHOTO_MS + 5.0 for a in ev.attempts)
    assert ev.mean_ms() == ev.mean_ms(True) == ev.mean_ms(False) == PHOTO_MS + 5.0
    assert set(ev.stage_ms) == {'roi', 'prep', 'crease', 'compcode', 'lbp', 'checks'}
    assert ev.stage_ms['checks'] > 0


def test_the_report_has_what_the_brief_asks_for(ev) -> None:
    text = '\n'.join(report_lines(ev))
    c = ev.confusion
    for needle in ('Confusion matrix', 'FAR  ', 'FRR  ', 'Accuracy  ', 'Mean latency', 'Threshold ', 'Score convention', 'Each method alone and fused', 'at or above the threshold'):
        assert needle in text, needle
    assert f'Attempts: {len(ev.attempts_of(True))} same-person (genuine), {len(ev.attempts_of(False))} different-person (impostor)' in text
    assert f'{c.genuine} genuine : {c.impostor} impostor' in text
    assert 'A lock that gave everybody the same answer would score' in text
    assert 'photos 1-3 made the lock' in text and 'photos 4-5 set the threshold' in text and 'photos 6 onwards were the test' in text


def test_the_attempt_list_and_the_picture_hold_numbers_only(ev) -> None:
    rows = attempts_csv(ev).splitlines()
    assert rows[0] == 'attempt,photo_of,photo,lock,kind,outcome,score,crease,compcode,ms'
    assert len(rows) == len(ev.attempts) + 1 and all(len(r.split(',')) == 10 for r in rows)
    img = visuals.score_picture(*ev.fused, ev.calibration.threshold, 'test')
    assert img.shape == (440, 1000, 3) and img.dtype == np.uint8 and img.std() > 5
    assert visuals.score_picture(np.array([]), np.array([0.2, 0.3]), 0.5).shape == (440, 1000, 3)  # one kind missing: still draws


def test_the_calibration_made_here_can_be_saved_and_the_website_accepts_it(ev, tmp_path) -> None:
    path = tmp_path / 'calibration.json'
    save_calibration(ev.calibration, path)
    again = load_calibration(path)
    assert again.threshold == ev.calibration.threshold and again.normalisers == ev.calibration.normalisers
    assert 'validation photos only' in again.source
    assert not again.calibrated  # four people are not enough to call it calibrated
    broken = path.read_text(encoding='utf-8').replace(again.config_hash, 'not-this-engine')
    path.write_text(broken, encoding='utf-8')
    with pytest.raises(CalibrationError):
        load_calibration(path)


# ------------------------------------------------------------------ the script


@pytest.fixture(scope='module')
def script():
    import sys

    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('palm_evaluate', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_runs_on_drawn_hands_and_writes_a_report_with_no_photos(script, tmp_path, capsys) -> None:
    code = script.main(['--drawn', '--drawn-people', '3', '--out', str(tmp_path)])
    assert code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ['palm_attempts.csv', 'palm_evaluation.txt', 'palm_scores.png']
    report = (tmp_path / 'palm_evaluation.txt').read_text(encoding='utf-8')
    assert 'Confusion matrix' in report and '3 people, 21 photos' in report
    assert 'no photos or templates' in capsys.readouterr().out


def test_the_script_will_not_put_drawn_hand_numbers_into_the_website(script, tmp_path, capsys) -> None:
    before = load_calibration().threshold
    assert script.main(['--drawn', '--write-calibration', '--out', str(tmp_path)]) == 1
    assert 'real dataset' in capsys.readouterr().out
    assert load_calibration().threshold == before
    assert list(tmp_path.iterdir()) == []


def test_the_script_says_where_the_photos_go_when_the_folder_is_missing(script, tmp_path, capsys) -> None:
    assert script.main(['--photos', str(tmp_path / 'nothing-here'), '--out', str(tmp_path / 'out')]) == 1
    out = capsys.readouterr().out
    assert 'does not exist' in out and 'P01' in out
