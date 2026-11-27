"""Step 2: preprocessing. The square becomes an even grey picture, so the methods see creases and not lighting.

1. green channel: on skin, creases show best in green (red sees through the skin, blue is noisy)
2. a light blur takes out sensor grain
3. CLAHE (contrast-limited adaptive histogram equalisation) evens the contrast across the square
4. flattening: the local average brightness is subtracted, which takes out shading and leaves the detail
5. z-normalising: mean 0, spread 1, so a brighter or darker photo gives the same numbers
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import PrepSettings


@dataclass
class Prepared:
    #: green channel after the light blur, 0-255
    gray: np.ndarray
    #: after CLAHE, 0-255: the picture people are shown
    contrast: np.ndarray
    #: flattened and z-normalised, float32: what the methods read
    norm: np.ndarray
    #: how much the flattened picture varies, in grey levels. Low means a flat, blurred or over-exposed square.
    spread: float


def prepare(roi_bgr: np.ndarray, settings: PrepSettings) -> Prepared:
    green = roi_bgr[..., 1].astype(np.float32)
    if settings.denoise_sigma > 0:
        green = cv2.GaussianBlur(green, (0, 0), settings.denoise_sigma)
    gray = np.clip(np.round(green), 0, 255).astype(np.uint8)
    clahe = cv2.createCLAHE(clipLimit=settings.clahe_clip, tileGridSize=(settings.clahe_tiles, settings.clahe_tiles))
    contrast = clahe.apply(gray)
    level = contrast.astype(np.float32)
    flat = level - cv2.GaussianBlur(level, (0, 0), settings.flatten_sigma)
    spread = float(flat.std())
    norm = ((flat - flat.mean()) / max(spread, 1e-6)).astype(np.float32)
    return Prepared(gray=gray, contrast=contrast, norm=norm, spread=spread)
