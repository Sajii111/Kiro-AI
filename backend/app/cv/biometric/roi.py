"""Step 1: the region of interest. A square from the middle of the palm, the same part of the palm in every photo.

The square is placed from the four knuckles only (index, middle, ring and little finger). They sit on the rigid part of
the hand, so they stay put against the skin of the palm whatever the wrist does. The wrist point is left out on purpose:
it is the least steady landmark (it moves with the wrist's bend and with how much forearm shows), and a frame built on it
turns and slides the square over the palm from one photo to the next.

The knuckle line (a straight line through the four knuckles) gives the square its direction. The square's middle sits a
fixed share of the knuckle span below the middle of that line, toward the wrist, and its side is a fixed share of the span.
So a photo taken closer, further, or with the hand turned gives the same square.

The square is cut straight out of the photo with one affine warp (rotation and scale in one go), with the fingers up and
the thumb to the right. A left palm therefore comes out as the mirror image of a right one; that is fine, because a lock
only ever compares a palm with the same hand.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.cv.hand import INDEX_MCP, MIDDLE_MCP, PINKY_MCP, RING_MCP, WRIST, hand_frame
from app.cv.palm import hand_mask

from .config import RoiSettings


@dataclass(frozen=True)
class RoiProblem:
    code: str
    message: str


@dataclass
class Roi:
    #: the square, BGR, `size` x `size`, fingers up
    image: np.ndarray
    #: the share of the square that lies on the hand
    inside: float
    #: the square's corners in the source picture (top-left, top-right, bottom-right, bottom-left), for drawing
    corners: np.ndarray
    #: the square's side, in pixels of the source picture
    side_px: float


@dataclass(frozen=True)
class KnuckleFrame:
    """The palm's frame from its knuckle line."""

    #: the middle of the four knuckles, photo pixels
    origin: np.ndarray
    #: unit vector, photo pixels: perpendicular to the knuckle line, from the palm toward the fingers
    u: np.ndarray
    #: unit vector, photo pixels: along the knuckle line, toward the index finger
    v: np.ndarray
    #: the distance from the index-finger knuckle to the little-finger knuckle, photo pixels
    span: float


def knuckle_frame(points: np.ndarray) -> KnuckleFrame | None:
    """The frame from the four knuckles (the wrist only says which way is the palm, not where the square goes).
    None when the knuckles are too bunched up to define a line."""
    if not np.all(np.isfinite(points)):
        return None
    knuckles = np.asarray(points[[INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]], np.float64)
    origin = knuckles.mean(axis=0)
    across = knuckles[0] - knuckles[3]  # little finger to index finger
    span = float(np.linalg.norm(across))
    if span < 8:
        return None
    # the knuckle line: the main direction of the four points (steadier than the two end knuckles alone)
    _, _, vt = np.linalg.svd(knuckles - origin, full_matrices=False)
    v = vt[0]
    if float(v @ across) < 0:
        v = -v
    u = np.array([-v[1], v[0]])
    if float(u @ (origin - np.asarray(points[WRIST], np.float64))) < 0:  # the fingers are on the side away from the wrist
        u = -u
    return KnuckleFrame(origin=origin, u=u, v=v, span=span)


def roi_matrix(points: np.ndarray, settings: RoiSettings) -> tuple[np.ndarray, float] | RoiProblem:
    """The 2 x 3 matrix that takes a pixel of the square (column, row) to a point of the photo, and the photo pixels one
    square pixel covers."""
    palm = hand_frame(points)
    frame = knuckle_frame(points)
    if palm is None or frame is None:
        return RoiProblem('no_hand', 'We could not find a hand in this photo. Hold the whole palm flat to the camera, then take it again.')
    if palm.length < settings.min_palm_px:
        return RoiProblem('too_small', 'The palm is too small in this photo. Move closer so the palm fills most of the frame, then take it again.')
    n = settings.size
    side = settings.side_scale * frame.span  # photo pixels
    centre = frame.origin - settings.center_below * frame.span * frame.u
    step = side / n  # photo pixels per square pixel
    half = (n - 1) / 2
    v, u = frame.v, frame.u
    # photo = centre + step * ((col - half) * v - (row - half) * u): columns run toward the thumb, rows toward the wrist
    m = np.array(
        [
            [step * v[0], -step * u[0], centre[0] - step * half * (v[0] - u[0])],
            [step * v[1], -step * u[1], centre[1] - step * half * (v[1] - u[1])],
        ]
    )
    return m, step


