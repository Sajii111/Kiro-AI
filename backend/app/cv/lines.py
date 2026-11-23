"""Finding the five principal lines of a palm, the shape of the hand and other creases.

The input is the straightened palm and its ridge map (cv/palm.py). The output is the same HandAnalysis the stand-in
returns, so nothing downstream knows which of the two made it.

HOW A LINE IS FOUND. Each of the five lines has a usual home on the palm, written as zones relative to the knuckles
(for example: the heart line starts on the little-finger side, between the knuckle line and the middle of the palm, and
runs toward the index finger). Inside its zone the tracer looks for the path that follows the most crease: dynamic
programming (the Viterbi algorithm) over the ridge map, moving one pixel at a time along the line's main direction and
at most one pixel sideways, paid by ridge strength and charged a small price for every pixel walked and for wiggling.
Lines are traced one at a time, strongest first (life, head, heart, fate, sun), and the pixels of a line that was found are
closed to the ones after it, so two lines cannot take the same crease.

HOW IT IS JUDGED. The traced path is measured (its length, how strong and how continuous the crease is along it) and
given one of three honest answers: detected, uncertain (something line-like is there but it is faint or broken) or not
visible. Only a detected line gets a length, a curve and a clarity; those words come from fixed rules written below, so
the same photo always gives the same answer.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.cv.findings import (
    PALM_SQUARE_AT,
    REAL_FINGERS_LONG_AT,
    clamp01,
    observation_for,
    r3,
    shape_observation,
)
from app.cv.hand import (
    INDEX_MCP,
    MIDDLE_FINGER,
    MIDDLE_MCP,
    PINKY_MCP,
    RING_MCP,
    FoundHand,
    chain_length,
)
from app.cv.palm import (
    H_PX,
    W_PX,
    X_MIN,
    PalmNotUsable,
    PalmView,
    S,
    prepare_palm,
    to_px,
    to_rc,
    to_xy,
)
from app.cv.versions import REAL_DETECTOR
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

log = logging.getLogger('kiro.lines')

Poly = list[tuple[float, float]]
NEG = -1e9

# ------------------------------------------------------------------ the tracer


def _trace_left_to_right(profit: np.ndarray, start: np.ndarray, m: int, lam: float) -> tuple[np.ndarray, np.ndarray]:
    """Best path from the left edge to the right: the total of `profit` along one pixel per column, starting anywhere in
    `start` (a boolean array) and ending anywhere. A step may move up to `m` rows and costs `lam` per row moved.
    Returns the best total ending at every pixel, and for every pixel how it was reached (127 means: it is a start)."""
    h, w = profit.shape
    best = np.full((h, w), NEG, np.float64)
    came = np.zeros((h, w), np.int8)
    rows = np.arange(h)
    prev = np.full(h, NEG)
    steps = range(-m, m + 1)
    for x in range(w):
        options = np.full((2 * m + 1, h), NEG)
        for k, d in enumerate(steps):  # arrived from row y - d
            if d >= 0:
                options[k, d:] = prev[: h - d] - lam * abs(d)
            else:
                options[k, : h + d] = prev[-d:] - lam * abs(d)
        pick = options.argmax(axis=0)
        carried = options[pick, rows]
        fresh = np.where(start[:, x], 0.0, NEG)
        use_start = fresh >= carried
        base = np.where(use_start, fresh, carried)
        here = np.where(base > NEG / 2, base + profit[:, x], NEG)
        best[:, x] = here
        came[:, x] = np.where(use_start, 127, pick - m)
        prev = here
    return best, came


def _backtrack(best: np.ndarray, came: np.ndarray) -> tuple[float, list[tuple[int, int]]] | None:
    r, c = np.unravel_index(np.argmax(best), best.shape)
    total = float(best[r, c])
    if total <= NEG / 2:
        return None
    path = [(int(r), int(c))]
    while came[r, c] != 127:
        r = r - int(came[r, c])
        c -= 1
        path.append((int(r), int(c)))
    path.reverse()
    return total, path


def trace(profit: np.ndarray, start: np.ndarray, direction: str, m: int = 1, lam: float = 0.12) -> tuple[float, np.ndarray] | None:
    """The best path through `profit` that begins in `start` and heads in `direction`: 'x+' (left to right), 'x-' (right to
    left), 'y-' (top to bottom) or 'y+' (bottom to top). Returns the total and the path as (row, column) pixels."""
    p, s = profit, start
    if direction == 'x-':
        p, s = p[:, ::-1], s[:, ::-1]
    elif direction == 'y-':
        p, s = p.T, s.T
    elif direction == 'y+':
        p, s = p[::-1].T, s[::-1].T
    got = _backtrack(*_trace_left_to_right(np.ascontiguousarray(p), np.ascontiguousarray(s), m, lam))
    if got is None:
        return None
    total, path = got
    h, w = profit.shape
    out = np.empty((len(path), 2), np.int32)
    for i, (r, c) in enumerate(path):
        if direction == 'x+':
            out[i] = (r, c)
        elif direction == 'x-':
            out[i] = (r, w - 1 - c)
        elif direction == 'y-':
            out[i] = (c, r)
        else:
            out[i] = (h - 1 - c, r)
    return total, out


# ------------------------------------------------------------------ where each line usually lives


def lerp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


@dataclass(frozen=True)
class Zone:
    start: Poly  # where the line may begin
    corridor: Poly  # the only place it may run
    direction: str
    gate: str  # 'h': the crease must run sideways; 'v': it must run up and down


#: the up-and-down lines stay this far on the palm side of the thumb's base (palm units)
THUMB_MARGIN = 0.02


def thumb_edge(k: dict[str, float]) -> float:
    """How far toward the thumb the life, fate and sun lines may run: the base of the thumb or the index knuckle, whichever
    is further out, less a small margin. Beyond it lies the fold where the thumb meets the palm: a deep, straight crease
    that the tracer otherwise took for the life line (it did on two of the six hands tested on 21 November 2026)."""
    return max(k.get('t', k['i']), k['i']) - THUMB_MARGIN


def keep_off_thumb(poly: Poly, edge: float) -> Poly:
    return [(min(x, edge), y) for x, y in poly]


def zones(k: dict[str, float]) -> dict[str, Zone]:
    """The zones, in palm coordinates, from the x of the four knuckles (i index, m middle, r ring, p little finger) and of
    the base of the thumb (t)."""
    xi, xm, xr, xp = k['i'], k['m'], k['r'], k['p']
    left, right = xp - 0.20, xi + 0.15
    edge = thumb_edge(k)

    def head_top(x: float) -> float:  # the head line slopes down toward the little-finger side
        return lerp(x, left, right, 0.65, 1.00)

    return {
        'life': Zone(
            start=keep_off_thumb([(xi - 0.10, 0.70), (xi + 0.30, 0.70), (xi + 0.30, 1.05), (xi - 0.10, 1.05)], edge),
            corridor=keep_off_thumb([(-0.12, -0.12), (xi + 0.40, -0.12), (xi + 0.40, 1.08), (-0.12, 1.08)], edge),
            direction='y-',
            gate='v',
        ),
        'head': Zone(
            start=[(xi - 0.05, head_top(xi - 0.05) - 0.30), (right, head_top(right) - 0.30), (right, head_top(right)), (xi - 0.05, head_top(xi - 0.05))],
            corridor=[(right, head_top(right)), (left, head_top(left)), (left, head_top(left) - 0.48), (right, head_top(right) - 0.48)],
            direction='x-',
            gate='h',
        ),
        'heart': Zone(
            start=[(left, 0.55), (xp + 0.10, 0.55), (xp + 0.10, 0.98), (left, 0.98)],
            corridor=[(left, 1.12), (right, 1.12), (right, 0.96), (left, 0.60)],
            direction='x+',
            gate='h',
        ),
        'fate': Zone(
            start=keep_off_thumb([(xm - 0.30, -0.02), (xm + 0.30, -0.02), (xm + 0.30, 0.45), (xm - 0.30, 0.45)], edge),
            corridor=keep_off_thumb([(xm - 0.38, -0.12), (xm + 0.38, -0.12), (xm + 0.38, 1.00), (xm - 0.38, 1.00)], edge),
            direction='y+',
            gate='v',
        ),
        'sun': Zone(
            start=keep_off_thumb([(xr - 0.20, 0.22), (xr + 0.15, 0.22), (xr + 0.15, 0.60), (xr - 0.20, 0.60)], edge),
            corridor=keep_off_thumb([(xr - 0.25, 0.22), (xr + 0.20, 0.22), (xr + 0.20, 1.02), (xr - 0.25, 1.02)], edge),
            direction='y+',
            gate='v',
        ),
    }


#: the order the lines are traced in: strongest and most certain first
TRACE_ORDER = ('life', 'head', 'heart', 'fate', 'sun')

#: what a pixel must earn to be worth walking on (ridge strength times direction gate, minus this)
TAU = 0.30
#: pixels either side of a found line that later lines may not use
CLAIM_HALF_WIDTH = 8
#: how far the fate and sun lines stay from the life line, in palm units
LIFE_KEEP_OUT = 0.09


def polygon_mask(poly: Poly) -> np.ndarray:
    out = np.zeros((H_PX, W_PX), np.uint8)
    pts = np.round(np.array([to_px(x, y) for x, y in poly])).astype(np.int32)
    cv2.fillPoly(out, [pts], 255)
    return out > 0


def claim(path: np.ndarray, half_width: int, grace_at: np.ndarray | None = None, grace_px: float = 0) -> np.ndarray:
    """The pixels near a path. `grace_at` is a spot whose surroundings stay free (where the next line may start)."""
    out = np.zeros((H_PX, W_PX), np.uint8)
    cv2.polylines(out, [path[:, ::-1].astype(np.int32).reshape(-1, 1, 2)], False, 255, 2 * half_width + 1)
    if grace_at is not None:
        cv2.circle(out, (int(grace_at[1]), int(grace_at[0])), int(grace_px), 0, -1)
    return out > 0


@dataclass
class Traced:
    """One traced path, in palm coordinates, with how strong the crease is along it."""

    xy: np.ndarray  # (n, 2) smoothed
    strength: np.ndarray  # (n,) ridge strength along the raw path
    score: float

    @property
    def length(self) -> float:
        d = np.diff(self.xy, axis=0)
        return float(np.hypot(d[:, 0], d[:, 1]).sum())

    @property
    def mean(self) -> float:
        return float(self.strength.mean())

    @property
    def cover(self) -> float:
        """The share of the path that sits on a clear crease."""
        return float((self.strength > 0.35).mean())


def smooth(xy: np.ndarray, half: int = 12) -> np.ndarray:
    """A moving average that narrows at both ends, so the ends of the path stay where they are."""
    n = len(xy)
    if n < 5:
        return xy.astype(np.float64)
    c = np.vstack([np.zeros((1, 2)), np.cumsum(xy, axis=0)])
    out = np.empty((n, 2), np.float64)
    for i in range(n):
        h = min(half, i, n - 1 - i)
        out[i] = (c[i + h + 1] - c[i - h]) / (2 * h + 1)
    return out


def trace_all(view: PalmView) -> tuple[dict[str, Traced | None], dict[str, Zone]]:
    zs = zones(view.knuckle_x())
    taken = np.zeros((H_PX, W_PX), bool)
    life_path: np.ndarray | None = None
    found: dict[str, Traced | None] = {}
    for fid in TRACE_ORDER:
        zone = zs[fid]
        gate = view.gate_h if zone.gate == 'h' else view.gate_v
        profit = view.strength * gate - TAU
        profit[~polygon_mask(zone.corridor)] = -1.0
        profit[taken] = -TAU
        if fid in ('fate', 'sun') and life_path is not None:
            profit[claim(life_path, round(LIFE_KEEP_OUT * S))] = -TAU
        got = trace(profit, polygon_mask(zone.start), zone.direction)
        if got is None:
            found[fid] = None
            continue
        score, path = got
        strength = view.strength[path[:, 0], path[:, 1]]
        found[fid] = Traced(xy=smooth(to_xy(path[:, 0], path[:, 1])), strength=strength, score=score)
        taken |= claim(path, CLAIM_HALF_WIDTH, grace_at=path[0], grace_px=0.14 * S)
        if fid == 'life':
            life_path = path
    return found, zs


# ------------------------------------------------------------------ judging a traced line


@dataclass(frozen=True)
class Spec:
    #: shortest path, in palm units, that can count as detected
    detected_length: float
    #: shortest path that is worth mentioning as "uncertain"
    uncertain_length: float


SPECS = {
    'heart': Spec(0.40, 0.20),
    'head': Spec(0.35, 0.20),
    'life': Spec(0.40, 0.20),
    'fate': Spec(0.40, 0.20),
    'sun': Spec(0.25, 0.20),
}

#: below this the photo has too little crease contrast to say anything; between the two, nothing is called detected
CONTRAST_NONE = 0.018
CONTRAST_OK = 0.028
#: a detected line is on average this much stronger than the strongest 2% of the palm's ridge pixels
DETECTED_MEAN = 0.80
DETECTED_COVER = 0.80
UNCERTAIN_MEAN = 0.35
DEEP_MEAN = 1.12


def judge(fid: str, t: Traced | None, contrast: float) -> FeatureStatus:
    if t is None or contrast < CONTRAST_NONE:
        return 'not_visible'
    spec = SPECS[fid]
    if contrast >= CONTRAST_OK and t.length >= spec.detected_length and t.mean >= DETECTED_MEAN and t.cover >= DETECTED_COVER:
        return 'detected'
    if t.length >= spec.uncertain_length and t.mean >= UNCERTAIN_MEAN:
        return 'uncertain'
    return 'not_visible'


def sagitta(xy: np.ndarray) -> float:
    """How far a path bows away from the straight line between its ends, as a share of that straight line's length."""
    a, b = xy[0], xy[-1]
    chord = b - a
    n = float(np.hypot(*chord))
    if n < 1e-6:
        return 0.0
    dev = np.abs(chord[0] * (xy[:, 1] - a[1]) - chord[1] * (xy[:, 0] - a[0])) / n
    return float(dev.max() / n)


