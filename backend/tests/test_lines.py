"""Finding the five principal lines: the tracer, the rules that judge a traced line, and the whole analysis of a hand.

The whole-hand tests use the drawn hands from `synth.py`. The creases in them are drawn at known places, so a test can
check where the analysis put each line, not only what it called it.
"""

from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from synth import CREASES, Placed, distance_to_polyline, found, render, sample_polyline

from app.cv.lines import (
    CONTRAST_NONE,
    CONTRAST_OK,
    SPECS,
    THUMB_MARGIN,
    Traced,
    analyse,
    confidence_for,
    judge,
    polygon_mask,
    sagitta,
    smooth,
    thumb_edge,
    to_norm,
    trace,
    traits_for,
    zones,
)
from app.cv.palm import H_PX, W_PX, X_MIN, to_px
from app.schemas import PhotoQuality, PhotoSize

IDS = ['heart', 'head', 'life', 'fate', 'sun']
GOOD = PhotoQuality(sharpness='good', lighting='good', resolution='good', palmVisible=True, score=0.9)
POOR = PhotoQuality(sharpness='poor', lighting='fair', resolution='fair', palmVisible=True, score=0.4)
L_UNIT = 0.9925  # the drawn hand's wrist-to-knuckles length in its own units


# ------------------------------------------------------------------ the tracer