#: the two corners of the palm's base, in palm units: the heel of the hand on the little-finger side and on the thumb side
PALM_BASE = np.array([[-0.50, 0.02], [0.48, 0.05]])


def with_palm_base(points: np.ndarray) -> np.ndarray:
    """The 21 landmarks plus the two corners of the palm's base.

    `hand_mask` marks everything far from the landmarks' outline as surely background. The landmarks run straight from
    the wrist to the little-finger knuckle, but a real palm bulges past that line near the wrist (the heel of the hand),
    so that part would be cut off, and with it a corner of the square. Two extra points at the palm's base widen the
    outline there. `hand_mask` reads the 21 landmarks by their numbers, so the extra points only change the outline.
    """
    frame = hand_frame(points)
    if frame is None:
        return points
    return np.vstack([points, frame.to_photo(PALM_BASE)])


def corners_of(m: np.ndarray, n: int) -> np.ndarray:
    grid = np.array([[0, 0, 1], [n - 1, 0, 1], [n - 1, n - 1, 1], [0, n - 1, 1]], np.float64)
    return grid @ m.T


def sample_mask(mask: np.ndarray, m: np.ndarray, n: int) -> np.ndarray:
    """The part of a boolean mask under the square, as 0 / 255; outside the mask's picture counts as off the hand."""
    flags = cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP
    return cv2.warpAffine(mask.astype(np.uint8) * 255, m, (n, n), flags=flags, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def crop_roi(bgr: np.ndarray, points: np.ndarray, settings: RoiSettings, silhouette: np.ndarray | None = None) -> Roi | RoiProblem:
    """Cuts the square out of `bgr`, whose hand has the 21 landmarks `points` (pixels of `bgr`)."""
    found = roi_matrix(points, settings)
    if isinstance(found, RoiProblem):
        return found
    m, step = found
    n = settings.size
    h, w = bgr.shape[:2]
    corners = corners_of(m, n)
    margin = step  # half a pixel of the square either side, rounded up
    if corners[:, 0].min() - margin < 0 or corners[:, 1].min() - margin < 0 or corners[:, 0].max() + margin > w - 1 or corners[:, 1].max() + margin > h - 1:
        return RoiProblem('palm_cut_off', 'The middle of the palm is cut off by the edge of the photo. Step back so the whole hand fits, then take it again.')

    # Only the part of the photo around the square is worked on. A big palm is shrunk first, averaging over areas, so
    # fine creases do not alias when the square is sampled; then the warp only turns it.
    pad = int(np.ceil(3 * step)) + 2
    x0, y0 = max(0, int(corners[:, 0].min()) - pad), max(0, int(corners[:, 1].min()) - pad)
    x1, y1 = min(w, int(np.ceil(corners[:, 0].max())) + pad + 1), min(h, int(np.ceil(corners[:, 1].max())) + pad + 1)
    piece = bgr[y0:y1, x0:x1]
    shrink = min(1.0, 1.0 / step)
    if shrink < 1.0:
        piece = cv2.resize(piece, None, fx=shrink, fy=shrink, interpolation=cv2.INTER_AREA)
    mp = m.copy()
    mp[:, 2] -= (x0, y0)
    mp *= shrink
    interpolation = cv2.INTER_LINEAR if shrink < 1.0 else cv2.INTER_CUBIC
    image = cv2.warpAffine(piece, mp, (n, n), flags=interpolation | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)

    if silhouette is None:
        # The silhouette is cut out of the hand's own box, not the whole photo, so the small working size still gives the
        # hand plenty of pixels (and it is quicker).
        lo, hi = points.min(axis=0), points.max(axis=0)
        grow = 0.35 * float((hi - lo).max())
        bx0, by0 = max(0, int(lo[0] - grow)), max(0, int(lo[1] - grow))
        bx1, by1 = min(w, int(np.ceil(hi[0] + grow)) + 1), min(h, int(np.ceil(hi[1] + grow)) + 1)
        box = hand_mask(bgr[by0:by1, bx0:bx1], with_palm_base(points) - (bx0, by0), work_side=settings.mask_side)
        mb = m.copy()
        mb[:, 2] -= (bx0, by0)
        on_hand = sample_mask(box, mb, n)
    else:
        on_hand = sample_mask(silhouette, m, n)
    inside = float((on_hand > 127).mean())
    if inside < settings.min_inside:
        return RoiProblem('off_hand', 'Part of the middle of the palm does not show. Hold the palm flat and open, against a plain background, then take it again.')
    return Roi(image=image, inside=inside, corners=corners, side_px=step * n)