def ulnar_edge_x(view: PalmView, y: float) -> float:
    """The x of the little-finger edge of the hand at height y."""
    row = int(np.clip(round(to_px(0, y)[1]), 0, H_PX - 1))
    cols = np.flatnonzero(view.mask[row])
    return float(X_MIN + cols.min() / S) if len(cols) else float(X_MIN)


def traits_for(fid: str, t: Traced, view: PalmView) -> FeatureTraits:
    k = view.knuckle_x()
    xy = t.xy
    top, bottom = float(xy[:, 1].max()), float(xy[:, 1].min())

    if fid == 'heart':  # where it ends: under the index, middle or ring finger
        end_x = float(xy[-1, 0])
        length = 'long' if end_x >= (k['i'] + k['m']) / 2 else 'medium' if end_x >= (k['m'] + k['r']) / 2 else 'short'
    elif fid == 'head':  # how close it gets to the outer edge of the palm
        gap = float(xy[-1, 0]) - ulnar_edge_x(view, float(xy[-1, 1]))
        length = 'long' if gap <= 0.15 else 'medium' if gap <= 0.33 else 'short'
    elif fid == 'life':  # how far down toward the wrist it runs
        end_y = bottom
        length = 'long' if end_y <= 0.20 else 'medium' if end_y <= 0.40 else 'short'
    elif fid == 'fate':
        span = top - bottom
        length = 'long' if span >= 0.65 else 'medium' if span >= 0.35 else 'short'
    else:
        span = top - bottom
        length = 'long' if span >= 0.40 else 'medium' if span >= 0.22 else 'short'

    if fid == 'head':  # a head line is judged by how steeply it slopes
        run = abs(float(xy[-1, 0] - xy[0, 0]))
        rise = abs(float(xy[-1, 1] - xy[0, 1]))
        slope = math.degrees(math.atan2(rise, max(run, 1e-6)))
        curve = 'straight' if slope < 10 else 'gentle' if slope < 28 else 'pronounced'
    else:
        bow = sagitta(xy)
        straight_below, gentle_below = {'heart': (0.05, 0.13), 'life': (0.06, 0.20)}.get(fid, (0.05, 0.12))
        curve = 'straight' if bow < straight_below else 'gentle' if bow < gentle_below else 'pronounced'

    clarity = 'deep' if t.mean >= DEEP_MEAN else 'clear'
    return FeatureTraits(length=length, curve=curve, clarity=clarity)  # type: ignore[arg-type]


