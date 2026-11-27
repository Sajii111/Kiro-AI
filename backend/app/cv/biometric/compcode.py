"""Method B: the competitive code. The strongest line direction in every small block of the palm.

A bank of `orientations` Gabor filters (each one a little wave pattern tuned to lines in one direction) is run over the
picture. Creases are dark, so where a crease runs in a direction the filter for that direction answers most negatively.
In each block of `step` x `step` pixels the direction that "wins" this competition becomes that block's code: a number
from 0 to orientations - 1. Blocks where no filter finds a dark line (smooth skin, or the bright skin between two
creases) are marked weak and left out.

Two codes are compared by angular distance: directions next to each other differ by 1, opposite ones (90 degrees apart)
by orientations / 2. The mean distance over the blocks both codes trust, scaled to 0-1, is tried at small shifts and the
smallest is kept. The similarity is 1 minus that: about 0.5 for two unrelated palms, near 1 for the same palm.

After Kong and Zhang, "Competitive coding scheme for palmprint verification" (ICPR 2004).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from .config import CompCodeSettings


@dataclass
class CompCodeFeature:
    #: (blocks, blocks) uint8: the winning direction of each block
    code: np.ndarray
    #: (blocks, blocks) bool: blocks where a direction clearly won
    valid: np.ndarray


@lru_cache(maxsize=4)
def bank(settings: CompCodeSettings) -> tuple[np.ndarray, ...]:
    kernels = []
    for j in range(settings.orientations):
        theta = j * np.pi / settings.orientations
        k = cv2.getGaborKernel((settings.ksize, settings.ksize), settings.sigma, theta, settings.lambd, settings.gamma, 0, ktype=cv2.CV_32F)
        k = k - k.mean()  # no answer at all to plain, even skin
        k = k / np.abs(k).sum()
        kernels.append(k.astype(np.float32))
    return tuple(kernels)


def responses(norm: np.ndarray, settings: CompCodeSettings) -> np.ndarray:
    """(orientations, blocks, blocks): each filter's mean answer over each block."""
    n = norm.shape[0]
    blocks = n // settings.step
    out = np.empty((settings.orientations, blocks, blocks), np.float32)
    for j, k in enumerate(bank(settings)):
        r = cv2.filter2D(norm, cv2.CV_32F, k, borderType=cv2.BORDER_REFLECT)
        out[j] = cv2.resize(r[: blocks * settings.step, : blocks * settings.step], (blocks, blocks), interpolation=cv2.INTER_AREA)
    return out


def extract(norm: np.ndarray, settings: CompCodeSettings) -> CompCodeFeature:
    r = responses(norm, settings)
    code = np.argmin(r, axis=0).astype(np.uint8)
    # how dark a line the winner found. Between two creases every filter answers about zero or above (bright skin), so
    # the "winner" there is noise: such blocks come out weak and are left out.
    win = np.maximum(-r.min(axis=0), 0.0)
    strong = float(np.quantile(win, 0.9))
    valid = win >= settings.weak * max(strong, 1e-9)
    edge = max(1, settings.ksize // (2 * settings.step))  # blocks the filters saw past the edge of the square
    valid[:edge, :] = valid[-edge:, :] = False
    valid[:, :edge] = valid[:, -edge:] = False
    return CompCodeFeature(code=code, valid=valid)


def distance(a: CompCodeFeature, b: CompCodeFeature, settings: CompCodeSettings) -> float:
    """The smallest mean angular distance over the shifts tried, 0 (identical) to 1 (every block at right angles)."""
    o = settings.orientations
    half = o // 2
    n = a.code.shape[0]
    s = settings.shift
    ca, va = a.code[s : n - s, s : n - s].astype(np.int16), a.valid[s : n - s, s : n - s]
    need = settings.min_overlap * va.size
    best = 1.0
    for dy in range(-s, s + 1):
        for dx in range(-s, s + 1):
            cb = b.code[s + dy : n - s + dy, s + dx : n - s + dx].astype(np.int16)
            vb = b.valid[s + dy : n - s + dy, s + dx : n - s + dx]
            both = va & vb
            count = int(both.sum())
            if count < need:
                continue
            d = np.abs(ca - cb)
            d = np.minimum(d, o - d)
            best = min(best, float(d[both].sum()) / (count * half))
    return best


def similarity(a: CompCodeFeature, b: CompCodeFeature, settings: CompCodeSettings) -> float:
    return 1.0 - distance(a, b, settings)