def ridge_picture(h: int = 60, w: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """A picture where every pixel costs, except one gently bowed ridge from the left edge to the right that pays."""
    profit = np.full((h, w), -0.3)
    rows = np.round(30 + 8 * np.sin(np.linspace(0, np.pi, w))).astype(int)
    profit[rows, np.arange(w)] = 1.0
    return profit, rows


def start_at_left(profit: np.ndarray) -> np.ndarray:
    start = np.zeros(profit.shape, bool)
    start[:, 0] = True
    return start


def test_the_tracer_follows_a_ridge_left_to_right():
    profit, rows = ridge_picture()
    total, path = trace(profit, start_at_left(profit), 'x+')
    assert path[0, 1] == 0 and path[-1, 1] == profit.shape[1] - 1
    assert np.array_equal(path[:, 0], rows[path[:, 1]])  # exactly on the ridge, one pixel per column
    assert total == pytest.approx(profit.shape[1] * 1.0, abs=2.0)


@pytest.mark.parametrize('direction', ['x+', 'x-', 'y-', 'y+'])
def test_the_tracer_runs_in_every_direction_and_starts_where_it_is_told(direction):
    profit, _ = ridge_picture()
    start = start_at_left(profit)
    if direction == 'x-':
        profit, start = profit[:, ::-1].copy(), start[:, ::-1].copy()
    elif direction == 'y-':
        profit, start = profit.T.copy(), start.T.copy()
    elif direction == 'y+':
        profit, start = profit.T[::-1].copy(), start.T[::-1].copy()
    _, path = trace(profit, start, direction)
    assert {tuple(p) for p in path} == {tuple(p) for p in np.argwhere(profit == 1.0)}  # the ridge, and nothing else
    assert start[path[0, 0], path[0, 1]]  # it began inside the start area
    steps = np.abs(np.diff(path, axis=0))
    assert steps.max() <= 1 or (steps.max(axis=0) <= 1).all() or steps.sum(axis=1).max() <= 2  # joined up, no jumps


def test_the_tracer_will_not_jump_between_far_apart_ridges():
    profit = np.full((80, 100), -0.3)
    profit[20, :] = 0.6  # a weaker ridge up here
    profit[60, :] = 1.0  # a stronger one down here
    start = np.zeros(profit.shape, bool)
    start[:, 0] = True
    _, path = trace(profit, start, 'x+')
    assert set(path[:, 0]) == {60}  # it picks one and stays on it


def test_the_tracer_gives_up_when_there_is_nowhere_to_start():
    profit, _ = ridge_picture()
    assert trace(profit, np.zeros(profit.shape, bool), 'x+') is None


def test_a_smoothed_path_keeps_its_ends_where_they_were():
    rng = np.random.default_rng(5)
    xy = np.stack([np.linspace(0, 1, 80), 0.1 * np.sin(np.linspace(0, 4, 80)) + rng.normal(0, 0.01, 80)], axis=1)  # a bend with jitter
    out = smooth(xy)
    assert out[0] == pytest.approx(xy[0]) and out[-1] == pytest.approx(xy[-1])
    assert np.diff(out[15:-15, 1], 2).std() < 0.2 * np.diff(xy[15:-15, 1], 2).std()  # the jitter is gone, the bend stays
    assert np.abs(out[15:-15, 1] - 0.1 * np.sin(np.linspace(0, 4, 80))[15:-15]).max() < 0.02
    assert np.array_equal(smooth(xy[:3]), xy[:3])  # too short to smooth


# ------------------------------------------------------------------ how a path bows


def test_a_straight_path_does_not_bow():
    xy = np.stack([np.linspace(0, 1, 50), np.linspace(0, 0.4, 50)], axis=1)
    assert sagitta(xy) == pytest.approx(0.0, abs=1e-9)


def test_a_bow_is_measured_as_a_share_of_the_straight_distance_between_its_ends():
    # a circular arc of 120 degrees: the bow is (1 - cos 60) / (2 sin 60) of the chord
    a = np.radians(np.linspace(-60, 60, 200))
    arc = np.stack([np.sin(a), np.cos(a)], axis=1)
    assert sagitta(arc) == pytest.approx((1 - np.cos(np.radians(60))) / (2 * np.sin(np.radians(60))), rel=0.01)
    assert sagitta(np.array([[0.2, 0.2], [0.2, 0.2], [0.2, 0.2]])) == 0.0  # no chord, no bow


# ------------------------------------------------------------------ judging a traced line


def path_of(length: float = 0.6, strong: float = 1.0, weak_share: float = 0.0, n: int = 100) -> Traced:
    """A straight path `length` long, up the palm. `weak_share` of it lies on a barely visible crease."""
    xy = np.stack([np.zeros(n), np.linspace(0.0, length, n)], axis=1)
    strength = np.full(n, strong)
    strength[: round(weak_share * n)] = 0.1
    return Traced(xy=xy, strength=strength, score=1.0)


def test_a_photo_with_no_crease_contrast_says_nothing_about_any_line():
    great = path_of(0.9, 1.4)
    assert all(judge(fid, great, CONTRAST_NONE - 0.001) == 'not_visible' for fid in IDS)
    assert all(judge(fid, None, 0.1) == 'not_visible' for fid in IDS)


def test_a_photo_with_little_contrast_never_calls_a_line_detected():
    great = path_of(0.9, 1.4)
    middle = (CONTRAST_NONE + CONTRAST_OK) / 2
    assert all(judge(fid, great, middle) == 'uncertain' for fid in IDS)
    assert all(judge(fid, great, CONTRAST_OK) == 'detected' for fid in IDS)


@pytest.mark.parametrize('fid', IDS)
def test_each_line_has_its_own_shortest_length_to_count_as_detected(fid):
    spec = SPECS[fid]
    assert judge(fid, path_of(spec.detected_length + 0.01), 0.06) == 'detected'
    assert judge(fid, path_of(spec.detected_length - 0.02), 0.06) == 'uncertain'
    assert judge(fid, path_of(spec.uncertain_length - 0.02), 0.06) == 'not_visible'


def test_a_faint_or_patchy_line_is_uncertain_and_a_barely_there_one_is_not_visible():
    assert judge('heart', path_of(0.6, 0.5), 0.06) == 'uncertain'  # weaker than the palm's own strongest creases
    assert judge('heart', path_of(0.6, 1.0, weak_share=0.30), 0.06) == 'uncertain'  # broken: a third of it is not a crease
    assert judge('heart', path_of(0.6, 0.2), 0.06) == 'not_visible'


def test_confidence_is_missing_for_a_line_that_is_not_there_and_always_a_probability_otherwise():
    t = path_of(0.7, 1.2)
    assert confidence_for('not_visible', t, 'heart', GOOD) is None
    for fid in IDS:
        for strong in (0.4, 0.9, 1.5):
            for status in ('detected', 'uncertain'):
                c = confidence_for(status, path_of(0.7, strong), fid, GOOD)  # type: ignore[arg-type]
                assert 0.15 <= c <= 0.95


def test_confidence_is_lower_when_unsure_and_when_the_photo_is_poor():
    t = path_of(0.7, 1.0)
    detected = confidence_for('detected', t, 'life', GOOD)
    assert confidence_for('uncertain', t, 'life', GOOD) < detected
    assert confidence_for('detected', t, 'life', POOR) < detected
    assert confidence_for('detected', path_of(0.7, 0.9), 'life', GOOD) < confidence_for('detected', path_of(0.7, 1.4), 'life', GOOD)


# ------------------------------------------------------------------ the words for a traced line


def palm_stub(k: dict[str, float] | None = None) -> SimpleNamespace:
    """Just enough of a straightened palm for `traits_for`: where the knuckles are, and a palm that fills the picture."""
    knuckles = k or {'i': 0.33, 'm': 0.11, 'r': -0.11, 'p': -0.33}
    return SimpleNamespace(knuckle_x=lambda: knuckles, mask=np.ones((H_PX, W_PX), bool))


def line(points: list[tuple[float, float]], strong: float = 1.0) -> Traced:
    xy = sample_polyline(points, 80)
    return Traced(xy=xy, strength=np.full(len(xy), strong), score=1.0)


@pytest.mark.parametrize(('end_x', 'word'), [(0.30, 'long'), (0.10, 'medium'), (-0.20, 'short')])
def test_the_heart_line_is_as_long_as_the_finger_it_reaches_under(end_x, word):
    t = line([(-0.43, 0.8), (end_x / 2, 0.85), (end_x, 0.88)])
    assert traits_for('heart', t, palm_stub()).length == word


@pytest.mark.parametrize(('end_x', 'word'), [(-0.70, 'long'), (-0.50, 'medium'), (-0.20, 'short')])
def test_the_head_line_is_as_long_as_it_is_close_to_the_outer_edge_of_the_palm(end_x, word):
    t = line([(0.3, 0.7), (0.0, 0.62), (end_x, 0.55)])
    assert traits_for('head', t, palm_stub()).length == word
    assert X_MIN == -0.8  # (these thresholds assume the palm picture starts at -0.8)


@pytest.mark.parametrize(('end_y', 'word'), [(0.10, 'long'), (0.30, 'medium'), (0.55, 'short')])
def test_the_life_line_is_as_long_as_it_runs_down_toward_the_wrist(end_y, word):
    t = line([(0.3, 0.9), (0.2, 0.5), (0.25, end_y)])
    assert traits_for('life', t, palm_stub()).length == word


@pytest.mark.parametrize(('top', 'word'), [(0.8, 'long'), (0.5, 'medium'), (0.2, 'short')])
def test_the_fate_line_is_as_long_as_it_climbs(top, word):
    assert traits_for('fate', line([(0.0, 0.0), (0.05, top)]), palm_stub()).length == word


@pytest.mark.parametrize(('top', 'word'), [(0.5, 'long'), (0.3, 'medium'), (0.1, 'short')])
def test_the_sun_line_is_as_long_as_it_climbs_too_but_the_bar_is_lower(top, word):
    assert traits_for('sun', line([(-0.1, 0.0), (-0.1, top)]), palm_stub()).length == word


def test_the_head_line_curves_by_how_steeply_it_slopes():
    def head(deg: float) -> str:
        run = 0.8
        return traits_for('head', line([(0.3, 0.9), (0.3 - run, 0.9 - run * np.tan(np.radians(deg)))]), palm_stub()).curve  # type: ignore[return-value]

    assert [head(5), head(20), head(40)] == ['straight', 'gentle', 'pronounced']


def arc(bow: float) -> Traced:
    x = np.linspace(0, 1, 60)
    xy = np.stack([x, 4 * bow * x * (1 - x)], axis=1)  # a parabola whose bow, as a share of the chord, is `bow`
    return Traced(xy=xy, strength=np.full(60, 1.0), score=1.0)


@pytest.mark.parametrize(
    ('fid', 'bows'),
    [('heart', (0.03, 0.08, 0.25)), ('life', (0.04, 0.12, 0.35)), ('fate', (0.03, 0.08, 0.25)), ('sun', (0.03, 0.08, 0.25))],
)
def test_the_other_lines_curve_by_how_far_they_bow(fid, bows):
    got = [traits_for(fid, arc(b), palm_stub()).curve for b in bows]
    assert got == ['straight', 'gentle', 'pronounced']


def test_a_line_is_deep_when_it_stands_out_a_lot_from_the_palms_own_creases():
    t = line([(0.0, 0.0), (0.05, 0.8)])
    assert traits_for('fate', t, palm_stub()).clarity == 'clear'
    assert traits_for('fate', line([(0.0, 0.0), (0.05, 0.8)], strong=1.3), palm_stub()).clarity == 'deep'


# ------------------------------------------------------------------ whole hands: drawn, turned, mirrored

ANGLES = [('right', 0), ('left', 0), ('right', 28), ('left', -35), ('right', 170), ('left', 100)]


def analyse_drawn(side: str, angle: float, quality: PhotoQuality = GOOD, **kw):
    image, placed = render(side, angle, **kw)  # type: ignore[arg-type]
    h, w = image.shape[:2]
    hand = found(placed, finger_stretch=kw.get('finger_stretch', 1.0))
    return analyse(side, image, hand, PhotoSize(width=w, height=h), quality), placed, (w, h)  # type: ignore[arg-type]


@pytest.fixture(scope='module', params=ANGLES, ids=[f'{s}{a:+d}' for s, a in ANGLES])
def drawn_hand(request):
    side, angle = request.param
    analysis, placed, size = analyse_drawn(side, angle)
    return SimpleNamespace(side=side, angle=angle, analysis=analysis, result=analysis.result, placed=placed, size=size)


def features(result) -> dict:
    return {f.id: f for f in result.features}


def px_path(feature, size) -> np.ndarray:
    return np.array(feature.path) * [size[0], size[1]]


def test_the_four_drawn_lines_are_found_and_the_one_not_drawn_is_not(drawn_hand):
    got = {fid: f.status for fid, f in features(drawn_hand.result).items()}
    assert got == {'heart': 'detected', 'head': 'detected', 'life': 'detected', 'fate': 'detected', 'sun': 'not_visible'}
    assert drawn_hand.analysis.view.contrast > CONTRAST_OK


def test_each_traced_line_lies_on_the_crease_that_was_drawn_and_covers_all_of_it(drawn_hand):
    unit = drawn_hand.placed.scale * L_UNIT  # one palm length, in photo pixels
    for fid, drawn_line in CREASES.items():
        path = px_path(features(drawn_hand.result)[fid], drawn_hand.size)
        truth = drawn_hand.placed.px(drawn_line)
        on_crease = distance_to_polyline(path, truth) / unit
        covered = distance_to_polyline(drawn_hand.placed.px(sample_polyline(drawn_line)), path) / unit
        assert on_crease.max() < 0.04, f'{fid}: part of the path is {on_crease.max():.3f} palm lengths off the crease'
        assert covered.mean() < 0.03, f'{fid}: the crease is not covered ({covered.mean():.3f} off on average)'
        assert covered.max() < 0.20, f'{fid}: an end of the crease is missing ({covered.max():.3f})'


def test_the_lines_are_the_same_lines_whichever_way_the_hand_is_turned_or_mirrored(drawn_hand):
    # in palm coordinates the paths of a turned or mirrored hand must match the unturned right hand's
    ref_analysis, _, ref_size = REFERENCE
    unit_here = drawn_hand.analysis.view.frame
    unit_ref = ref_analysis.view.frame
    for fid in CREASES:
        here = unit_here.to_canon(px_path(features(drawn_hand.result)[fid], drawn_hand.size))
        there = unit_ref.to_canon(px_path(features(ref_analysis.result)[fid], ref_size))
        gap = distance_to_polyline(here, there)
        assert gap.mean() < 0.03, f'{fid}: differs from the unturned hand by {gap.mean():.3f}'


REFERENCE = analyse_drawn('right', 0)


def test_how_the_lines_are_described_matches_what_was_drawn(drawn_hand):
    f = features(drawn_hand.result)
    assert f['head'].traits.length == 'medium' and f['head'].traits.curve == 'gentle'
    assert f['life'].traits.length == 'long' and f['life'].traits.curve == 'gentle'
    assert f['fate'].traits.length == 'long' and f['fate'].traits.curve == 'straight'
    assert f['heart'].traits.curve == 'straight'
    assert f['heart'].traits.length in ('long', 'medium')  # it ends close to a boundary between two fingers
    assert all(f[fid].traits.clarity in ('clear', 'deep') for fid in ('heart', 'head', 'life', 'fate'))
    assert not f['sun'].traits.model_dump(exclude_none=True)
    assert f['sun'].path == [] and f['sun'].confidence is None


def test_every_position_is_a_fraction_of_the_photo(drawn_hand):
    for f in drawn_hand.result.features:
        assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in f.path)
        box = f.searchArea
        assert 0 <= box.x <= 1 and 0 <= box.y <= 1 and box.x + box.w <= 1.0001 and box.y + box.h <= 1.0001
        if f.status == 'detected':
            assert len(f.path) >= 10
    outline = drawn_hand.result.outline
    assert outline and all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in outline)
    for c in drawn_hand.result.otherCreases:
        assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in c.path)


