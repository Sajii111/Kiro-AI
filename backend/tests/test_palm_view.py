"""Straightening a palm: every hand, whatever its size, side or angle in the photo, ends up in the same coordinates."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from synth import LANDMARKS, Placed, found, render

from app.cv.hand import Frame, hand_frame
from app.cv.palm import (
    H_PX,
    MIN_PALM_PX,
    W_PX,
    PalmNotUsable,
    hand_mask,
    prepare_palm,
    to_px,
    to_rc,
    to_xy,
    warp,
)


def frame_for(length: float, angle: float, sign: int = 1, wrist=(2000.0, 2600.0)) -> Frame:
    a = np.radians(angle)
    u = np.array([-np.sin(a), -np.cos(a)])  # up the palm, in a picture where y grows downward
    v = np.array([np.cos(a), -np.sin(a)]) * sign  # toward the thumb
    return Frame(wrist=np.array(wrist), u=u, v=v, length=length, sign=sign)


def blob_picture(frame: Frame, at: tuple[float, float], size: int = 4000) -> np.ndarray:
    """A grey picture with one bright dot where the palm coordinates `at` fall, in the photo."""
    img = np.full((size, size, 3), 60, np.uint8)
    x, y = frame.to_photo(np.array([at]))[0]
    cv2.circle(img, (round(float(x)), round(float(y))), max(2, round(frame.length * 0.03)), (255, 255, 255), -1, cv2.LINE_AA)
    return img


def where_is_brightest(picture: np.ndarray) -> tuple[float, float]:
    gray = picture.astype(np.float32).mean(axis=2)
    weights = np.clip(gray - 100, 0, None)
    rows, cols = np.indices(gray.shape)
    return float((weights * cols).sum() / weights.sum()), float((weights * rows).sum() / weights.sum())


def test_the_straightened_picture_has_one_fixed_size_and_coordinates_convert_both_ways():
    assert (W_PX, H_PX) == (720, 560)  # 1.8 units across and 1.4 units up, at 400 pixels a unit
    for x, y in [(0.0, 0.0), (0.5, 0.9), (-0.3, 1.1), (0.9, -0.1)]:
        col, row = to_px(x, y)
        back = to_xy(np.array([row]), np.array([col]))[0]
        assert back == pytest.approx([x, y])
        assert to_rc(np.array([[x, y]]))[0] == pytest.approx([row, col])


@pytest.mark.parametrize('sign', [1, -1])
@pytest.mark.parametrize('angle', [0, 37, -120, 200])
@pytest.mark.parametrize('length', [650.0, 380.0, 190.0, 75.0])
def test_a_point_lands_at_its_palm_coordinates_whatever_the_size_angle_or_side(length, angle, sign):
    frame = frame_for(length, angle, sign)
    target = (0.30, 0.55)
    straight = warp(blob_picture(frame, target), frame)
    assert straight.shape == (H_PX, W_PX, 3)
    col, row = where_is_brightest(straight)
    want_col, want_row = to_px(*target)
    slack = 1.5 + 0.7 * 400 / length  # a small hand is enlarged, so half a photo pixel of error in the dot is several here
    assert (col, row) == pytest.approx((want_col, want_row), abs=slack)


def test_a_small_hand_in_a_big_photo_is_not_enlarged_to_fit():
    # A palm 65 px long in a 9000 x 9000 photo would need a 55,000 x 55,000 picture (9 GB) if the photo were enlarged first
    frame = frame_for(65.0, 15.0, wrist=(4500.0, 5000.0))
    big = blob_picture(frame, (0.1, 0.6), size=9000)
    straight = warp(big, frame)
    assert straight.shape == (H_PX, W_PX, 3)
    assert where_is_brightest(straight) == pytest.approx(to_px(0.1, 0.6), abs=6.0)


def test_a_mask_is_straightened_the_same_way_as_a_picture_and_stays_black_and_white():
    frame = frame_for(300.0, 25.0)
    mask = np.zeros((4000, 4000), np.uint8)
    x, y = frame.to_photo(np.array([(0.2, 0.5)]))[0]
    cv2.circle(mask, (round(float(x)), round(float(y))), 60, 255, -1)
    straight = warp(mask, frame, nearest=True)
    assert set(np.unique(straight)) <= {0, 255}
    rows, cols = np.nonzero(straight)
    assert (cols.mean(), rows.mean()) == pytest.approx(to_px(0.2, 0.5), abs=3.0)


def test_a_hand_too_small_to_carry_creases_is_not_usable():
    image, placed = render('right', 0, scale=40.0, size=(600, 600))
    hand = found(placed)
    assert hand_frame(hand.points).length < MIN_PALM_PX
    with pytest.raises(PalmNotUsable, match='too small'):
        prepare_palm(image, hand.points)


def test_landmarks_that_are_not_a_hand_are_not_usable():
    image, _ = render('right', 0)
    with pytest.raises(PalmNotUsable):
        prepare_palm(image, np.zeros((21, 2)))


@pytest.fixture(scope='module')
def view_and_hand():
    image, placed = render('right', 20)
    hand = found(placed)
    return prepare_palm(image, hand.points), hand, placed


def test_a_prepared_palm_is_one_picture_one_mask_and_a_ridge_map_of_the_same_size(view_and_hand):
    view, _, _ = view_and_hand
    assert view.image.shape == (H_PX, W_PX, 3)
    for part in (view.mask, view.strength, view.angle, view.gate_h, view.gate_v):
        assert part.shape == (H_PX, W_PX)
    assert view.strength.min() >= 0 and view.strength.max() <= 1.5
    assert view.gate_h.min() >= 0 and view.gate_h.max() <= 1 and view.gate_v.min() >= 0 and view.gate_v.max() <= 1
    assert view.contrast > 0.03  # the drawn creases are deep


def test_the_ridge_map_is_empty_outside_the_hand(view_and_hand):
    view, _, _ = view_and_hand
    assert view.strength[~view.mask].max() == 0.0
    assert (view.strength > 0.5).sum() > 500  # and there is something inside it


def test_the_silhouette_covers_the_palm_and_the_fingers_but_not_the_background(view_and_hand):
    view, hand, _ = view_and_hand
    inside = [0, 5, 9, 13, 17]  # the wrist and the four knuckles
    for i in inside:
        x, y = hand.points[i]
        assert view.silhouette[round(float(y)), round(float(x))], f'landmark {i} is outside the silhouette'
    h, w = view.silhouette.shape
    corners = [view.silhouette[10, 10], view.silhouette[10, w - 10], view.silhouette[h - 10, 10]]
    assert not any(corners)
    # about the right amount of picture: the drawn palm, fingers and forearm cover roughly a fifth of it
    share = float(view.silhouette.mean())
    assert 0.12 < share < 0.35


def test_a_prepared_palm_knows_where_its_knuckles_are_in_palm_coordinates(view_and_hand):
    view, _, _ = view_and_hand
    k = view.knuckle_x()
    assert list(k) == ['i', 'm', 'r', 'p', 't']
    assert k['i'] > k['m'] > k['r'] > k['p']  # from the thumb side to the little-finger side
    assert k['t'] == pytest.approx(float(view.anchors[1, 0]))  # the base of the thumb
    assert view.anchors[[5, 9, 13, 17], 0] == pytest.approx(LANDMARKS[[5, 9, 13, 17], 0] / 0.9925, abs=1e-6)
    assert Placed is not None


def test_the_silhouette_is_the_same_every_time_for_the_same_photo():
    # GrabCut starts from random numbers. Without a fixed seed the outline moved a little on every call, and so could a borderline line.
    image, placed = render('left', 28, seed=3)
    hand = found(placed)
    first = hand_mask(image, hand.points)
    for _ in range(3):
        assert np.array_equal(hand_mask(image, hand.points), first)