def confidence_for(status: FeatureStatus, t: Traced, fid: str, quality: PhotoQuality) -> float | None:
    if status == 'not_visible':
        return None
    spec = SPECS[fid]
    base = 0.5 * min(1.0, t.mean / 1.2) + 0.3 * t.cover + 0.2 * min(1.0, t.length / (spec.detected_length * 1.6))
    value = 0.25 + 0.7 * base
    if status == 'uncertain':
        value = min(value, 0.6) * 0.8
    value *= 0.8 + 0.2 * quality.score
    return r3(min(0.95, max(0.15, value)))


# ------------------------------------------------------------------ from palm coordinates to the photo


def to_norm(view: PalmView, xy: np.ndarray, size: tuple[int, int]) -> list[NormPoint]:
    """Palm coordinates to 0-1 fractions of the photo's width and height."""
    w, h = size
    px = view.frame.to_photo(xy)
    return [(r3(clamp01(float(x) / w)), r3(clamp01(float(y) / h))) for x, y in px]


def resample(xy: np.ndarray, count: int) -> np.ndarray:
    """`count` points spread evenly along a path."""
    d = np.hypot(*np.diff(xy, axis=0).T)
    along = np.concatenate([[0.0], np.cumsum(d)])
    if along[-1] < 1e-9:
        return xy[:1]
    t = np.linspace(0, along[-1], count)
    return np.stack([np.interp(t, along, xy[:, 0]), np.interp(t, along, xy[:, 1])], axis=1)


