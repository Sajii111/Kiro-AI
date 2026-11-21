"""The hand the stand-in line finder works from.

THIS FILE IS PART OF THE STAND-IN. It is the same stylised hand the website draws for its built-in sample photos
(src/lib/handGeometry.ts), written out as numbers, so that on those sample photos the stand-in lines land exactly on
the creases. On a real photo they cannot: no detection happens here. Phase 2 replaces the stand-in with real line
detection, and this file goes away with it.

Space: x to the right, y up, the wrist crease near y = 0, the palm about 1 unit wide. It is a RIGHT hand with the palm
facing the viewer (thumb on the right). A left hand is the right one mirrored.
"""

from __future__ import annotations

import math

P2 = tuple[float, float]

# The outline of the hand: control points of a smooth curve, copied from the website.
OUTLINE: list[P2] = [
    (-0.335, -0.22), (-0.345, -0.08), (-0.38, 0.1), (-0.43, 0.32),
    (-0.475, 0.55), (-0.5, 0.78), (-0.516, 0.88), (-0.535, 0.985),
    (-0.56141, 1.08932), (-0.59095, 1.19288), (-0.60913, 1.29981), (-0.63203, 1.40547),
    (-0.6497, 1.5127), (-0.66048, 1.58602), (-0.66246, 1.64087), (-0.6385, 1.6883),
    (-0.59503, 1.71562), (-0.54368, 1.71549), (-0.49822, 1.68796), (-0.47084, 1.6404),
    (-0.45054, 1.56977), (-0.42035, 1.46601), (-0.3928, 1.36144), (-0.35794, 1.25888),
    (-0.33183, 1.15369), (-0.307, 1.054), (-0.3, 1.033), (-0.293, 1.054),
    (-0.31328, 1.20891), (-0.33048, 1.36234), (-0.33538, 1.5129), (-0.34618, 1.65956),
    (-0.35179, 1.80439), (-0.35574, 1.93048), (-0.34776, 1.98785), (-0.3142, 2.03271),
    (-0.26407, 2.05311), (-0.21079, 2.04358), (-0.16864, 2.00668), (-0.14892, 1.95237),
    (-0.13098, 1.82898), (-0.11082, 1.68994), (-0.09497, 1.55284), (-0.07231, 1.41973),
    (-0.06106, 1.28958), (-0.052, 1.169), (-0.045, 1.148), (-0.038, 1.169),
    (-0.04062, 1.317), (-0.04096, 1.46978), (-0.03027, 1.62306), (-0.02603, 1.77688),
    (-0.01745, 1.931), (-0.00868, 2.08116), (0.00508, 2.13462), (0.04175, 2.17354),
    (0.09149, 2.18746), (0.14098, 2.17267), (0.17696, 2.13313), (0.18979, 2.07942),
    (0.19593, 1.92894), (0.20182, 1.77407), (0.20336, 1.6189), (0.21135, 1.4632),
    (0.20832, 1.30699), (0.203, 1.154), (0.21, 1.133), (0.217, 1.154),
    (0.22893, 1.27413), (0.24157, 1.40102), (0.26513, 1.52807), (0.2804, 1.65747),
    (0.29919, 1.78732), (0.31296, 1.88473), (0.33581, 1.94291), (0.38241, 1.9816),
    (0.44026, 1.99039), (0.49387, 1.96692), (0.52886, 1.91749), (0.53586, 1.8553),
    (0.53465, 1.75579), (0.53102, 1.62231), (0.52121, 1.48874), (0.51699, 1.35317),
    (0.49919, 1.21779), (0.485, 1.08), (0.49, 0.98), (0.494, 0.88),
    (0.508, 0.8), (0.53, 0.75), (0.58562, 0.80236), (0.64034, 0.86451),
    (0.70589, 0.92316), (0.76759, 0.99141), (0.83325, 1.05989), (0.86571, 1.0938),
    (0.91707, 1.12336), (0.97661, 1.12336), (1.02818, 1.09358), (1.05796, 1.04201),
    (1.05796, 0.98247), (1.02797, 0.93068), (1.00141, 0.88931), (0.9435, 0.80559),
    (0.87845, 0.72481), (0.81407, 0.63762), (0.73568, 0.55711), (0.655, 0.47),
    (0.615, 0.37), (0.57, 0.26), (0.495, 0.1), (0.415, -0.05),
    (0.345, -0.22),
]