def test_confidence_goes_with_the_status(drawn_hand):
    for f in drawn_hand.result.features:
        if f.status == 'not_visible':
            assert f.confidence is None
        else:
            assert 0.15 <= f.confidence <= 0.95
    # lines found this clearly are reported with high confidence
    assert min(f.confidence for f in drawn_hand.result.features if f.status == 'detected') > 0.8


def test_the_result_names_the_real_method_and_the_hand_it_was_given(drawn_hand):
    r = drawn_hand.result
    assert r.side == drawn_hand.side
    assert (r.photo.width, r.photo.height) == drawn_hand.size
    assert r.methodVersion == 'palm-lines 1.1'
    assert all(f.method == 'palm-lines 1.1' for f in r.features)
    assert [f.id for f in r.features] == IDS or sorted(f.id for f in r.features) == sorted(IDS)


def test_the_shape_of_the_hand_is_measured_from_the_photo(drawn_hand):
    shape = drawn_hand.result.palmShape
    assert shape.status == 'detected'
    assert shape.traits.palm == 'square' and shape.traits.fingers == 'short'
    assert shape.palmRatio == pytest.approx(0.95, abs=0.06)  # the drawn palm is as wide as 0.94 of its length
    assert shape.fingerRatio == pytest.approx(0.957, abs=0.01)  # and the middle finger 0.957 of it


