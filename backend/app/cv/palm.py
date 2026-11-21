"""The palm, straightened, and the map of where its creases are.

Starting point: a photo and the 21 landmarks of the hand in it (cv/hand.py). Everything here is classical image
processing (OpenCV and NumPy); no network is involved.

  1. SILHOUETTE. The landmarks seed GrabCut, which cuts the hand out of its background. The palm and the bones of the
     fingers are marked as hand, everything well outside the landmarks as background, and GrabCut decides the rest.
     The silhouette is used for the outline and to keep the crease search inside the hand.
  2. STRAIGHTENING. The photo is warped so that every palm has the same position, size and direction: the wrist at the
     bottom, the fingers up, the thumb to the right, and one unit equal to the wrist-to-knuckles distance (400 pixels).
     A left and a right palm then look alike, and every later step can use the same numbers (frame in cv/hand.py).
  3. RIDGE MAP. A crease is a thin dark valley. At three scales, the second derivatives of the picture (the Hessian)
     say how strongly each pixel sits in a valley and which way the valley runs. Before that, the green channel (where
     skin lines show best) is divided by its own local average, so a shadow or a bright patch does not hide a crease.

lines.py then walks along the valleys to find the principal lines.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.cv.hand import (
    INDEX_MCP,
    MIDDLE_MCP,
    PINKY_MCP,
    RING_MCP,
    THUMB_CMC,
    WRIST,
    Frame,
    hand_frame,
)

# ------------------------------------------------------------------ the straightened picture

#: pixels per unit (one unit is the wrist-to-knuckles distance)
S = 400.0
X_MIN, X_MAX = -0.80, 1.00
Y_MIN, Y_MAX = -0.20, 1.20
W_PX = round((X_MAX - X_MIN) * S)
H_PX = round((Y_MAX - Y_MIN) * S)

#: scales of the ridge filter, in pixels of the straightened picture (a crease is about 4 to 8 pixels wide there)
SIGMAS = (2.0, 3.0, 4.0)
#: width, in pixels of the straightened picture, of the round shape that shrinks the hand's silhouette before the crease
#: search: the search stays about half of it (14 pixels) inside the edge, where the outline of the skin would look like a crease
EDGE_ERODE = 29

FINGER_BONES = ([1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16], [17, 18, 19, 20])


def to_px(x: float, y: float) -> tuple[float, float]:
    """Palm coordinates to (column, row) of the straightened picture."""
    return (x - X_MIN) * S, (Y_MAX - y) * S


def to_xy(rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """(row, column) pixels of the straightened picture to palm coordinates, as an (n, 2) array of (x, y)."""
    return np.stack([X_MIN + np.asarray(cols, np.float64) / S, Y_MAX - np.asarray(rows, np.float64) / S], axis=-1)


def to_rc(xy: np.ndarray) -> np.ndarray:
    """Palm coordinates, as an (n, 2) array of (x, y), to (row, column) pixels of the straightened picture."""
    xy = np.asarray(xy, np.float64)
    return np.stack([(Y_MAX - xy[:, 1]) * S, (xy[:, 0] - X_MIN) * S], axis=-1)


def warp(img: np.ndarray, frame: Frame, nearest: bool = False) -> np.ndarray:
    """The photo (or a mask of it) seen in the palm's own coordinates, 720 x 560 pixels."""
    scale = S / frame.length  # how much the photo must grow or shrink for the palm to be S pixels long
    # A big hand is shrunk first: averaging over areas keeps fine creases from aliasing. A small hand is NOT enlarged
    # first, because enlarging a whole photo by a big factor can take gigabytes; the warp below does the enlarging.
    shrink = min(scale, 1.0)
    small = cv2.resize(img, None, fx=shrink, fy=shrink, interpolation=cv2.INTER_NEAREST if nearest else cv2.INTER_AREA) if shrink < 1.0 else img
    step = shrink / scale  # pixels of `small` that one pixel of the straightened picture covers (1 after shrinking, less when enlarging)
    origin = frame.wrist * shrink + S * step * (X_MIN * frame.v + Y_MAX * frame.u)
    m = np.array([[frame.v[0] * step, -frame.u[0] * step, origin[0]], [frame.v[1] * step, -frame.u[1] * step, origin[1]]])
    interpolation = cv2.INTER_NEAREST if nearest else cv2.INTER_CUBIC if step < 1.0 else cv2.INTER_LINEAR
    border = cv2.BORDER_CONSTANT if nearest else cv2.BORDER_REFLECT
    return cv2.warpAffine(small, m, (W_PX, H_PX), flags=interpolation | cv2.WARP_INVERSE_MAP, borderMode=border)


