"""Made-up photos of a whole hand, with the 21 landmarks and the creases at places we know, for testing the real analysis.

They are drawings: a skin-coloured hand (palm, forearm, five fingers) on a grey background, with the principal lines
drawn as soft dark valleys, a little random wrinkle texture, lighting that fades across the hand and sensor noise. No real
person is in them, so they can live in the repository.

Because the creases are drawn at known places, a test can check not only WHAT the analysis says but WHERE it put the
lines: the distance between each traced path and the line that was drawn. The hand's landmarks are known too, so a fake
hand finder can hand them over instead of running the hand model (which needs a downloaded file and a real photo).

Palm coordinates: x toward the thumb, y toward the fingers, one unit = the wrist-to-knuckles distance.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.cv.hand import FoundHand

# the 21 landmarks, MediaPipe's order: wrist; thumb 1-4; index 5-8; middle 9-12; ring 13-16; little finger 17-20
LANDMARKS = np.array(
    [
        (0.00, 0.00),
        (0.40, 0.18), (0.62, 0.42), (0.80, 0.62), (0.95, 0.80),
        (0.33, 1.00), (0.38, 1.40), (0.40, 1.65), (0.41, 1.85),
        (0.11, 1.05), (0.12, 1.50), (0.12, 1.78), (0.12, 2.00),
        (-0.11, 1.02), (-0.13, 1.45), (-0.14, 1.70), (-0.15, 1.90),
        (-0.33, 0.90), (-0.38, 1.20), (-0.40, 1.38), (-0.41, 1.52),
    ]
)  # fmt: skip

#: the creases that were drawn: the truth the tests compare against
CREASES: dict[str, list[tuple[float, float]]] = {
    'life': [(0.30, 0.95), (0.22, 0.70), (0.18, 0.45), (0.18, 0.22), (0.24, 0.05)],
    'head': [(0.30, 0.93), (0.12, 0.84), (-0.08, 0.76), (-0.25, 0.66)],
    'heart': [(-0.43, 0.80), (-0.25, 0.88), (-0.05, 0.96), (0.12, 1.01), (0.27, 1.03)],
    'fate': [(0.03, 0.02), (0.04, 0.30), (0.07, 0.60), (0.09, 0.88)],
}

SKIN_BGR = np.array([140, 172, 224], np.float32)
BACKGROUND_BGR = np.array([118, 120, 122], np.float32)


class Placed:
    """One hand in one picture: where its landmarks are, and a way to put palm coordinates on the picture."""

    def __init__(self, side: str, angle: float, scale: float, size: tuple[int, int], width: float = 1.0):
        self.width = width  # 1.0 is the drawn hand; less is a narrower hand (every x is multiplied by it)
        a = np.radians(angle)
        self.u = np.array([-np.sin(a), -np.cos(a)])  # wrist to knuckles (in a picture, y grows downward)
        v = np.array([np.cos(a), -np.sin(a)])  # toward the thumb: to the right for a right palm, to the left for a left palm
        self.v = v if side == 'right' else -v
        self.scale = scale
        self.side = side
        w, h = size
        # the middle of the palm sits in the middle of the picture, so a turned hand stays inside it
        centre = np.array([w / 2, h / 2])
        self.origin = centre - scale * (0.15 * width * self.v + 1.0 * self.u)
        self.size = size

    def px(self, points) -> np.ndarray:
        p = np.atleast_2d(np.asarray(points, np.float64))
        return self.origin + self.scale * (p[:, 0:1] * self.width * self.v + p[:, 1:2] * self.u)

    @property
    def landmarks(self) -> np.ndarray:
        return self.px(LANDMARKS)


def landmarks_for(finger_stretch: float = 1.0) -> np.ndarray:
    """The 21 landmarks in palm coordinates, with every finger drawn longer (above 1) or shorter (below 1)."""
    marks = LANDMARKS.copy()
    for first in (5, 9, 13, 17):
        base = marks[first].copy()
        marks[first + 1 : first + 4] = base + (marks[first + 1 : first + 4] - base) * finger_stretch
    return marks


def found(placed: Placed, label: str | None = None, score: float = 0.97, finger_stretch: float = 1.0) -> FoundHand:
    """What the hand model would answer for this picture: the landmarks, and whether it calls the hand left or right
    (by default, the side it was drawn as)."""
    return FoundHand(points=placed.px(landmarks_for(finger_stretch)), label=label or placed.side, score=score)  # type: ignore[arg-type]


class FakeFinder:
    """Stands in for the hand model in tests: answers with the hands it was given for a picture of a given size
    (width, height). A picture it was not told about has no hand in it."""

    def __init__(self, hands: dict[tuple[int, int], list[FoundHand]] | None = None):
        self.hands = hands or {}
        self.calls = 0
        self.closed = False

    def find(self, bgr: np.ndarray) -> list[FoundHand]:
        self.calls += 1
        h, w = bgr.shape[:2]
        return list(self.hands.get((w, h), []))

    def close(self) -> None:
        self.closed = True


def render(
    side: str = 'right',
    angle: float = 0.0,
    scale: float = 480.0,
    size: tuple[int, int] = (1300, 1300),
    creases: tuple[str, ...] = ('life', 'head', 'heart', 'fate'),
    depth: float = 38.0,
    seed: int = 1,
    finger_stretch: float = 1.0,
    wrinkles: int = 28,
    hand_width: float = 1.0,
) -> tuple[np.ndarray, Placed]:
    """A BGR picture of a hand (palm to the camera) and where everything in it is."""
    rng = np.random.default_rng(seed)
    width, height = size
    placed = Placed(side, angle, scale, size, hand_width)

    # fingers can be drawn longer or shorter (the landmarks of each finger move with them)
    placed_marks = placed.px(landmarks_for(finger_stretch))

    # the shape of the hand
    mask = np.zeros((height, width), np.uint8)
    palm = [(-0.44, -0.10), (0.42, -0.10), (0.50, 0.30), (0.46, 0.75), (0.47, 1.06), (-0.47, 1.02), (-0.46, 0.60)]
    forearm = [(-0.38, -0.10), (0.36, -0.10), (0.34, -0.45), (-0.36, -0.45)]
    for poly in (palm, forearm):
        cv2.fillPoly(mask, [np.round(placed.px(poly)).astype(np.int32)], 255, cv2.LINE_AA)
    chains = ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))
    for chain in chains:
        pts = np.round(placed_marks[list(chain)]).astype(np.int32)
        thick = int(scale * (0.23 if chain[0] == 1 else 0.17))
        cv2.polylines(mask, [pts], False, 255, thick, cv2.LINE_AA)
        for p in pts:
            cv2.circle(mask, tuple(int(x) for x in p), thick // 2, 255, -1, cv2.LINE_AA)
    # skin joining the thumb to the palm
    web = [(0.40, 0.10), (0.62, 0.30), (0.40, 0.70), (0.30, 0.45)]
    cv2.fillPoly(mask, [np.round(placed.px(web)).astype(np.int32)], 255, cv2.LINE_AA)

    # lighting: brighter toward one corner
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    light = 1.0 + 0.12 * ((xx / width) - 0.5) - 0.10 * ((yy / height) - 0.5)
    img = np.empty((height, width, 3), np.float32)
    img[:] = BACKGROUND_BGR
    img = np.where(mask[..., None] > 0, SKIN_BGR, img) * light[..., None]

    # the creases: soft dark valleys, a little darker in the green channel where skin lines show best
    layer = np.zeros((height, width), np.uint8)
    line_px = max(2, round(scale / 100))
    for name in creases:
        cv2.polylines(layer, [np.round(placed.px(CREASES[name])).astype(np.int32)], False, 255, line_px, cv2.LINE_AA)
    for _ in range(wrinkles):  # short random wrinkles that are not lines: the analysis must not mistake them for one
        c = np.array([rng.uniform(-0.3, 0.4), rng.uniform(0.1, 0.95)])
        t = rng.uniform(0, np.pi)
        half = rng.uniform(0.04, 0.12) * np.array([np.cos(t), np.sin(t)])
        cv2.line(layer, tuple(np.round(placed.px(c - half)[0]).astype(int)), tuple(np.round(placed.px(c + half)[0]).astype(int)), int(rng.uniform(70, 110)), 2, cv2.LINE_AA)
    valley = cv2.GaussianBlur(layer.astype(np.float32) / 255.0, (0, 0), 1.6) * (mask > 0)
    img -= valley[..., None] * np.array([depth * 0.7, depth, depth * 0.9], np.float32)

    img += rng.normal(0, 3.5, img.shape).astype(np.float32)  # sensor grain
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    return np.clip(img, 0, 255).astype(np.uint8), placed


def jpeg(image: np.ndarray, quality: int = 92) -> bytes:
    ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return data.tobytes()


def distance_to_polyline(points: np.ndarray, polyline: np.ndarray) -> np.ndarray:
    """For each point, its distance to the nearest stretch of the polyline."""
    a, b = polyline[:-1], polyline[1:]
    ab = b - a
    out = np.empty(len(points))
    for i, p in enumerate(points):
        t = np.clip(((p - a) * ab).sum(axis=1) / np.maximum((ab * ab).sum(axis=1), 1e-9), 0, 1)
        nearest = a + t[:, None] * ab
        out[i] = np.sqrt(((p - nearest) ** 2).sum(axis=1)).min()
    return out


def sample_polyline(polyline, count: int = 200) -> np.ndarray:
    """`count` points spread evenly along a polyline (so a long line is not judged by where its few corners are)."""
    poly = np.asarray(polyline, np.float64)
    step = np.hypot(*np.diff(poly, axis=0).T)
    along = np.concatenate([[0.0], np.cumsum(step)])
    at = np.linspace(0.0, along[-1], count)
    return np.stack([np.interp(at, along, poly[:, 0]), np.interp(at, along, poly[:, 1])], axis=1)