@pytest.mark.parametrize(('stretch', 'fingers'), [(1.2, 'long'), (0.8, 'short')])
def test_long_fingers_are_told_from_short_ones(stretch, fingers):
    analysis, _, _ = analyse_drawn('right', 0, finger_stretch=stretch)
    assert analysis.result.palmShape.traits.fingers == fingers


def test_a_narrow_hand_is_a_long_palm():
    analysis, _, _ = analyse_drawn('right', 0, hand_width=0.85)
    assert analysis.result.palmShape.status == 'detected'
    assert analysis.result.palmShape.traits.palm == 'long'
    assert features(analysis.result)['life'].status == 'detected'


def test_the_shape_is_only_guessed_when_the_hand_is_turned_or_the_photo_is_poor():
    image, placed = render('right', 0)
    hand = found(placed)
    size = PhotoSize(width=1300, height=1300)
    poor = analyse('right', image, hand, size, PhotoQuality(sharpness='poor', lighting='poor', resolution='fair', palmVisible=True, score=0.3))
    assert poor.result.palmShape.status == 'uncertain' and poor.result.palmShape.palmRatio is None
    assert features(poor.result)['life'].status == 'detected'  # the lines do not depend on that
    cut = analyse('right', image, hand, size, GOOD, cut_off=True)
    assert cut.result.palmShape.status == 'uncertain'


