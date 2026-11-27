"""The palm lock from start to finish: a checked photo in, an outcome out.

    extract(checked)              photo -> features, or a Problem (the photo cannot be judged)
    enrol([extraction, ...])      3-5 photos of one palm -> a Template, or an EnrolProblem
    verify(template, extraction)  one new photo against a template -> a Decision

A Decision's outcome is one of three:

    success        Authentication Successful: the score reached the threshold
    failed         Authentication Failed: the score is below the threshold
    invalid_image  Invalid Image: the photo could not be judged (no hand, wrong hand, blurred...), so no score

An Invalid Image never counts as a failed attempt, because nobody was refused: the photo was.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from app.cv.images import SECOND_HAND, TILTED_PALM, CheckedPhoto

from . import compcode, crease, lbp
from .config import DEFAULT, ENGINE_VERSION, EngineSettings, config_hash
from .crease import CreaseDetail
from .match import Calibration, Features, raw_scores
from .prep import Prepared, prepare
from .roi import Roi, RoiProblem, crop_roi
from .template import Template, TemplateOutdated

Outcome = Literal['success', 'failed', 'invalid_image']
OUTCOME_TITLES: dict[str, str] = {
    'success': 'Authentication Successful',
    'failed': 'Authentication Failed',
    'invalid_image': 'Invalid Image',
}


@dataclass(frozen=True)
class Problem:
    """Why a photo cannot be judged. `message` says what to do next."""

    code: str
    message: str


@dataclass
class Extraction:
    side: str
    features: Features
    roi: Roi
    prepared: Prepared
    detail: CreaseDetail
    #: milliseconds each step took
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    #: the fused score, 0 to 1, or None for an invalid image
    score: float | None
    threshold: float
    #: each deciding method's normalised score for the best-matching enrolment photo (0 to 1)
    methods: dict[str, float]
    #: every method's own similarity before normalising, the spare one included
    raw: dict[str, float]
    #: which enrolment photo matched best (0-based), or None
    best_sample: int | None
    #: one plain sentence for the person and the attempt log
    reason: str
    problem: str | None = None
    calibrated: bool = False
    engine_version: str = ENGINE_VERSION

    @property
    def title(self) -> str:
        return OUTCOME_TITLES[self.outcome]


@dataclass(frozen=True)
class EnrolProblem:
    code: str
    message: str
    #: the photo (0-based) to take again, when one photo is the trouble
    photo: int | None = None


# ------------------------------------------------------------------ one photo


def auth_photo_problem(checked: CheckedPhoto) -> Problem | None:
    """The photo checks, stricter than a reading's: a reading copes with a warning, a lock does not compare the wrong
    hand, two hands or a tilted palm."""
    if not checked.ok:
        return Problem('photo_checks', checked.first_problem())
    if checked.hand is None or checked.analysis is None or checked.facts is None:
        return Problem('no_hand', 'We could not find a hand in this photo. Hold the whole palm flat to the camera in even light, then take it again.')
    facts = checked.facts
    if checked.hand_count > 1 and checked.second_hand_ratio >= SECOND_HAND:
        return Problem('two_hands', 'Two hands are in this photo. Photograph only the hand for this lock, then take it again.')
    if facts.side_matches is False:
        other = 'right' if checked.side == 'left' else 'left'
        return Problem(
            'wrong_hand',
            f'This looks like a {other} hand, but this lock uses the {checked.side} hand. Use the {checked.side} hand (a selfie-mode photo can come out mirrored).',
        )
    if facts.flatness < TILTED_PALM:
        return Problem('tilted', 'The palm is tilted away from the camera. Hold it flat and facing the camera, then take it again.')
    return None


def extract_from_image(bgr: np.ndarray, points: np.ndarray, side: str, settings: EngineSettings = DEFAULT, silhouette: np.ndarray | None = None) -> Extraction | Problem:
    """The features of the palm in `bgr`, whose 21 landmarks are `points` (pixels of `bgr`)."""
    timings: dict[str, float] = {}
    t = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal t
        now = time.perf_counter()
        timings[name] = round((now - t) * 1000, 1)
        t = now

    roi = crop_roi(bgr, points, settings.roi, silhouette)
    if isinstance(roi, RoiProblem):
        return Problem(roi.code, roi.message)
    lap('roi')
    prepared = prepare(roi.image, settings.prep)
    if prepared.spread < settings.prep.min_spread:
        return Problem('too_flat', 'The palm shows almost no detail: the photo is blurred, too dark or too bright. Take it again in even light, holding still.')
    lap('prep')
    crease_feature, detail = crease.extract(prepared.norm, settings.crease)
    lap('crease')
    code = compcode.extract(prepared.norm, settings.compcode)
    lap('compcode')
    texture = lbp.extract(prepared.contrast, settings.lbp)
    lap('lbp')
    features = Features(crease=crease_feature, compcode=code, lbp=texture)
    return Extraction(side=side, features=features, roi=roi, prepared=prepared, detail=detail, timings=timings)


def extract(checked: CheckedPhoto, settings: EngineSettings = DEFAULT) -> Extraction | Problem:
    """The features of a photo that went through `check_photo` with the hand model."""
    problem = auth_photo_problem(checked)
    if problem is not None:
        return problem
    assert checked.analysis is not None and checked.hand is not None
    return extract_from_image(checked.analysis, checked.hand.points, checked.side, settings)


# ------------------------------------------------------------------ comparing


def compare(a: Features, b: Features, cal: Calibration, settings: EngineSettings = DEFAULT) -> tuple[float, dict[str, float], dict[str, float]]:
    """(fused score, normalised scores of the deciding methods, raw scores of every method) for two photos."""
    raw = raw_scores(a, b, settings)
    norm = {m: v for m, v in cal.normalised(raw).items() if m in cal.weights}
    return cal.fuse(raw), norm, raw


def score_matrix(samples: list[Features], cal: Calibration, settings: EngineSettings = DEFAULT) -> np.ndarray:
    n = len(samples)
    out = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            out[i, j] = out[j, i] = compare(samples[i], samples[j], cal, settings)[0]
    return out


# ------------------------------------------------------------------ locking and opening


def enrol(extractions: list[Extraction], side: str, cal: Calibration, settings: EngineSettings = DEFAULT) -> Template | EnrolProblem:
    """A template from 3-5 photos of the same palm. Every photo must match the others: a photo of someone else, or a
    poor one, would weaken the lock, so it is pointed out and must be taken again."""
    need, most = settings.match.enrol_min, settings.match.enrol_max
    if len(extractions) < need:
        return EnrolProblem('too_few', f'Locking a profile needs {need} photos of the palm. {len(extractions)} were given.')
    if len(extractions) > most:
        return EnrolProblem('too_many', f'Locking a profile takes at most {most} photos.')
    for i, e in enumerate(extractions):
        if e.side != side:
            return EnrolProblem('wrong_hand', f'Photo {i + 1} is not the {side} hand.', i)
    samples = [e.features for e in extractions]
    scores = score_matrix(samples, cal, settings)
    n = len(samples)
    agreement = (scores.sum(axis=1) - 1.0) / (n - 1)  # each photo's mean score against the others
    worst = int(np.argmin(agreement))
    if agreement[worst] < cal.threshold + settings.match.consistency_margin:
        return EnrolProblem(
            'inconsistent',
            f'Photo {worst + 1} does not match the others well enough. Take it again: the same palm, flat and open, in the same light.',
            worst,
        )
    return Template(side=side, samples=samples, engine_version=ENGINE_VERSION, config_hash=config_hash(settings))


def invalid(problem: Problem, cal: Calibration) -> Decision:
    return Decision(
        outcome='invalid_image',
        score=None,
        threshold=cal.threshold,
        methods={},
        raw={},
        best_sample=None,
        reason=problem.message,
        problem=problem.code,
        calibrated=cal.calibrated,
    )


def verify(template: Template, extraction: Extraction | Problem, cal: Calibration, settings: EngineSettings = DEFAULT) -> Decision:
    """One new photo against a locked palm. The photo is compared with every enrolment photo and the best match counts."""
    if isinstance(extraction, Problem):
        return invalid(extraction, cal)
    if template.engine_version != ENGINE_VERSION or template.config_hash != config_hash(settings):
        raise TemplateOutdated('the template was made by a different version of the palm lock')
    if extraction.side != template.side:
        return invalid(Problem('wrong_hand', f'This lock uses the {template.side} hand. Take the photo of the {template.side} palm.'), cal)
    best: tuple[float, dict[str, float], dict[str, float]] | None = None
    best_i = 0
    for i, sample in enumerate(template.samples):
        result = compare(extraction.features, sample, cal, settings)
        if best is None or result[0] > best[0]:
            best, best_i = result, i
    assert best is not None
    score, norm, raw = best
    ok = score >= cal.threshold
    reason = (
        f'The palm matched: score {score:.2f} reached the threshold {cal.threshold:.2f}.'
        if ok
        else f'The palm did not match: score {score:.2f} is below the threshold {cal.threshold:.2f}.'
    )
    return Decision(
        outcome='success' if ok else 'failed',
        score=round(score, 4),
        threshold=cal.threshold,
        methods={m: round(v, 4) for m, v in norm.items()},
        raw={m: round(v, 4) for m, v in raw.items()},
        best_sample=best_i,
        reason=reason,
        calibrated=cal.calibrated,
    )
