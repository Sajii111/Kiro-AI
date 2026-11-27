"""Pictures of each step, for the website's "how it decided" panel and for the pilot contact sheet.

Only ever made for the person looking at their own attempt, and never stored.
"""

from __future__ import annotations

import cv2
import numpy as np

from .engine import Extraction

#: one colour per competitive-code direction (BGR), weak blocks grey
CODE_COLOURS = np.array([[60, 76, 231], [34, 126, 230], [15, 196, 241], [113, 204, 46], [219, 152, 52], [182, 89, 155]], np.uint8)


def photo_with_square(bgr: np.ndarray, extraction: Extraction, width: int = 480) -> np.ndarray:
    """The photo with the cut-out square drawn on it, shrunk to `width`."""
    scale = width / bgr.shape[1]
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    corners = np.round(extraction.roi.corners * scale).astype(np.int32)
    cv2.polylines(small, [corners], True, (40, 200, 255), 2, cv2.LINE_AA)
    cv2.circle(small, tuple(int(v) for v in corners[0]), 4, (40, 200, 255), -1, cv2.LINE_AA)  # the top-left corner
    return small


def contrast_picture(extraction: Extraction) -> np.ndarray:
    return cv2.cvtColor(extraction.prepared.contrast, cv2.COLOR_GRAY2BGR)


def crease_picture(extraction: Extraction) -> np.ndarray:
    out = cv2.cvtColor(extraction.prepared.contrast, cv2.COLOR_GRAY2BGR)
    out = (out * 0.6).astype(np.uint8)
    out[extraction.detail.lines] = (60, 90, 255)
    return out


def code_picture(extraction: Extraction, size: int | None = None) -> np.ndarray:
    feature = extraction.features.compcode
    pic = CODE_COLOURS[feature.code % len(CODE_COLOURS)].copy()
    pic[~feature.valid] = (90, 90, 90)
    n = size or extraction.prepared.contrast.shape[0]
    return cv2.resize(pic, (n, n), interpolation=cv2.INTER_NEAREST)


def steps(extraction: Extraction) -> dict[str, np.ndarray]:
    """Square pictures of the steps, all the same size."""
    return {
        'roi': extraction.roi.image,
        'contrast': contrast_picture(extraction),
        'creases': crease_picture(extraction),
        'code': code_picture(extraction),
    }


# ------------------------------------------------------------------ the evaluation


def score_picture(genuine: np.ndarray, impostor: np.ndarray, threshold: float, title: str = '') -> np.ndarray:
    """Left: how the test scores of same-person and different-person attempts spread, with the threshold. Right: the ROC curve
    (FAR across, the share of genuine attempts accepted up), with the point the threshold gives. Numbers and curves only."""
    from .protocol import confusion_at, roc_curve

    width, height = 1000, 440
    img = np.full((height, width, 3), 250, np.uint8)
    ink, grey = (40, 40, 40), (190, 190, 190)
    green, red = (90, 170, 60), (60, 60, 220)
    font = cv2.FONT_HERSHEY_SIMPLEX

    def text(s: str, x: int, y: int, scale: float = 0.45, colour: tuple[int, int, int] = ink) -> None:
        cv2.putText(img, s, (x, y), font, scale, colour, 1, cv2.LINE_AA)

    def frame(x0: int, y0: int, w: int, h: int, xs: list[str], ys: list[str]) -> None:
        cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), grey, 1)
        for k, label in enumerate(xs):
            text(label, x0 + round(w * k / max(len(xs) - 1, 1)) - 8, y0 + h + 18)
        for k, label in enumerate(ys):
            text(label, x0 - 38, y0 + h - round(h * k / max(len(ys) - 1, 1)) + 4)

    text(title or 'Palm lock: test attempts', 20, 26, 0.6)
    # the spread of the scores, each kind as a share of its own attempts so that the many impostor attempts do not hide the few genuine ones
    x0, y0, w, h = 60, 70, 410, 300
    bins = 20
    g = np.histogram(np.clip(genuine, 0, 1), bins=bins, range=(0, 1))[0] / max(len(genuine), 1)
    i = np.histogram(np.clip(impostor, 0, 1), bins=bins, range=(0, 1))[0] / max(len(impostor), 1)
    top = max(float(g.max(initial=0)), float(i.max(initial=0)), 0.05)
    top = float(np.ceil(top * 10) / 10)
    frame(x0, y0, w, h, ['0', '0.5', '1'], [f'{top * k / 2:.0%}' for k in range(3)])
    step = w / bins
    for k in range(bins):
        for values, colour, shift in ((i, red, 0.0), (g, green, 0.5)):
            bar = round(h * values[k] / top)
            if bar:
                left = x0 + round((k + shift) * step) + 1
                cv2.rectangle(img, (left, y0 + h - bar), (left + round(step / 2) - 2, y0 + h), colour, -1)
    tx = x0 + round(w * float(np.clip(threshold, 0, 1)))
    cv2.line(img, (tx, y0 - 6), (tx, y0 + h), ink, 2, cv2.LINE_AA)
    text(f'threshold {threshold:.2f}', min(tx + 6, x0 + w - 110), y0 - 10)
    text('fused score', x0 + w // 2 - 36, y0 + h + 40)
    cv2.rectangle(img, (x0 + 8, y0 + 8), (x0 + 20, y0 + 20), green, -1)
    text(f'same person ({len(genuine)})', x0 + 26, y0 + 19)
    cv2.rectangle(img, (x0 + 8, y0 + 28), (x0 + 20, y0 + 40), red, -1)
    text(f'different people ({len(impostor)})', x0 + 26, y0 + 39)
    text('share of the attempts of each kind', x0, y0 + h + 62)

    # the ROC curve
    rx, ry, rw, rh = 560, 70, 300, 300
    frame(rx, ry, rw, rh, ['0', '0.5', '1'], ['0', '0.5', '1'])
    cv2.line(img, (rx, ry + rh), (rx + rw, ry), grey, 1, cv2.LINE_AA)
    if len(genuine) and len(impostor):
        far, frr = roc_curve(genuine, impostor)
        pts = np.array([[rx + far[k] * rw, ry + rh - (1 - frr[k]) * rh] for k in range(len(far))], np.int32)
        cv2.polylines(img, [pts], False, (170, 90, 30), 2, cv2.LINE_AA)
        at = confusion_at(genuine, impostor, threshold)
        px, py = rx + round((at.far.value or 0) * rw), ry + rh - round((1 - (at.frr.value or 0)) * rh)
        cv2.circle(img, (px, py), 6, ink, 2, cv2.LINE_AA)
        text('the threshold', min(px + 10, rx + rw - 90), min(py + 22, ry + rh - 8))
    else:
        text('needs both kinds of attempt', rx + 50, ry + rh // 2)
    text('FAR: different people accepted', rx + 40, ry + rh + 40)
    text('same people accepted', rx - 40, ry - 14)
    return img