# ------------------------------------------------------------------ what must NOT be found


def test_a_palm_with_no_lines_gets_no_lines():
    analysis, _, _ = analyse_drawn('right', 0, creases=())
    assert {f.status for f in analysis.result.features} == {'not_visible'}
    assert all(f.path == [] for f in analysis.result.features)
    assert analysis.view.contrast < CONTRAST_NONE  # random wrinkles are not enough contrast to say anything


def test_a_line_that_was_not_drawn_is_not_called_detected():
    analysis, _, _ = analyse_drawn('left', 0, creases=('life', 'head', 'heart'))
    got = {f.id: f.status for f in analysis.result.features}
    assert got['fate'] != 'detected' and got['sun'] != 'detected'
    assert got['life'] == got['head'] == got['heart'] == 'detected'


def test_a_blurred_photo_loses_the_lines_instead_of_inventing_them():
    image, placed = render('right', 0)
    size = PhotoSize(width=1300, height=1300)
    sharp = analyse('right', image, found(placed), size, GOOD).result
    assert sum(f.status == 'detected' for f in sharp.features) == 4
    for sigma in (10, 20):
        blurred = cv2.GaussianBlur(image, (0, 0), sigma)
        got = analyse('right', blurred, found(placed), size, GOOD).result
        assert {f.status for f in got.features} == {'not_visible'}, f'blur {sigma}'


