"""The hand's own coordinates, and what the landmarks say about a photo (is a palm in view, is it the right hand...).

The landmarks come from `synth.py`: a hand drawn at a known place, so the right answers are known too.
"""

from __future__ import annotations

import numpy as np
import pytest
from synth import LANDMARKS, FakeFinder, Placed, found, landmarks_for

from app.cv.hand import FoundHand, build_finder, describe, hand_frame
from app.cv.images import palm_check_from_hands

SIZE = (1300, 1300)
SCALE = 480.0
#: wrist to the middle of the four knuckles in the drawn hand's own units (the drawing's L)
L_UNIT = float(np.linalg.norm(LANDMARKS[[5, 9, 13, 17]].mean(axis=0)))


def drawn(side: str = 'right', angle: float = 0.0, scale: float = SCALE, width: float = 1.0, **kw) -> FoundHand:
    return found(Placed(side, angle, scale, SIZE, width), **kw)


def moved(hand: FoundHand, dx: float = 0.0, dy: float = 0.0) -> FoundHand:
    return FoundHand(points=hand.points + [dx, dy], label=hand.label, score=hand.score)


def check(hands: list[FoundHand], side: str = 'right', size: tuple[int, int] = SIZE):
    result, hand, facts = palm_check_from_hands(hands, side, *size)  # type: ignore[arg-type]
    return result.status, result.message, hand, facts


# ------------------------------------------------------------------ the frame


@pytest.mark.parametrize('side', ['right', 'left'])
@pytest.mark.parametrize('angle', [0, 28, -35, 90, 170, -150])
def test_the_frame_does_not_care_which_way_the_hand_is_turned(side, angle):
    hand = drawn(side, angle)
    frame = hand_frame(hand.points)
    assert frame is not None
    assert frame.length == pytest.approx(L_UNIT * SCALE)
    # in palm coordinates every hand is the same hand, whatever the side or the angle: x toward the thumb, y toward the fingers
    assert frame.to_canon(hand.points) == pytest.approx(LANDMARKS / L_UNIT, abs=1e-6)


def test_the_frame_tells_a_right_palm_from_a_left_one_by_where_the_thumb_is():
    assert hand_frame(drawn('right', 0).points).sign == +1
    assert hand_frame(drawn('left', 0).points).sign == -1
    # turning the hand does not change it (the sign is about which side the thumb is on, not about the direction)
    assert all(hand_frame(drawn('right', a).points).sign == +1 for a in (45, 120, 200, -80))
    assert all(hand_frame(drawn('left', a).points).sign == -1 for a in (45, 120, 200, -80))


def test_a_point_goes_from_the_photo_to_the_palm_and_back_unchanged():
    hand = drawn('left', 33)
    frame = hand_frame(hand.points)
    rng = np.random.default_rng(3)
    somewhere = rng.uniform(100, 1200, size=(40, 2))
    assert frame.to_photo(frame.to_canon(somewhere)) == pytest.approx(somewhere, abs=1e-6)
    assert frame.to_canon(frame.wrist[None, :])[0] == pytest.approx([0.0, 0.0])
    # the middle of the knuckles is one unit up the palm
    knuckles = hand.points[[5, 9, 13, 17]].mean(axis=0)
    assert frame.to_canon(knuckles[None, :])[0] == pytest.approx([0.0, 1.0], abs=1e-9)


def test_landmarks_that_do_not_make_a_hand_give_no_frame():
    assert hand_frame(np.zeros((21, 2))) is None
    assert hand_frame(np.full((21, 2), np.nan)) is None
    stacked = drawn().points.copy()
    stacked[17] = stacked[5]  # the index and little-finger knuckles on the same spot: no direction "across the hand"
    assert hand_frame(stacked) is None
    bunched = drawn().points.copy()
    bunched[:] = bunched[0] + np.linspace(0, 3, 21)[:, None]  # the whole hand squeezed into a few pixels
    assert hand_frame(bunched) is None