# ------------------------------------------------------------------ the silhouette


def hand_mask(bgr: np.ndarray, points: np.ndarray, work_side: int = 480) -> np.ndarray:
    """The hand's silhouette as a boolean array the size of `bgr`, cut out with GrabCut and seeded by the landmarks."""
    h, w = bgr.shape[:2]
    scale = min(1.0, work_side / max(h, w))
    small = cv2.resize(bgr, (max(8, round(w * scale)), max(8, round(h * scale))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    p = points * scale
    wrist = p[WRIST]
    length = float(np.linalg.norm(p[[INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]].mean(axis=0) - wrist))
    pi = np.round(p).astype(np.int32)

    hull_img = np.zeros((sh, sw), np.uint8)
    cv2.fillConvexPoly(hull_img, cv2.convexHull(pi), 255)
    far = cv2.dilate(hull_img, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(length * 0.5) | 1,) * 2))

    mask = np.full((sh, sw), cv2.GC_PR_BGD, np.uint8)
    mask[far == 0] = cv2.GC_BGD
    # probably hand: the palm, and thick tubes along the finger bones. The whole hull is not marked: it holds a lot of
    # background between the spread fingers.
    palm_poly = cv2.convexHull(pi[[WRIST, 1, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]])
    cv2.fillConvexPoly(mask, palm_poly, int(cv2.GC_PR_FGD))
    tube = max(3, int(length * 0.15))
    for bones in FINGER_BONES:
        cv2.polylines(mask, [pi[bones]], False, int(cv2.GC_PR_FGD), tube)
    # surely hand: the middle of the palm and a thin line along each finger
    palm = np.zeros((sh, sw), np.uint8)
    cv2.fillConvexPoly(palm, palm_poly, 255)
    palm = cv2.erode(palm, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(length * 0.12) | 1,) * 2))
    mask[palm > 0] = cv2.GC_FGD
    thin = max(2, int(length * 0.03))
    for bones in FINGER_BONES:
        cv2.polylines(mask, [pi[bones]], False, int(cv2.GC_FGD), thin)

    try:
        background, foreground = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        # GrabCut starts its colour model with k-means, which draws random numbers from OpenCV's own generator. That
        # generator carries on from where the last call left it, so without this line the same photo gave a slightly
        # different silhouette each time it was analysed. A fixed seed makes the same photo give the same answer.
        cv2.setRNGSeed(0)
        cv2.grabCut(small, mask, None, background, foreground, 4, cv2.GC_INIT_WITH_MASK)
        out = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    except cv2.error:
        out = hull_img.copy()  # GrabCut could not run (a degenerate picture): the landmarks' hull is the best guess
    out = cv2.morphologyEx(out, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR) > 127


# ------------------------------------------------------------------ the ridge map

_K_XX = np.array([[1, -2, 1]], np.float32)
_K_YY = _K_XX.T.copy()
_K_XY = 0.25 * np.array([[1, 0, -1], [0, 0, 0], [-1, 0, 1]], np.float32)


