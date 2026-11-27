"""The spare method: local binary patterns (LBP). Reported next to the two main methods, not used for the decision.

Every pixel is compared with its 8 neighbours: brighter or not gives 8 bits, a pattern from 0 to 255. Patterns with at
most two changes from 0 to 1 around the circle ("uniform": edges, corners, spots) keep their own bin; all others share
one, so there are 59 bins. A histogram of the patterns in each cell of a grid describes the skin's texture there. Two
palms are compared by the chi-square distance between their histograms.

It is texture without geometry: good at "is this skin like that skin", weak at "are these the same creases". That is
why it is a spare: it shows what the geometric methods add.
"""

from __future__ import annotations

import numpy as np

from .config import LbpSettings

_OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1))


def _uniform_table() -> np.ndarray:
    table = np.full(256, 58, np.uint8)
    label = 0
    for code in range(256):
        bits = [(code >> i) & 1 for i in range(8)]
        changes = sum(bits[i] != bits[(i + 1) % 8] for i in range(8))
        if changes <= 2:
            table[code] = label
            label += 1
    return table


_TABLE = _uniform_table()
BINS = 59


def extract(gray: np.ndarray, settings: LbpSettings) -> np.ndarray:
    g = gray.astype(np.int16)
    n = g.shape[0]
    centre = g[1 : n - 1, 1 : n - 1]
    code = np.zeros_like(centre, dtype=np.uint8)
    for bit, (dy, dx) in enumerate(_OFFSETS):
        code |= ((g[1 + dy : n - 1 + dy, 1 + dx : n - 1 + dx] >= centre).astype(np.uint8) << bit).astype(np.uint8)
    labels = _TABLE[code]
    cells = settings.grid
    m = labels.shape[0]
    cell = m // cells
    hist = np.zeros((cells, cells, BINS), np.float32)
    for r in range(cells):
        for c in range(cells):
            part = labels[r * cell : (r + 1) * cell, c * cell : (c + 1) * cell]
            h = np.bincount(part.ravel(), minlength=BINS).astype(np.float32)
            hist[r, c] = h / max(h.sum(), 1.0)
    return hist


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """1 minus the mean chi-square distance per cell (which lies between 0 and 1)."""
    num = (a - b) ** 2
    den = a + b
    chi = 0.5 * np.where(den > 0, num / np.maximum(den, 1e-12), 0.0).sum(axis=2)
    return float(1.0 - chi.mean())