# ------------------------------------------------------------------ what the landmarks say about the photo


def test_an_open_flat_palm_reads_as_one():
    hand = drawn()
    facts = describe(hand, hand_frame(hand.points), *SIZE, 'right')
    assert facts.length == pytest.approx(L_UNIT * SCALE)
    assert 0.65 < facts.flatness < 0.70  # width across the knuckles to palm length, about 0.7 for a palm facing the camera
    assert 0.90 < facts.finger_reach < 1.0
    assert not facts.cut_off and not facts.cut_off_palm
    assert facts.shows_palm is True and facts.side_matches is True


def test_the_back_of_a_hand_is_told_apart_by_the_label_and_the_thumb_disagreeing():
    # the network calls this a left hand, but the thumb sits where a right palm has it: that is the back of a right hand
    # (or the palm of a mirrored photo, which the slot check below deals with)
    back = drawn('right', label='left')
    facts = describe(back, hand_frame(back.points), *SIZE, 'right')
    assert facts.shows_palm is False
    # the same picture, called right: a palm
    palm = drawn('right', label='right')
    assert describe(palm, hand_frame(palm.points), *SIZE, 'right').shows_palm is True


def test_a_hesitant_network_is_not_believed_either_way():
    hand = drawn('right', label='left', score=0.60)
    facts = describe(hand, hand_frame(hand.points), *SIZE, 'right')
    assert facts.shows_palm is None and facts.side_matches is None
    # and a tilted hand cannot say which side it is showing
    tilted = drawn('right', label='left', width=0.4)
    assert describe(tilted, hand_frame(tilted.points), *SIZE, 'right').shows_palm is None


def test_the_slot_a_photo_was_added_to_is_compared_with_what_the_network_sees():
    hand = drawn('right')
    frame = hand_frame(hand.points)
    assert describe(hand, frame, *SIZE, 'right').side_matches is True
    assert describe(hand, frame, *SIZE, 'left').side_matches is False


def test_a_landmark_at_the_edge_of_the_photo_counts_as_cut_off():
    hand = drawn()
    facts = describe(moved(hand, dy=-400), hand_frame(moved(hand, dy=-400).points), *SIZE, 'right')  # fingertips above the photo
    assert facts.cut_off and facts.cut_off_palm
    # the thumb tip alone is past the right edge: the photo is cut, but the palm and the four fingers are all there
    thumb_x = hand.points[4, 0]
    pushed = moved(hand, dx=SIZE[0] + 5 - thumb_x)
    facts = describe(pushed, hand_frame(pushed.points), *SIZE, 'right')
    assert facts.cut_off and not facts.cut_off_palm


def test_finger_reach_falls_when_the_fingers_curl():
    short = drawn(finger_stretch=0.5)
    open_ = drawn(finger_stretch=1.0)
    assert describe(short, hand_frame(short.points), *SIZE, 'right').finger_reach < 0.5 < describe(open_, hand_frame(open_.points), *SIZE, 'right').finger_reach
    assert landmarks_for(1.0) == pytest.approx(LANDMARKS)


# ------------------------------------------------------------------ the "palm in view" check


def test_a_good_photo_of_a_palm_passes():
    status, message, hand, facts = check([drawn()])
    assert (status, message) == ('pass', 'A palm is in view.')
    assert hand is not None and facts is not None
    assert check([drawn('left')], 'left')[0] == 'pass'


FAILS = [
    ('nothing is found', list, 'could not find a hand'),
    ('it is the back of the hand', lambda: [drawn('right', label='left')], 'back of the hand'),
    ('the hand is tiny', lambda: [drawn(scale=100)], 'very small'),
    ('the palm is edge-on', lambda: [drawn(width=0.30)], 'turned away'),
]


@pytest.mark.parametrize(('why', 'make', 'words'), FAILS, ids=[f[0] for f in FAILS])
def test_a_photo_with_no_usable_palm_fails_and_says_what_to_do(why, make, words):
    status, message, _, _ = check(make())
    assert status == 'fail'
    assert words in message