def valley(gray: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """How much each pixel sits in a dark valley at one scale (scale-normalised), and the direction ACROSS the valley."""
    g = cv2.GaussianBlur(gray, (0, 0), sigma)
    ixx = cv2.filter2D(g, -1, _K_XX, borderType=cv2.BORDER_REFLECT)
    iyy = cv2.filter2D(g, -1, _K_YY, borderType=cv2.BORDER_REFLECT)
    ixy = cv2.filter2D(g, -1, _K_XY, borderType=cv2.BORDER_REFLECT)
    mean = 0.5 * (ixx + iyy)
    root = np.sqrt((0.5 * (ixx - iyy)) ** 2 + ixy**2)
    strongest, weakest = mean + root, mean - root  # the two curvatures; a valley is high in one and flat in the other
    strength = np.maximum(strongest - np.abs(weakest), 0) * sigma**2
    across = 0.5 * np.arctan2(2 * ixy, ixx - iyy)
    return strength, across


def ridge_map(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Valley strength and across-direction of a picture, the best of three scales at every pixel."""
    green = bgr[..., 1].astype(np.float32)
    flat = cv2.GaussianBlur(green, (0, 0), 30)
    ratio = np.log((green + 8) / (flat + 8))  # brightness compared with the neighbourhood, in log units
    best = angle = None
    for sigma in SIGMAS:
        strength, across = valley(ratio, sigma)
        if best is None:
            best, angle = strength, across
        else:
            wins = strength > best
            best, angle = np.where(wins, strength, best), np.where(wins, across, angle)
    return best, angle


def smoothstep(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ everything about one palm, ready for tracing


@dataclass
class PalmView:
    frame: Frame
    #: the photo's landmarks in palm coordinates: (21, 2) of (x, y)
    anchors: np.ndarray
    #: the silhouette in photo pixels (the size of the picture given in)
    silhouette: np.ndarray
    #: the silhouette in the straightened picture
    mask: np.ndarray
    #: the straightened picture (BGR, 560 x 720)
    image: np.ndarray
    #: ridge strength relative to the strongest 2% of the palm, 0 to 1.5 (0 outside the hand)
    strength: np.ndarray
    #: the direction ACROSS the valley at each pixel, in radians
    angle: np.ndarray
    #: ridge strength where the valley runs sideways / up and down (0 where it runs the other way)
    gate_h: np.ndarray
    gate_v: np.ndarray
    #: the absolute ridge strength of that strongest 2%: how much crease contrast the photo really has
    contrast: float

    def knuckle_x(self) -> dict[str, float]:
        a = self.anchors
        return {'i': float(a[INDEX_MCP, 0]), 'm': float(a[MIDDLE_MCP, 0]), 'r': float(a[RING_MCP, 0]), 'p': float(a[PINKY_MCP, 0]), 't': float(a[THUMB_CMC, 0])}


class PalmNotUsable(Exception):
    """The landmarks do not describe a hand that can be straightened (too small, collapsed, or outside the picture)."""


#: a palm shorter than this, in photo pixels, has no creases to find. (The photo check already turns away palms under 120.)
MIN_PALM_PX = 60


def prepare_palm(bgr: np.ndarray, points: np.ndarray) -> PalmView:
    frame = hand_frame(points)
    if frame is None:
        raise PalmNotUsable('the landmarks do not give a hand')
    if frame.length < MIN_PALM_PX:
        raise PalmNotUsable('the hand is too small in the photo')
    silhouette = hand_mask(bgr, points)
    image = warp(bgr, frame)
    mask = warp(silhouette.astype(np.uint8) * 255, frame, nearest=True) > 127
    interior = cv2.erode(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (EDGE_ERODE, EDGE_ERODE))) > 0
    if int(interior.sum()) < 20_000:
        raise PalmNotUsable('too little of the hand is inside the picture')

    ridge, across = ridge_map(image)
    ridge = np.where(interior, ridge, 0.0)
    contrast = float(np.percentile(ridge[interior], 98))
    strength = np.clip(ridge / max(contrast, 1e-6), 0, 1.5).astype(np.float32)
    gate_h = smoothstep(np.abs(np.sin(across)), 0.55, 0.85).astype(np.float32)
    gate_v = smoothstep(np.abs(np.cos(across)), 0.55, 0.85).astype(np.float32)
    return PalmView(
        frame=frame,
        anchors=frame.to_canon(points),
        silhouette=silhouette,
        mask=mask,
        image=image,
        strength=strength,
        angle=across.astype(np.float32),
        gate_h=gate_h,
        gate_v=gate_v,
        contrast=contrast,
    )