# The five principal lines: control points of a smooth curve each.
LINES: dict[str, list[P2]] = {
    'heart': [(-0.5, 0.82), (-0.4, 0.9), (-0.22, 0.95), (0, 0.96), (0.17, 0.99), (0.29, 1.04)],
    'head': [(0.46, 0.8), (0.32, 0.74), (0.14, 0.69), (-0.06, 0.64), (-0.24, 0.6), (-0.4, 0.55)],
    'life': [(0.44, 0.82), (0.36, 0.7), (0.27, 0.56), (0.21, 0.4), (0.18, 0.24), (0.2, 0.07), (0.27, -0.07)],
    'fate': [(0, -0.06), (-0.01, 0.14), (0, 0.36), (0.03, 0.58), (0.06, 0.76), (0.08, 0.9)],
    'sun': [(-0.1, 0.46), (-0.13, 0.6), (-0.16, 0.74), (-0.18, 0.88)],
}


def _seg(p0: P2, p1: P2, p2: P2, p3: P2, t: float) -> P2:
    """One piece of a centripetal Catmull-Rom curve (Barry-Goldman). Avoids loops and overshoot on uneven spacing."""

    def d(a: P2, b: P2) -> float:
        return max(1e-6, math.hypot(b[0] - a[0], b[1] - a[1]) ** 0.5)

    t0 = 0.0
    t1 = t0 + d(p0, p1)
    t2 = t1 + d(p1, p2)
    t3 = t2 + d(p2, p3)
    x = t1 + (t2 - t1) * t

    def mix(a: P2, b: P2, ta: float, tb: float) -> P2:
        k = (x - ta) / (tb - ta)
        return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)

    a1 = mix(p0, p1, t0, t1)
    a2 = mix(p1, p2, t1, t2)
    a3 = mix(p2, p3, t2, t3)
    b1 = mix(a1, a2, t0, t2)
    b2 = mix(a2, a3, t1, t3)
    return mix(b1, b2, t1, t2)


def sample_spline(pts: list[P2], per_segment: int = 10) -> list[P2]:
    """A smooth polyline through the control points (an open curve)."""
    if len(pts) < 3:
        return list(pts)
    first, last = pts[0], pts[-1]
    ext = [(2 * first[0] - pts[1][0], 2 * first[1] - pts[1][1]), *pts, (2 * last[0] - pts[-2][0], 2 * last[1] - pts[-2][1])]
    out: list[P2] = []
    for i in range(len(pts) - 1):
        for j in range(per_segment):
            out.append(_seg(ext[i], ext[i + 1], ext[i + 2], ext[i + 3], j / per_segment))
    out.append(last)
    return out


def _bounds(pts: list[P2], pad: float) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad


# the box around the hand, with a little air
MIN_X, MAX_X, MIN_Y, MAX_Y = _bounds(sample_spline(OUTLINE, 6), 0.04)


def hand_frame(w: float, h: float, fill: float = 0.9):
    """Where the hand sits inside a picture of w x h pixels. Returns a function from hand space to pixels."""
    s = min(w / (MAX_X - MIN_X), h / (MAX_Y - MIN_Y)) * fill
    ox = (w - (MAX_X - MIN_X) * s) / 2 - MIN_X * s
    oy = (h - (MAX_Y - MIN_Y) * s) / 2 + MAX_Y * s

    def to_px(p: P2) -> P2:
        return (ox + p[0] * s, oy - p[1] * s)

    return to_px
