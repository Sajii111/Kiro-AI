"""Method A: the crease map. Where the palm's creases run, and in which direction.

Creases are thin dark valleys in the skin. A valley filter (the Hessian: how the brightness curves across and along each
pixel, at three scales) gives every pixel a valley strength and the direction across the valley. The strongest
`keep` share of pixels becomes the crease map, and pieces too small to be a crease are dropped.

Two things are kept and compared:

- the map itself, softened and shrunk, compared by normalised cross-correlation at small shifts (so a photo a few
  pixels off still lines up). This is what makes the method geometric: the same creases in the same places.
- a direction histogram for each cell of a grid: how much crease runs in each of `bins` directions there, compared by
  cosine similarity. It forgives a crease that moved a little within its cell but not one that changed direction.

The similarity is the mean of the two, between 0 (nothing alike) and 1 (identical).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.cv.palm import valley

from .config import CreaseSettings

#: pixels at the border of the square ignored by the valley filter (it sees past the edge there)
BORDER = 4


@dataclass
class CreaseFeature:
    #: the softened crease map, `map_size` x `map_size`, float32
    map: np.ndarray
    #: (grid, grid, bins) direction histograms, each cell scaled to length 1 (or all zeros)
    grid: np.ndarray


@dataclass
class CreaseDetail:
    """What a person is shown for this step."""

    strength: np.ndarray  # valley strength, float32, size x size
    lines: np.ndarray  # bool, size x size


def valleys(norm: np.ndarray, sigmas: tuple[float, ...]) -> tuple[np.ndarray, np.ndarray]:
    best = across = None
    for sigma in sigmas:
        strength, angle = valley(norm, sigma)
        if best is None:
            best, across = strength, angle
        else:
            wins = strength > best
            best, across = np.where(wins, strength, best), np.where(wins, angle, across)
    assert best is not None and across is not None
    best = best.astype(np.float32)
    best[:BORDER, :] = best[-BORDER:, :] = 0
    best[:, :BORDER] = best[:, -BORDER:] = 0
    return best, across.astype(np.float32)


def crease_lines(strength: np.ndarray, settings: CreaseSettings) -> np.ndarray:
    inner = strength[BORDER:-BORDER, BORDER:-BORDER]
    cut = float(np.quantile(inner, 1.0 - settings.keep))
    lines = (strength > cut) & (strength > 0)
    _count, labels, stats, _ = cv2.connectedComponentsWithStats(lines.astype(np.uint8), connectivity=8)
    small = np.where(stats[:, cv2.CC_STAT_AREA] < settings.min_area)[0]
    if len(small):
        lines[np.isin(labels, small)] = False
    return lines


def direction_grid(strength: np.ndarray, across: np.ndarray, lines: np.ndarray, settings: CreaseSettings) -> np.ndarray:
    n = strength.shape[0]
    cells, bins = settings.grid, settings.bins
    along = np.mod(across + np.pi / 2, np.pi)  # the direction the crease runs, 0 to pi
    which = np.minimum((along / np.pi * bins).astype(np.int32), bins - 1)
    weight = np.where(lines, strength, 0.0)
    cell = n // cells
    out = np.zeros((cells, cells, bins), np.float32)
    rows = np.minimum(np.arange(n) // cell, cells - 1)
    flat_cell = (rows[:, None] * cells + rows[None, :]).ravel()
    idx = flat_cell * bins + which.ravel()
    np.add.at(out.reshape(-1), idx, weight.ravel())
    norms = np.linalg.norm(out, axis=2, keepdims=True)
    return np.where(norms > 1e-9, out / np.maximum(norms, 1e-9), 0.0).astype(np.float32)


def extract(norm: np.ndarray, settings: CreaseSettings) -> tuple[CreaseFeature, CreaseDetail]:
    strength, across = valleys(norm, settings.sigmas)
    lines = crease_lines(strength, settings)
    soft = cv2.GaussianBlur(lines.astype(np.float32), (0, 0), settings.blur)
    small = cv2.resize(soft, (settings.map_size, settings.map_size), interpolation=cv2.INTER_AREA)
    grid = direction_grid(strength, across, lines, settings)
    return CreaseFeature(map=small.astype(np.float32), grid=grid), CreaseDetail(strength=strength, lines=lines)


def best_correlation(a: np.ndarray, b: np.ndarray, shift: int) -> float:
    """The highest normalised cross-correlation of `b` against `a` over shifts of up to `shift` pixels each way."""
    n = a.shape[0]
    s = shift
    core = a[s : n - s, s : n - s]
    core = core - core.mean()
    core_norm = float(np.sqrt((core * core).sum()))
    if core_norm < 1e-9:
        return 0.0
    best = -1.0
    for dy in range(-s, s + 1):
        for dx in range(-s, s + 1):
            part = b[s + dy : n - s + dy, s + dx : n - s + dx]
            part = part - part.mean()
            part_norm = float(np.sqrt((part * part).sum()))
            if part_norm < 1e-9:
                continue
            best = max(best, float((core * part).sum()) / (core_norm * part_norm))
    return best


def similarity(a: CreaseFeature, b: CreaseFeature, settings: CreaseSettings) -> float:
    corr = max(0.0, best_correlation(a.map, b.map, settings.shift))
    ga, gb = a.grid.ravel(), b.grid.ravel()
    denom = float(np.linalg.norm(ga) * np.linalg.norm(gb))
    cos = float(ga @ gb) / denom if denom > 1e-9 else 0.0
    return 0.5 * corr + 0.5 * max(0.0, cos)