def path_points(view: PalmView, xy: np.ndarray, size: tuple[int, int]) -> list[NormPoint]:
    length = float(np.hypot(*np.diff(xy, axis=0).T).sum())
    count = int(min(80, max(12, round(length / 0.02))))
    return to_norm(view, resample(xy, count), size)


def search_box(view: PalmView, corridor: Poly, size: tuple[int, int]) -> NormBox:
    pts = to_norm(view, np.array(corridor), size)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return NormBox(x=r3(x0), y=r3(y0), w=r3(x1 - x0), h=r3(y1 - y0))


def outline_points(view: PalmView, size: tuple[int, int]) -> list[NormPoint] | None:
    contours, _ = cv2.findContours(view.silhouette.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    biggest = max(contours, key=cv2.contourArea)
    simple = cv2.approxPolyDP(biggest, 0.0012 * cv2.arcLength(biggest, True), True).reshape(-1, 2)
    if len(simple) < 8:
        return None
    w, h = size
    return [(r3(clamp01(float(x) / w)), r3(clamp01(float(y) / h))) for x, y in simple]


# ------------------------------------------------------------------ other creases

#: ridge strength a pixel needs to belong to a crease that is not one of the five lines
OTHER_MIN_STRENGTH = 0.40
#: shortest such crease worth showing, in palm units
OTHER_MIN_LENGTH = 0.15
OTHER_MAX = 3


def longest_path(skeleton: np.ndarray) -> np.ndarray | None:
    """The longest walk along a thin one-pixel-wide shape (a skeleton): found by walking from any pixel to the farthest
    one, then from there to the farthest again. Returns (row, column) pixels, or None for an empty shape."""
    coords = np.argwhere(skeleton)
    if len(coords) < 2:
        return None
    index = {(int(r), int(c)): i for i, (r, c) in enumerate(coords)}
    near = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def farthest(src: int) -> tuple[int, list[int]]:
        parent = {src: -1}
        queue = [src]
        last = src
        for node in queue:
            last = node
            r, c = coords[node]
            for dr, dc in near:
                j = index.get((int(r) + dr, int(c) + dc))
                if j is not None and j not in parent:
                    parent[j] = node
                    queue.append(j)
        chain = []
        node = last
        while node != -1:
            chain.append(node)
            node = parent[node]
        return last, chain

    a, _ = farthest(0)
    _, chain = farthest(a)
    return coords[chain]


def where_words(x: float, y: float, k: dict[str, float]) -> str:
    if y < 0.30:
        return 'across the lower palm, above the wrist'
    if x < k['p'] + 0.05:
        return 'on the outer edge of the palm'
    if x > k['i'] - 0.05 and y < 0.80:
        return 'on the thumb side of the palm'
    if y > 0.85:
        return 'near the base of the fingers'
    return 'in the middle of the palm'


def other_creases(view: PalmView, size: tuple[int, int], keep_clear: np.ndarray) -> list[OtherCrease]:
    """Strong creases left over once the five lines are named. They are shown thinly and never named."""
    if not hasattr(cv2, 'ximgproc'):
        return []
    k = view.knuckle_x()
    strength = view.strength.copy()
    palm = polygon_mask([(k['p'] - 0.15, 0.10), (k['i'] + 0.30, 0.10), (k['i'] + 0.30, 1.0), (k['p'] - 0.15, 1.0)])
    strength[~palm | keep_clear] = 0

    # keep only the crest of each valley (one pixel wide), so a crease becomes a thin line
    across = view.angle
    rows, cols = np.indices(strength.shape)
    dr, dc = np.rint(np.sin(across)).astype(int), np.rint(np.cos(across)).astype(int)
    ahead = strength[np.clip(rows + dr, 0, H_PX - 1), np.clip(cols + dc, 0, W_PX - 1)]
    behind = strength[np.clip(rows - dr, 0, H_PX - 1), np.clip(cols - dc, 0, W_PX - 1)]
    crest = (strength >= ahead) & (strength >= behind) & (strength > OTHER_MIN_STRENGTH)
    joined = cv2.dilate(crest.astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
    thin = cv2.ximgproc.thinning(joined) > 0
    count, labels = cv2.connectedComponents(thin.astype(np.uint8), connectivity=8)

    found: list[tuple[float, Traced]] = []
    for label in range(1, count):
        shape = labels == label
        if int(shape.sum()) < OTHER_MIN_LENGTH * S:
            continue
        path = longest_path(shape)
        if path is None:
            continue
        values = view.strength[path[:, 0], path[:, 1]]
        t = Traced(xy=smooth(to_xy(path[:, 0], path[:, 1])), strength=values, score=0.0)
        if t.length < OTHER_MIN_LENGTH:
            continue
        found.append((t.length * t.mean, t))
    found.sort(key=lambda f: f[0], reverse=True)

    out: list[OtherCrease] = []
    for _, t in found[:OTHER_MAX]:
        cx, cy = float(t.xy[:, 0].mean()), float(t.xy[:, 1].mean())
        out.append(
            OtherCrease(
                id=f'c{len(out) + 1}',
                path=path_points(view, t.xy, size),
                confidence=r3(min(0.62, max(0.30, 0.25 + 0.25 * min(1.2, t.mean)))),
                observation=(
                    f'A short, faint crease {where_words(cx, cy, k)}. '
                    'It does not match any of the five main lines, so it is shown but not named.'
                ),
            )
        )
    return out


# ------------------------------------------------------------------ the shape of the hand


def palm_width_ratio(view: PalmView, hand: FoundHand) -> float:
    """Palm width (across the knuckles, edge of the skin to edge of the skin) divided by the palm's length. Measured on
    the silhouette; when that looks wrong, estimated from the knuckle landmarks (the skin reaches about a third beyond
    the outer knuckle centres)."""
    k = view.knuckle_x()
    ys = view.anchors[[INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP], 1]
    fallback = 1.35 * float(np.linalg.norm(hand.points[INDEX_MCP] - hand.points[PINKY_MCP])) / view.frame.length
    row = int(np.clip(round(to_px(0, float(ys.mean()))[1]), 0, H_PX - 1))
    line = view.mask[row]
    centre = int(np.clip(round((float(np.mean(list(k.values()))) - X_MIN) * S), 0, W_PX - 1))
    if not line[centre]:
        return fallback
    a = b = centre
    while a > 0 and line[a - 1]:
        a -= 1
    while b < W_PX - 1 and line[b + 1]:
        b += 1
    measured = (b - a) / S
    return measured if 0.8 * fallback <= measured <= 1.25 * fallback else fallback


def build_palm_shape(view: PalmView, hand: FoundHand, quality: PhotoQuality, cut_off: bool) -> PalmShape:
    palm_ratio = palm_width_ratio(view, hand)
    finger_ratio = chain_length(hand.points, MIDDLE_FINGER) / view.frame.length
    flatness = float(np.linalg.norm(hand.points[INDEX_MCP] - hand.points[PINKY_MCP]) / view.frame.length)
    if flatness < 0.55 or finger_ratio < 0.75 or cut_off or quality.score < 0.5:
        return PalmShape(
            status='uncertain',
            traits=PalmShapeTraits(),
            palmRatio=None,
            fingerRatio=None,
            confidence=r3(0.35 + 0.15 * quality.score),
            observation='The hand is turned, curled or cut off by the edge of the photo, or the photo is poor, so its shape can only be guessed.',
            method=REAL_DETECTOR,
        )
    traits = PalmShapeTraits(palm='square' if palm_ratio >= PALM_SQUARE_AT else 'long', fingers='long' if finger_ratio >= REAL_FINGERS_LONG_AT else 'short')
    return PalmShape(
        status='detected',
        traits=traits,
        palmRatio=r3(palm_ratio),
        fingerRatio=r3(finger_ratio),
        confidence=r3(min(0.9, 0.55 + 0.3 * quality.score)),
        observation=shape_observation(traits, palm_ratio, finger_ratio),
        method=REAL_DETECTOR,
    )


# ------------------------------------------------------------------ one hand, start to finish


@dataclass
class Analysis:
    """The result for one hand, with the working that produced it (the contact-sheet script draws from this)."""

    result: HandAnalysis
    view: PalmView | None = None
    traces: dict[str, Traced | None] = field(default_factory=dict)
    zones: dict[str, Zone] = field(default_factory=dict)
    others: list[OtherCrease] = field(default_factory=list)


def nothing_found(side: HandSide, size: PhotoSize, quality: PhotoQuality, why: str) -> Analysis:
    """What to say when the hand could not be straightened at all: every finding is "not visible"."""
    features = [
        FeatureResult(
            id=fid,  # type: ignore[arg-type]
            name=FEATURE_NAMES[fid],
            status='not_visible',
            path=[],
            searchArea=NormBox(x=0.0, y=0.0, w=1.0, h=1.0),
            confidence=None,
            observation=observation_for(fid, 'not_visible', FeatureTraits()),
            traits=FeatureTraits(),
            method=REAL_DETECTOR,
        )
        for fid in FEATURE_ORDER
    ]
    shape = PalmShape(
        status='not_visible',
        traits=PalmShapeTraits(),
        palmRatio=None,
        fingerRatio=None,
        confidence=None,
        observation=f'The hand could not be measured in this photo ({why}), so nothing is said about its shape.',
        method=REAL_DETECTOR,
    )
    return Analysis(result=HandAnalysis(side=side, photo=size, quality=quality, outline=None, features=features, palmShape=shape, otherCreases=[], methodVersion=REAL_DETECTOR))


def analyse(
    side: HandSide,
    bgr: np.ndarray,
    hand: FoundHand,
    photo: PhotoSize,
    quality: PhotoQuality,
    cut_off: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> Analysis:
    """Everything about one palm: the five lines, the shape of the hand, other creases and the outline.

    `bgr` is the picture the landmarks were found in (the same size, so the landmarks are in its pixels). Positions in
    the result are fractions of the picture, so they hold for the photo as uploaded."""
    size = (bgr.shape[1], bgr.shape[0])
    try:
        view = prepare_palm(bgr, hand.points)
    except PalmNotUsable as exc:
        return nothing_found(side, photo, quality, str(exc))

    traces, zs = trace_all(view)
    if cancelled and cancelled():
        return nothing_found(side, photo, quality, 'cancelled')

    features: list[FeatureResult] = []
    accepted = np.zeros((H_PX, W_PX), bool)
    for fid in FEATURE_ORDER:
        t = traces.get(fid)
        status = judge(fid, t, view.contrast)
        traits = FeatureTraits()
        path: list[NormPoint] = []
        if t is not None and status != 'not_visible':
            path = path_points(view, t.xy, size)
            accepted |= claim(np.round(to_rc(t.xy)).astype(np.int32), 16)
            traits = traits_for(fid, t, view) if status == 'detected' else FeatureTraits(clarity='faint')
        features.append(
            FeatureResult(
                id=fid,  # type: ignore[arg-type]
                name=FEATURE_NAMES[fid],
                status=status,
                path=path,
                searchArea=search_box(view, zs[fid].corridor, size),
                confidence=confidence_for(status, t, fid, quality) if t is not None else None,
                observation=observation_for(fid, status, traits),
                traits=traits,
                method=REAL_DETECTOR,
            )
        )

    try:
        others = other_creases(view, size, accepted)
    except (cv2.error, ValueError, IndexError) as exc:  # a bonus feature: never let it spoil the reading
        log.warning('other creases skipped: %s', exc)
        others = []

    result = HandAnalysis(
        side=side,
        photo=photo,
        quality=quality,
        outline=outline_points(view, size),
        features=features,
        palmShape=build_palm_shape(view, hand, quality, cut_off),
        otherCreases=others,
        methodVersion=REAL_DETECTOR,
    )
    return Analysis(result=result, view=view, traces=traces, zones=zs, others=others)