def test_faint_creases_are_not_called_detected():
    analysis, _, _ = analyse_drawn('right', 0, depth=9)
    assert 'detected' not in {f.status for f in analysis.result.features}


def test_every_line_is_at_most_uncertain_when_the_contrast_is_borderline():
    analysis, _, _ = analyse_drawn('right', 0, creases=('heart', 'head'))
    assert 'detected' not in {f.status for f in analysis.result.features if f.id not in ('heart', 'head')}


# ------------------------------------------------------------------ a different size, a different light, a different file


def test_the_same_photo_gives_exactly_the_same_reading_every_time():
    first = analyse_drawn('left', -35)[0].result
    for _ in range(2):
        assert analyse_drawn('left', -35)[0].result.model_dump() == first.model_dump()


def test_a_smaller_picture_gives_the_same_lines():
    big, _, _ = analyse_drawn('right', 0)
    small, _, size = analyse_drawn('right', 0, scale=330, size=(900, 900))
    assert {f.id: f.status for f in small.result.features} == {f.id: f.status for f in big.result.features}
    for fid in CREASES:
        a = big.view.frame.to_canon(px_path(features(big.result)[fid], (1300, 1300)))
        b = small.view.frame.to_canon(px_path(features(small.result)[fid], size))
        assert distance_to_polyline(b, a).mean() < 0.03


def test_brightness_and_jpeg_compression_do_not_move_the_lines():
    image, placed = render('right', 0)
    size = PhotoSize(width=1300, height=1300)
    base = analyse('right', image, found(placed), size, GOOD)
    dim = np.clip(image.astype(np.float32) * 0.55 + 5, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 55])
    assert ok
    squeezed = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    for name, changed in (('dim', dim), ('jpeg 55', squeezed)):
        got = analyse('right', changed, found(placed), size, GOOD)
        assert {f.id: f.status for f in got.result.features} == {f.id: f.status for f in base.result.features}, name
        for fid in CREASES:
            a = base.view.frame.to_canon(px_path(features(base.result)[fid], (1300, 1300)))
            b = got.view.frame.to_canon(px_path(features(got.result)[fid], (1300, 1300)))
            assert distance_to_polyline(b, a).mean() < 0.03, f'{name}: {fid}'


# ------------------------------------------------------------------ giving up gracefully