WARNINGS = [
    ('it was added as the wrong hand', lambda: [drawn('right')], 'left', 'right hand, but it was added as the left'),
    ('two hands are in the photo', lambda: [drawn('right'), drawn('left', 20, scale=400)], 'right', 'Two hands'),
    ('the palm is tilted', lambda: [drawn(width=0.55)], 'right', 'tilted'),
    ('the palm is cut off', lambda: [moved(drawn(), dy=-400)], 'right', 'cut off'),
    ('the palm is small in the photo', lambda: [drawn(scale=240)], 'right', 'small part'),
    ('the fingers are curled', lambda: [drawn(finger_stretch=0.5)], 'right', 'curled'),
]


@pytest.mark.parametrize(('why', 'make', 'side', 'words'), WARNINGS, ids=[w[0] for w in WARNINGS])
def test_a_photo_that_can_be_read_but_not_well_gets_a_warning(why, make, side, words):
    status, message, hand, _ = check(make(), side)
    assert status == 'warn'
    assert words in message
    assert hand is not None  # a warning still hands the hand on to the analysis


def test_a_thumb_cut_off_alone_is_a_softer_warning_than_a_cut_off_palm():
    hand = drawn()
    pushed = moved(hand, dx=SIZE[0] + 5 - hand.points[4, 0])
    status, message, _, _ = check([pushed])
    assert status == 'warn' and 'thumb' in message
    assert 'Parts of the hand' not in message


def test_a_much_smaller_second_hand_is_not_a_second_hand():
    assert check([drawn('right'), drawn('left', 20, scale=200)])[0] == 'pass'


def test_the_most_serious_problem_is_the_one_reported():
    # the back of a very small hand: the back of the hand comes first
    assert 'back of the hand' in check([drawn('right', label='left', scale=100)])[1]
    # a tiny hand that is also in the wrong slot: too small comes before the wrong-slot warning
    status, message, _, _ = check([drawn('right', scale=100)], 'left')
    assert status == 'fail' and 'very small' in message


# ------------------------------------------------------------------ the fake finder (what the other tests rely on)


def test_the_fake_finder_answers_by_the_size_of_the_picture():
    hand = drawn()
    finder = FakeFinder({SIZE: [hand]})
    blank = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
    assert finder.find(blank) == [hand]
    assert finder.find(blank[:1200]) == []
    assert finder.calls == 2
    finder.close()
    assert finder.closed


# ------------------------------------------------------------------ choosing the mode when the server starts


def test_sample_mode_never_loads_the_hand_model(tmp_path):
    assert build_finder('sample', tmp_path / 'nothing.task') is None


def test_real_mode_refuses_to_start_without_the_model_file(tmp_path):
    with pytest.raises(RuntimeError, match='run.bat models'):
        build_finder('real', tmp_path / 'nothing.task')


def test_real_mode_refuses_to_start_without_the_package(tmp_path, monkeypatch):
    monkeypatch.setattr('app.cv.hand.mediapipe_installed', lambda: False)
    with pytest.raises(RuntimeError, match='not installed'):
        build_finder('real', tmp_path / 'nothing.task')


def test_auto_mode_falls_back_to_samples_and_says_so(tmp_path, caplog):
    with caplog.at_level('WARNING', logger='kiro.hand'):
        assert build_finder('auto', tmp_path / 'nothing.task') is None
    assert 'SAMPLE readings' in caplog.text


def test_a_broken_model_file_is_a_clear_error_in_real_mode_and_a_fallback_in_auto_mode(tmp_path, caplog):
    pytest.importorskip('mediapipe')
    broken = tmp_path / 'hand_landmarker.task'
    broken.write_bytes(b'this is not a model')
    with pytest.raises(RuntimeError, match='could not be loaded'):
        build_finder('real', broken)
    with caplog.at_level('WARNING', logger='kiro.hand'):
        assert build_finder('auto', broken) is None
    assert 'could not be loaded' in caplog.text
