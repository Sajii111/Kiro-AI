"""THE SAMPLE LINE FINDER. Port of src/api/mock/generate.ts.

It does NOT look at the photo. From a seed (the reading id) and the photo quality it decides, repeatably, which lines
"were found" and where, drawing them from the same stylised hand the website uses for its built-in sample photos. On
those sample drawings the lines therefore land on the creases; on a real photo they cannot, so a reading made this way
is labelled a sample (`meta.mock = true`).

It is used for the website's built-in sample drawings (which are not real hands), for the tests, and when the hand
model is not installed. A real photo goes through cv/palm.py and cv/lines.py instead, which return the same
HandAnalysis shape.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.rand import rng
from app.cv.findings import (
    FINGERS_LONG_AT,
    PALM_SQUARE_AT,
    clamp01,
    js_round,
    observation_for,
    r3,
    shape_observation,
)
from app.cv.handmodel import LINES, OUTLINE, P2, hand_frame, sample_spline
from app.cv.versions import STAND_IN_DETECTOR, STAND_IN_PIPELINE
from app.llm.knowledge import FEATURE_NAMES, FEATURE_ORDER
from app.schemas import (
    FeatureResult,
    FeatureStatus,
    FeatureTraits,
    HandAnalysis,
    HandSide,
    NormBox,
    NormPoint,
    OtherCrease,
    PalmShape,
    PalmShapeTraits,
    PhotoQuality,
    PhotoSize,
)

PIPELINE_VERSION = STAND_IN_PIPELINE
DETECTOR_VERSION = STAND_IN_DETECTOR

Rand = Callable[[], float]

# ------------------------------------------------------------------ choosing what "was found"

STATUS_WEIGHTS: dict[str, tuple[float, float, float]] = {
    'heart': (0.82, 0.14, 0.04),
    'head': (0.78, 0.17, 0.05),
    'life': (0.88, 0.10, 0.02),
    'fate': (0.30, 0.30, 0.40),
    'sun': (0.24, 0.30, 0.46),
}

CURVE_WEIGHTS: dict[str, list[tuple[str, float]]] = {
    'heart': [('gentle', 0.5), ('pronounced', 0.3), ('straight', 0.2)],
    'head': [('gentle', 0.45), ('straight', 0.35), ('pronounced', 0.2)],
    'life': [('gentle', 0.45), ('pronounced', 0.4), ('straight', 0.15)],
    'fate': [('straight', 0.6), ('gentle', 0.3), ('pronounced', 0.1)],
    'sun': [('straight', 0.7), ('gentle', 0.25), ('pronounced', 0.05)],
}


def pick(rand: Rand, options: list[tuple[str, float]]) -> str:
    r = rand() * sum(w for _, w in options)
    for value, w in options:
        r -= w
        if r <= 0:
            return value
    return options[-1][0]


Plan = dict[str, dict[str, FeatureStatus]]


def plan_statuses(seed: int, quality: dict[str, PhotoQuality]) -> Plan:
    """Decides, from a seed and the photo quality, how each line comes out. Worse photos find less.
    For demonstration, every reading shows at least one uncertain and one not-visible line, so the honest handling of
    unclear features is always on screen."""
    rand = rng(seed)
    plan: Plan = {'left': {}, 'right': {}}
    for side in ('left', 'right'):
        penalty = min(0.7, max(0.0, (0.85 - quality[side].score) * 1.2))
        for fid in FEATURE_ORDER:
            d0, u0, n0 = STATUS_WEIGHTS[fid]
            moved = d0 * penalty
            d = d0 - moved
            u = u0 + moved * 0.65
            n = n0 + moved * 0.35
            plan[side][fid] = pick(rand, [('detected', d), ('uncertain', u), ('not_visible', n)])  # type: ignore[assignment]
            if fid in ('heart', 'life') and quality[side].score >= 0.6:
                plan[side][fid] = 'detected'
    every = list(plan['left'].values()) + list(plan['right'].values())
    if 'uncertain' not in every:
        plan['left']['head'] = 'uncertain'
    if 'not_visible' not in every:
        plan['right']['sun'] = 'not_visible'
    return plan


# ------------------------------------------------------------------ one hand

KEEP = {'short': 0.66, 'medium': 0.86, 'long': 1.0}


def normaliser(side: HandSide, photo: PhotoSize) -> Callable[[P2], NormPoint]:
    """Hand space to the 0-1 picture space of a w x h photo. A left hand is the right one mirrored."""
    w, h = photo.width, photo.height
    to_px = hand_frame(w, h)

    def to_norm(p: P2) -> NormPoint:
        px, py = to_px(p)
        nx = px / w
        return (r3(1 - nx if side == 'left' else nx), r3(py / h))

    return to_norm


def build_feature(fid: str, side: HandSide, status: FeatureStatus, photo: PhotoSize, rand: Rand) -> FeatureResult:
    to_norm = normaliser(side, photo)

    # every hand is a little different: nudge the control points
    shift = ((rand() - 0.5) * 0.04, (rand() - 0.5) * 0.04)
    wobble = 0.045 if status == 'uncertain' else 0.025
    pts: list[P2] = [(x + shift[0] + (rand() - 0.5) * wobble, y + shift[1] + (rand() - 0.5) * wobble) for x, y in LINES[fid]]

    # the zone searched: the usual place of the line, with some room around it
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = 0.07
    c0 = to_norm((min(xs) - pad, max(ys) + pad))
    c1 = to_norm((max(xs) + pad, min(ys) - pad))
    x0, x1 = clamp01(min(c0[0], c1[0])), clamp01(max(c0[0], c1[0]))
    y0, y1 = clamp01(min(c0[1], c1[1])), clamp01(max(c0[1], c1[1]))
    search_area = NormBox(x=r3(x0), y=r3(y0), w=r3(x1 - x0), h=r3(y1 - y0))

    method = DETECTOR_VERSION
    name = FEATURE_NAMES[fid]

    if status == 'not_visible':
        return FeatureResult(
            id=fid, name=name, status=status, path=[], searchArea=search_area, confidence=None,
            observation=observation_for(fid, status, FeatureTraits()), traits=FeatureTraits(), method=method,
        )  # type: ignore[arg-type]

    detected = status == 'detected'
    length = pick(rand, [('short', 0.25), ('medium', 0.45), ('long', 0.3)])
    if detected:
        traits = FeatureTraits(length=length, curve=pick(rand, CURVE_WEIGHTS[fid]), clarity=pick(rand, [('clear', 0.6), ('deep', 0.4)]))  # type: ignore[arg-type]
    else:
        traits = FeatureTraits(clarity='faint')

    samples = sample_spline(pts, 6)
    keep = KEEP[length] if detected else 0.82
    count = min(len(samples), max(12, js_round(len(samples) * keep)))
    path = [to_norm(p) for p in samples[:count]]

    return FeatureResult(
        id=fid, name=name, status=status, path=path, searchArea=search_area,
        confidence=r3(0.78 + rand() * 0.17 if detected else 0.4 + rand() * 0.22),
        observation=observation_for(fid, status, traits), traits=traits, method=method,
    )  # type: ignore[arg-type]


# ------------------------------------------------------------------ hand shape and other creases

def build_palm_shape(quality: PhotoQuality, seed: int, rand: Rand) -> PalmShape:
    method = DETECTOR_VERSION
    if not quality.palmVisible:
        return PalmShape(
            status='not_visible', traits=PalmShapeTraits(), palmRatio=None, fingerRatio=None, confidence=None,
            observation='The hand could not be measured in this photo, so nothing is said about its shape.', method=method,
        )
    # both photos show the same person, so both hands share one base shape; only a small difference comes from each photo
    base = rng(seed + 7)
    square = base() < 0.5
    long_fingers = base() < 0.5
    jitter = (base(), base())
    palm_ratio = r3((0.92 + jitter[0] * 0.1 if square else 0.74 + jitter[0] * 0.1) + (rand() - 0.5) * 0.04)
    finger_ratio = r3((0.95 + jitter[1] * 0.13 if long_fingers else 0.76 + jitter[1] * 0.1) + (rand() - 0.5) * 0.04)
    if quality.score < 0.6:
        return PalmShape(
            status='uncertain', traits=PalmShapeTraits(), palmRatio=None, fingerRatio=None, confidence=r3(0.4 + rand() * 0.2),
            observation='Parts of the hand are soft or cut off in this photo, so its shape can only be guessed.', method=method,
        )
    traits = PalmShapeTraits(palm='square' if palm_ratio >= PALM_SQUARE_AT else 'long', fingers='long' if finger_ratio >= FINGERS_LONG_AT else 'short')
    return PalmShape(
        status='detected', traits=traits, palmRatio=palm_ratio, fingerRatio=finger_ratio, confidence=r3(0.72 + rand() * 0.18),
        observation=shape_observation(traits, palm_ratio, finger_ratio),
        method=method,
    )


CREASE_CANDIDATES: list[tuple[list[P2], str]] = [
    ([(-0.47, 0.62), (-0.4, 0.5), (-0.33, 0.38), (-0.26, 0.26)], 'on the outer edge of the palm, running down towards the wrist'),
    ([(-0.2, 0.7), (-0.1, 0.76), (0.0, 0.8)], 'between the heart line and the head line, below the ring finger'),
    ([(-0.3, 0.2), (-0.15, 0.14), (0.0, 0.12), (0.12, 0.16)], 'across the lower palm, above the wrist'),
]


def build_other_creases(side: HandSide, photo: PhotoSize, quality: PhotoQuality, rand: Rand) -> list[OtherCrease]:
    """Strong creases left over once the five lines are named. Worse photos find fewer."""
    to_norm = normaliser(side, photo)
    out: list[OtherCrease] = []
    for pts0, where in CREASE_CANDIDATES:
        if rand() > 0.6 * min(1.0, quality.score + 0.1):
            continue
        pts: list[P2] = [(x + (rand() - 0.5) * 0.03, y + (rand() - 0.5) * 0.03) for x, y in pts0]
        out.append(
            OtherCrease(
                id=f'c{len(out) + 1}',
                path=[to_norm(p) for p in sample_spline(pts, 5)],
                confidence=r3(0.42 + rand() * 0.24),
                observation=f'A short, faint crease {where}. It does not match any of the five main lines, so it is shown but not named.',
            )
        )
    return out


def build_analysis(side: HandSide, plan: dict[str, FeatureStatus], photo: PhotoSize, quality: PhotoQuality, seed: int) -> HandAnalysis:
    rand = rng(seed + (17 if side == 'left' else 101))
    features = [build_feature(fid, side, plan[fid], photo, rand) for fid in FEATURE_ORDER]
    return HandAnalysis(
        side=side,
        photo=photo,
        quality=quality,
        outline=[normaliser(side, photo)(p) for p in sample_spline(OUTLINE, 5)],
        features=features,
        palmShape=build_palm_shape(quality, seed, rand),
        otherCreases=build_other_creases(side, photo, quality, rand),
        methodVersion=DETECTOR_VERSION,
    )