def test_landmarks_that_cannot_be_straightened_give_a_reading_with_nothing_found_not_an_error():
    image, placed = render('right', 0)
    hand = found(placed)
    squeezed = type(hand)(points=hand.points[0] + (hand.points - hand.points[0]) * 0.02, label='right', score=0.97)
    result = analyse('right', image, squeezed, PhotoSize(width=1300, height=1300), GOOD).result
    assert {f.status for f in result.features} == {'not_visible'}
    assert result.palmShape.status == 'not_visible'
    assert result.outline is None and result.otherCreases == []


def test_a_cancelled_reading_stops_without_a_result_worth_keeping():
    image, placed = render('right', 0)
    result = analyse('right', image, found(placed), PhotoSize(width=1300, height=1300), GOOD, cancelled=lambda: True).result
    assert {f.status for f in result.features} == {'not_visible'}


def test_other_creases_are_short_and_few_and_never_on_a_line_already_found(drawn_hand):
    others = drawn_hand.result.otherCreases
    assert len(others) <= 3
    found_paths = [px_path(f, drawn_hand.size) for f in drawn_hand.result.features if f.path]
    for c in others:
        mine = np.array(c.path) * drawn_hand.size
        assert len(mine) >= 2
        # a crease that is not one of the five is not lying along one of them
        away = min(float(np.median(distance_to_polyline(mine, p))) for p in found_paths)
        assert away / (drawn_hand.placed.scale * L_UNIT) > 0.04


def test_positions_survive_a_different_picture_size_for_the_same_hand():
    # the same hand in a taller picture: the result is in fractions, so the lines move with the picture
    image, placed = render('right', 0, size=(1300, 1500))
    hand = found(placed)
    result = analyse('right', image, hand, PhotoSize(width=1300, height=1500), GOOD).result
    f = features(result)['life']
    truth = placed.px(CREASES['life'])
    path = np.array(f.path) * [1300, 1500]
    assert distance_to_polyline(path, truth).max() / (placed.scale * L_UNIT) < 0.04
    assert to_norm is not None and Placed is not None  # (kept imported for the helpers above)


# ------------------------------------------------------------------ the fold at the base of the thumb

KNUCKLES = {'i': 0.35, 'm': 0.10, 'r': -0.15, 'p': -0.40, 't': 0.42}


def test_the_up_and_down_lines_stay_on_the_palm_side_of_the_thumb_base():
    """The fold where the thumb meets the palm is a deep, straight crease. On two of six real hands the tracer took it for the
    life line (and, once that was closed off, for the fate line). The life, fate and sun lines may not run past it."""
    edge = thumb_edge(KNUCKLES)
    assert edge == pytest.approx(0.42 - THUMB_MARGIN)
    zs = zones(KNUCKLES)
    for fid in ('life', 'fate', 'sun'):
        assert max(x for x, _ in zs[fid].corridor) <= edge + 1e-9
        assert max(x for x, _ in zs[fid].start) <= edge + 1e-9
    # the heart and head lines reach the index finger's side as before: the rule is only for the up-and-down lines
    assert max(x for x, _ in zs['heart'].corridor) == pytest.approx(KNUCKLES['i'] + 0.15)
    assert max(x for x, _ in zs['head'].corridor) == pytest.approx(KNUCKLES['i'] + 0.15)


def test_a_pixel_on_the_thumb_fold_is_outside_the_life_line_search_area():
    edge = thumb_edge(KNUCKLES)
    mask = polygon_mask(zones(KNUCKLES)['life'].corridor)
    inside_c, inside_r = to_px(edge - 0.05, 0.6)
    fold_c, fold_r = to_px(edge + 0.05, 0.6)
    assert mask[round(inside_r), round(inside_c)]
    assert not mask[round(fold_r), round(fold_c)]


def test_without_the_thumb_base_the_index_knuckle_sets_the_limit():
    no_thumb = {k: v for k, v in KNUCKLES.items() if k != 't'}
    assert thumb_edge(no_thumb) == pytest.approx(0.35 - THUMB_MARGIN)
    # a thumb base nearer the palm's middle than the index knuckle does not pull the limit inward
    assert thumb_edge({**KNUCKLES, 't': 0.20}) == pytest.approx(0.35 - THUMB_MARGIN)
