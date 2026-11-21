"""Made-up palm photos for the tests and for the smoke check.

They are drawings of the same stylised hand the website uses for its built-in sample photos (a skin-coloured hand on a
grey background, with creases and a little grain so the photo looks sharp to the focus check). No real person is in
them, so they can live in the repository.

    python tests/photos.py            writes tests/data/sample-left.jpg and sample-right.jpg
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.cv.handmodel import LINES, OUTLINE, hand_frame, sample_spline

SKIN_BGR = (140, 172, 224)  # a warm skin tone (the checks look for the skin range in YCbCr space)
BACKGROUND_BGR = (118, 120, 122)


def palm(width: int = 800, height: int = 1000, side: str = 'right', seed: int = 1) -> np.ndarray:
    """A BGR picture of a right hand, palm to the camera (a left hand is the same picture mirrored)."""
    rng = np.random.default_rng(seed)
    img = np.empty((height, width, 3), np.uint8)
    img[:] = BACKGROUND_BGR
    to_px = hand_frame(width, height)

    outline = np.array([to_px(p) for p in sample_spline(OUTLINE, 6)], np.int32)
    cv2.fillPoly(img, [outline], SKIN_BGR, lineType=cv2.LINE_AA)
    cv2.polylines(img, [outline], True, (96, 118, 170), 3, cv2.LINE_AA)

    widths = {'heart': 6, 'head': 6, 'life': 7, 'fate': 4, 'sun': 3}
    for name, pts in LINES.items():
        line = np.array([to_px(p) for p in sample_spline(pts, 8)], np.int32)
        cv2.polylines(img, [line], False, (84, 104, 150), widths[name], cv2.LINE_AA)

    # a little grain, like real skin and a real sensor
    noise = rng.normal(0, 7, img.shape).astype(np.float32)
    img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if side == 'left':
        img = img[:, ::-1].copy()
    return img


def jpeg(image: np.ndarray, quality: int = 90) -> bytes:
    ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return data.tobytes()


def png(image: np.ndarray) -> bytes:
    ok, data = cv2.imencode('.png', image)
    assert ok
    return data.tobytes()


def blurry(image: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(image, (0, 0), 14)


def dark(image: np.ndarray) -> np.ndarray:
    return (image.astype(np.float32) * 0.18).astype(np.uint8)


def not_a_palm(width: int = 800, height: int = 1000) -> np.ndarray:
    """A blue-grey picture with texture and no skin tones at all."""
    rng = np.random.default_rng(3)
    img = np.empty((height, width, 3), np.uint8)
    img[:] = (170, 120, 90)  # BGR: a blue wall
    noise = rng.normal(0, 7, img.shape).astype(np.float32)
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def main() -> None:
    out = HERE / 'data'
    out.mkdir(exist_ok=True)
    (out / 'sample-right.jpg').write_bytes(jpeg(palm(side='right', seed=1)))
    (out / 'sample-left.jpg').write_bytes(jpeg(palm(side='left', seed=2)))
    print('wrote', out / 'sample-left.jpg', 'and', out / 'sample-right.jpg')


if __name__ == '__main__':
    main()
