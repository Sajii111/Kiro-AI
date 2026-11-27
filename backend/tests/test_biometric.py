"""The palm lock (ICA 02): the square from the palm, the preprocessing, both methods, the spare, matching, the
calibration, sealed templates, and enrolment and verification from start to finish.

Drawn hands stand in for people (see synth.py). One drawn "person" is one random seed: the principal lines are the same
for everyone, but the small wrinkles and their places are the seed's own. That is harder than real palms, whose principal
lines differ too, so a method that tells drawn people apart is using the fine detail. The same seed drawn turned, closer
or further, and lighter or darker is the same person photographed again.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from synth import FakeFinder, found, jpeg, render

from app.cv.biometric import compcode, crease, lbp
from app.cv.biometric.config import (
    DEFAULT,
    ENGINE_VERSION,
    CompCodeSettings,
    EngineSettings,
    RoiSettings,
    config_hash,
)
from app.cv.biometric.engine import (
    EnrolProblem,
    Extraction,
    Problem,
    auth_photo_problem,
    enrol,
    extract,
    extract_from_image,
    verify,
)
from app.cv.biometric.evaluate import calibrate, eer_threshold, rates
from app.cv.biometric.match import (
    CALIBRATION_PATH,
    Calibration,
    CalibrationError,
    Normaliser,
    calibration_from_json,
    load_calibration,
    raw_scores,
)
from app.cv.biometric.prep import prepare
from app.cv.biometric.roi import RoiProblem, crop_roi, knuckle_frame, roi_matrix
from app.cv.biometric.template import (
    Template,
    TemplateError,
    TemplateOutdated,
    new_key,
    seal,
    unseal,
)
from app.cv.hand import INDEX_MCP, PINKY_MCP, WRIST, hand_frame
from app.cv.images import check_photo

SHOTS = [(0, 480, 1.0), (12, 430, 0.9), (-15, 520, 1.1), (25, 460, 1.0), (-6, 500, 0.95)]


def shot(person: int, k: int, side: str = 'right') -> tuple[np.ndarray, object]:
    angle, scale, gain = SHOTS[k]
    img, placed = render(side=side, angle=angle, scale=scale, seed=100 + person)
    rng = np.random.default_rng(1000 * person + k + (500 if side == 'left' else 0))
    img = np.clip(img.astype(np.float32) * gain + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
    return img, placed


def extraction(person: int, k: int, side: str = 'right') -> Extraction:
    img, placed = shot(person, k, side)
    e = extract_from_image(img, found(placed).points, side)
    assert isinstance(e, Extraction), e
    return e


DRAWN_CALIBRATION = Path(__file__).resolve().parent / 'data' / 'calibration-drawn.json'


@pytest.fixture(scope='module')
def people() -> dict[int, list[Extraction]]:
    return {p: [extraction(p, k) for k in range(len(SHOTS))] for p in range(4)}


@pytest.fixture(scope='module')
def cal() -> Calibration:
    return load_calibration(DRAWN_CALIBRATION)


# ------------------------------------------------------------------ step 1: the square


def test_the_square_is_upright_with_the_thumb_to_the_right():
    _img, placed = render(angle=30)
    points = found(placed).points
    m, _ = roi_matrix(points, DEFAULT.roi)
    from app.cv.biometric.roi import corners_of

    tl, tr, _br, bl = corners_of(m, DEFAULT.roi.size)
    # the top edge is toward the fingers, the bottom toward the wrist
    assert np.linalg.norm(tl - points[WRIST]) > np.linalg.norm(bl - points[WRIST])
    # the right edge is the thumb side: the top-right corner is nearer the index knuckle, the top-left nearer the little finger's
    assert np.linalg.norm(tr - points[INDEX_MCP]) < np.linalg.norm(tr - points[PINKY_MCP])
    assert np.linalg.norm(tl - points[PINKY_MCP]) < np.linalg.norm(tl - points[INDEX_MCP])


@pytest.mark.parametrize('side', ['right', 'left'])
def test_the_same_palm_gives_the_same_square_however_it_is_turned_or_how_close(side):
    squares = []
    for angle, scale in ((0, 480), (35, 420), (-20, 560)):
        img, placed = render(side=side, angle=angle, scale=scale, seed=7)
        roi = crop_roi(img, found(placed).points, DEFAULT.roi)
        assert not isinstance(roi, RoiProblem), roi
        assert roi.image.shape == (128, 128, 3) and roi.inside >= 0.95
        squares.append(prepare(roi.image, DEFAULT.prep).norm)
    for other in squares[1:]:
        assert np.corrcoef(squares[0].ravel(), other.ravel())[0, 1] > 0.8


def test_the_square_comes_from_the_knuckles_and_ignores_the_wrist_point():
    """The wrist point is the least steady landmark (a bent wrist, more or less forearm in the picture). It must not move the
    square: only the four knuckles place it."""
    _img, placed = render(angle=10, seed=7)
    points = found(placed).points
    palm = hand_frame(points)
    assert palm is not None
    m, step = roi_matrix(points, DEFAULT.roi)
    moved = points.copy()
    moved[WRIST] = moved[WRIST] + 0.15 * palm.length * palm.v - 0.10 * palm.length * palm.u  # sideways, and further from the knuckles
    m2, step2 = roi_matrix(moved, DEFAULT.roi)
    assert np.allclose(m, m2) and step == step2


def test_the_square_sits_at_the_set_height_below_the_knuckle_line():
    _img, placed = render(angle=25, seed=7)
    points = found(placed).points
    frame = knuckle_frame(points)
    assert frame is not None
    m, step = roi_matrix(points, DEFAULT.roi)
    n = DEFAULT.roi.size
    middle = m @ np.array([(n - 1) / 2, (n - 1) / 2, 1.0])
    d = middle - frame.origin
    assert d @ frame.u == pytest.approx(-DEFAULT.roi.center_below * frame.span, abs=1e-6)  # below the line, toward the wrist
    assert abs(d @ frame.v) < 1e-6  # in the middle of the knuckles, sideways
    assert step * n == pytest.approx(DEFAULT.roi.side_scale * frame.span)


def test_a_left_palm_comes_out_as_the_mirror_of_the_same_right_palm():
    right, rp = render(side='right', seed=7)
    left, lp = render(side='left', seed=7)
    r = crop_roi(right, found(rp).points, DEFAULT.roi)
    lt = crop_roi(left, found(lp).points, DEFAULT.roi)
    a, b = prepare(r.image, DEFAULT.prep).norm, prepare(lt.image, DEFAULT.prep).norm
    assert np.corrcoef(a.ravel(), b.ravel())[0, 1] > 0.8  # the frame already mirrors a left hand, so they line up


def test_a_palm_too_small_in_the_photo_is_refused():
    img, placed = render(scale=120, size=(400, 400))
    out = crop_roi(img, found(placed).points, DEFAULT.roi)
    assert isinstance(out, RoiProblem) and out.code == 'too_small'


def test_a_palm_cut_off_by_the_edge_is_refused():
    img, placed = render()
    half = np.ascontiguousarray(img[:, :640])  # the middle of the palm is at x = 650
    out = crop_roi(half, found(placed).points, DEFAULT.roi)
    assert isinstance(out, RoiProblem) and out.code == 'palm_cut_off'


def test_a_square_that_is_not_on_the_hand_is_refused():
    img, placed = render()
    nothing = np.zeros(img.shape[:2], bool)
    out = crop_roi(img, found(placed).points, DEFAULT.roi, silhouette=nothing)
    assert isinstance(out, RoiProblem) and out.code == 'off_hand'


def test_landmarks_that_do_not_make_a_hand_are_refused():
    img, _ = render()
    out = crop_roi(img, np.zeros((21, 2)), DEFAULT.roi)
    assert isinstance(out, RoiProblem) and out.code == 'no_hand'


# ------------------------------------------------------------------ step 2: preprocessing


def test_preprocessing_is_normalised_and_does_not_care_about_brightness():
    img, placed = render(seed=3)
    roi = crop_roi(img, found(placed).points, DEFAULT.roi)
    a = prepare(roi.image, DEFAULT.prep)
    darker = prepare(np.clip(roi.image.astype(np.float32) * 0.75, 0, 255).astype(np.uint8), DEFAULT.prep)
    assert abs(float(a.norm.mean())) < 1e-3 and abs(float(a.norm.std()) - 1) < 1e-3
    assert a.contrast.dtype == np.uint8 and a.norm.dtype == np.float32
    assert np.corrcoef(a.norm.ravel(), darker.norm.ravel())[0, 1] > 0.95


def test_a_featureless_palm_is_an_invalid_image():
    img, placed = render(seed=3, creases=(), wrinkles=0)
    plain = cv2.GaussianBlur(img, (0, 0), 6)  # no creases, and blurred: nothing to recognise
    out = extract_from_image(plain, found(placed).points, 'right')
    assert isinstance(out, Problem) and out.code == 'too_flat'


# ------------------------------------------------------------------ method A: creases


def test_the_crease_map_finds_the_drawn_creases(people):
    e = people[0][0]
    lines = e.detail.lines
    assert 0.03 < lines.mean() <= DEFAULT.crease.keep
    assert e.features.crease.map.shape == (DEFAULT.crease.map_size,) * 2
    grid = e.features.crease.grid
    assert grid.shape == (DEFAULT.crease.grid, DEFAULT.crease.grid, DEFAULT.crease.bins)
    norms = np.linalg.norm(grid, axis=2)
    assert np.all((np.abs(norms - 1) < 1e-4) | (norms == 0))


def test_crease_similarity_is_one_for_itself_and_forgives_a_small_shift(people):
    f = people[0][0].features.crease
    assert crease.similarity(f, f, DEFAULT.crease) == pytest.approx(1.0, abs=1e-6)
    moved = dataclasses.replace(f, map=np.roll(f.map, (2, -1), axis=(0, 1)))
    assert crease.similarity(f, moved, DEFAULT.crease) > 0.95


# ------------------------------------------------------------------ method B: competitive code


@pytest.mark.parametrize(('direction', 'expected'), [('vertical', 0), ('horizontal', 3)])
def test_the_competitive_code_names_the_direction_of_dark_lines(direction, expected):
    img = np.full((128, 128), 200, np.uint8)
    for at in range(8, 128, 12):
        if direction == 'vertical':
            cv2.line(img, (at, 0), (at, 127), 120, 2)
        else:
            cv2.line(img, (0, at), (127, at), 120, 2)
    norm = ((img - img.mean()) / img.std()).astype(np.float32)
    f = compcode.extract(norm, DEFAULT.compcode)
    codes = f.code[f.valid]
    assert len(codes) > 100
    assert np.mean(codes == expected) > 0.9


def test_competitive_code_distance_is_zero_for_itself_and_about_half_for_noise():
    s = CompCodeSettings()
    rng = np.random.default_rng(0)
    a = compcode.CompCodeFeature(code=rng.integers(0, 6, (32, 32)).astype(np.uint8), valid=np.ones((32, 32), bool))
    b = compcode.CompCodeFeature(code=rng.integers(0, 6, (32, 32)).astype(np.uint8), valid=np.ones((32, 32), bool))
    assert compcode.distance(a, a, s) == 0.0
    assert 0.35 < compcode.distance(a, b, s) < 0.55  # the best of 25 shifts of unrelated codes is a little under 0.5
    none = compcode.CompCodeFeature(code=a.code, valid=np.zeros((32, 32), bool))
    assert compcode.distance(a, none, s) == 1.0  # nothing comparable counts as nothing alike


# ------------------------------------------------------------------ the spare: LBP


def test_lbp_histograms_and_similarity(people):
    h = people[0][0].features.lbp
    assert h.shape == (DEFAULT.lbp.grid, DEFAULT.lbp.grid, lbp.BINS)
    assert np.allclose(h.sum(axis=2), 1.0, atol=1e-5)
    assert lbp.similarity(h, h) == pytest.approx(1.0)
    assert lbp.similarity(h, people[1][0].features.lbp) < 1.0


# ------------------------------------------------------------------ every method tells drawn people apart


@pytest.mark.parametrize('method', ['crease', 'compcode', 'lbp'])
def test_each_method_scores_the_same_person_higher_than_different_people(people, method):
    same = [raw_scores(a.features, b.features)[method] for v in people.values() for i, a in enumerate(v) for b in v[i + 1 :]]
    different = [raw_scores(people[p][0].features, people[q][k].features)[method] for p in people for q in people if q > p for k in range(3)]
    assert np.mean(same) > np.mean(different)
    if method == 'compcode':
        assert min(same) > max(different)  # the competitive code separates them completely


# ------------------------------------------------------------------ matching and the calibration


def test_a_normaliser_maps_impostor_to_zero_and_genuine_to_one():
    n = Normaliser(impostor=0.5, genuine=0.9)
    assert n.apply(0.5) == 0.0 and n.apply(0.9) == 1.0 and n.apply(0.7) == pytest.approx(0.5)
    assert n.apply(0.1) == 0.0 and n.apply(1.0) == 1.0
    assert Normaliser(0.6, 0.6).apply(0.9) == 0.0


def test_the_drawn_hand_calibration_belongs_to_these_settings(cal):
    """What the tests run on (it loading at all means its settings hash matches the engine's)."""
    assert cal.engine_version == ENGINE_VERSION and cal.config_hash == config_hash(DEFAULT)
    assert 0.0 < cal.threshold < 1.0
    assert set(cal.weights) == set(DEFAULT.match.methods) and set(cal.weights) <= set(cal.normalisers)


def test_the_tests_never_read_the_shipped_calibration():
    """`run.bat palm --calibrate` rewrites backend/app/cv/biometric/calibration.json with real-hand numbers. Everything the tests
    (and the app they start) load must stay the fixed drawn-hand file, or drawn impostors would start to match."""
    from app.cv.biometric import match

    assert Path(match.CALIBRATION_PATH).resolve() == DRAWN_CALIBRATION.resolve()
    assert load_calibration() == load_calibration(DRAWN_CALIBRATION)
    assert CALIBRATION_PATH.resolve() != DRAWN_CALIBRATION.resolve()  # the shipped file is a different file


def test_the_shipped_calibration_belongs_to_these_settings():
    """The file the website uses (and `run.bat palm --calibrate` rewrites): whatever was measured, it must fit this engine."""
    shipped = load_calibration(CALIBRATION_PATH)
    assert shipped.engine_version == ENGINE_VERSION and shipped.config_hash == config_hash(DEFAULT)
    assert 0.0 < shipped.threshold < 1.0
    assert set(shipped.weights) == set(DEFAULT.match.methods) and set(shipped.weights) <= set(shipped.normalisers)
    assert calibration_from_json(json.loads(CALIBRATION_PATH.read_text(encoding='utf-8'))) == shipped


def test_a_calibration_made_with_other_settings_is_refused(tmp_path):
    data = json.loads(CALIBRATION_PATH.read_text(encoding='utf-8'))
    data['config_hash'] = '0000000000000000'
    path = tmp_path / 'calibration.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(CalibrationError):
        load_calibration(path)
    path.write_text('{"calibrated": true}', encoding='utf-8')
    with pytest.raises(CalibrationError):
        load_calibration(path)
    with pytest.raises(CalibrationError):
        load_calibration(tmp_path / 'missing.json')


def test_changing_a_setting_changes_the_hash():
    other = EngineSettings(roi=RoiSettings(center_below=0.8))
    assert config_hash(other) != config_hash(DEFAULT)
    assert config_hash(EngineSettings()) == config_hash(DEFAULT)


def test_the_fused_score_is_the_weighted_mean_of_the_normalised_scores():
    c = Calibration(
        calibrated=False,
        threshold=0.5,
        normalisers={'crease': Normaliser(0.0, 1.0), 'compcode': Normaliser(0.5, 1.0), 'lbp': Normaliser(0.0, 1.0)},
        weights={'crease': 0.25, 'compcode': 0.75},
        source='test',
        engine_version=ENGINE_VERSION,
        config_hash=config_hash(DEFAULT),
    )
    assert c.fuse({'crease': 0.4, 'compcode': 0.75, 'lbp': 0.0}) == pytest.approx(0.25 * 0.4 + 0.75 * 0.5)


# ------------------------------------------------------------------ measuring and setting the threshold


def test_error_rates_and_the_equal_error_threshold():
    genuine = np.array([0.7, 0.8, 0.9, 0.95])
    impostor = np.array([0.1, 0.2, 0.3, 0.4])
    t, eer = eer_threshold(genuine, impostor)
    assert t == pytest.approx(0.55) and eer == 0.0
    assert rates(genuine, impostor, t) == (0.0, 0.0)
    assert rates(genuine, impostor, 0.85) == (0.0, 0.5)
    t, eer = eer_threshold(np.array([0.3, 0.6, 0.7, 0.8]), np.array([0.1, 0.2, 0.4, 0.65]))
    far, frr = rates(np.array([0.3, 0.6, 0.7, 0.8]), np.array([0.1, 0.2, 0.4, 0.65]), t)
    assert far == frr == eer == 0.25


def test_calibrating_on_drawn_people_separates_them(people):
    c, pairs = calibrate({str(p): [e.features for e in v] for p, v in people.items()}, 'test', calibrated=False)
    assert len(pairs.genuine) == 4 * 10 and len(pairs.impostor) == 6 * 25
    assert c.measured['eer'] < 0.1 and c.measured['genuine_mean'] > c.measured['impostor_mean'] + 0.4
    assert c.config_hash == config_hash(DEFAULT) and not c.calibrated


# ------------------------------------------------------------------ sealed templates


def test_a_sealed_template_opens_with_its_key_and_holds_the_same_features(people):
    template = Template(side='right', samples=[e.features for e in people[0][:3]])
    key = new_key()
    sealed = seal(template, key)
    assert b'crease_map' not in sealed and len(sealed) < 100_000
    back = unseal(sealed, key)
    assert back.side == 'right' and len(back.samples) == 3
    for a, b in zip(template.samples, back.samples, strict=True):
        assert np.array_equal(a.compcode.code, b.compcode.code) and np.array_equal(a.compcode.valid, b.compcode.valid)
        assert np.allclose(a.crease.map, b.crease.map, atol=2e-3)
        assert raw_scores(a, b)['compcode'] == 1.0


def test_a_sealed_template_cannot_be_opened_with_another_key_or_after_a_change(people):
    template = Template(side='right', samples=[people[0][0].features])
    sealed = seal(template, new_key())
    with pytest.raises(TemplateError):
        unseal(sealed, new_key())
    key = new_key()
    sealed = bytearray(seal(template, key))
    sealed[60] ^= 1
    with pytest.raises(TemplateError):
        unseal(bytes(sealed), key)


def test_a_template_from_other_settings_is_outdated(people):
    key = new_key()
    old = Template(side='right', samples=[people[0][0].features], config_hash='0000000000000000')
    with pytest.raises(TemplateOutdated):
        unseal(seal(old, key), key)


# ------------------------------------------------------------------ from a photo to an outcome


def checked(person: int, k: int, side: str = 'right', slot: str | None = None, hands: int = 1):
    """A drawn photo of `side` put through the photo checks as the `slot` hand (the same side unless given)."""
    img, placed = shot(person, k, side)
    hand = found(placed)
    finder = FakeFinder({(img.shape[1], img.shape[0]): [hand] * hands})
    return check_photo(jpeg(img), slot or side, 24_000_000, finder)  # type: ignore[arg-type]


def test_lock_with_three_photos_then_open_with_a_fourth(cal):
    template = enrol([extract(checked(0, k)) for k in range(3)], 'right', cal)  # type: ignore[misc]
    assert isinstance(template, Template), template
    d = verify(template, extract(checked(0, 3)), cal)
    assert d.outcome == 'success' and d.title == 'Authentication Successful'
    assert d.score is not None and d.score >= d.threshold == cal.threshold
    assert set(d.methods) == {'crease', 'compcode'} and set(d.raw) == {'crease', 'compcode', 'lbp'}
    assert d.best_sample in (0, 1, 2) and d.problem is None and d.calibrated == cal.calibrated

    other = verify(template, extract(checked(2, 0)), cal)
    assert other.outcome == 'failed' and other.title == 'Authentication Failed'
    assert other.score is not None and other.score < other.threshold


def test_a_photo_without_a_hand_is_an_invalid_image_with_no_score(cal):
    img, _ = shot(0, 0)
    no_hand = check_photo(jpeg(img), 'right', 24_000_000, FakeFinder())  # type: ignore[arg-type]
    problem = extract(no_hand)
    assert isinstance(problem, Problem)
    template = Template(side='right', samples=[extraction(0, 0).features])
    d = verify(template, problem, cal)
    assert d.outcome == 'invalid_image' and d.title == 'Invalid Image'
    assert d.score is None and d.methods == {} and d.reason and d.problem == problem.code


def test_the_wrong_hand_two_hands_and_a_tilted_palm_are_invalid_images():
    wrong = checked(0, 0, side='left', slot='right')
    assert wrong.ok  # a reading only warns about this, and carries on
    problem = auth_photo_problem(wrong)
    assert problem is not None and problem.code == 'wrong_hand'
    two = auth_photo_problem(checked(0, 0, hands=2))
    assert two is not None and two.code == 'two_hands'
    tilted = checked(0, 0)
    tilted.facts = dataclasses.replace(tilted.facts, flatness=0.35)  # type: ignore[arg-type]
    problem = auth_photo_problem(tilted)
    assert problem is not None and problem.code == 'tilted'
    assert auth_photo_problem(checked(0, 0)) is None


def test_a_photo_of_the_other_hand_does_not_open_a_lock(cal):
    template = Template(side='left', samples=[extraction(0, 0, 'left').features])
    d = verify(template, extraction(0, 0, 'right'), cal)
    assert d.outcome == 'invalid_image' and d.problem == 'wrong_hand'


def test_enrolment_needs_enough_photos_and_points_out_one_that_does_not_match(people, cal):
    few = enrol(people[0][:2], 'right', cal)
    assert isinstance(few, EnrolProblem) and few.code == 'too_few'
    many = enrol(people[0] + [people[1][0]], 'right', cal)
    assert isinstance(many, EnrolProblem) and many.code == 'too_many'
    mixed = enrol([people[0][0], people[0][2], people[2][0], people[0][3]], 'right', cal)
    assert isinstance(mixed, EnrolProblem) and mixed.code == 'inconsistent' and mixed.photo == 2
    left = enrol(people[0][:3], 'left', cal)
    assert isinstance(left, EnrolProblem) and left.code == 'wrong_hand'


def test_a_template_from_another_version_is_not_compared(people, cal):
    old = Template(side='right', samples=[people[0][0].features], config_hash='0000000000000000')
    with pytest.raises(TemplateOutdated):
        verify(old, people[0][1], cal)


def test_every_step_is_timed(people):
    assert set(people[0][0].timings) == {'roi', 'prep', 'crease', 'compcode', 'lbp'}
    assert all(v >= 0 for v in people[0][0].timings.values())
