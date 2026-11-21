"""The image-processing steps, run on the server with OpenCV, and the order they are reported in.

These are the steps the assessment asks to see: grayscale, smoothing (Gaussian blur), contrast (CLAHE), edges (Canny),
thresholding and morphology. Each one runs for real on a working copy of each photo and is sent back as a small
picture (a JPEG data URL, about 400 px), so the website can show original-versus-processed.

The last step, "lines", is where the creases are found. With the hand model installed (and photos of real hands) it is
real: cv/palm.py straightens each palm and builds a ridge map, and cv/lines.py traces and judges the five principal lines.
Otherwise (the website's built-in sample drawings, the tests, or no hand model) the sample finder in cv/standin.py places
them and the reading is labelled a sample.

Nothing is written to disk. The pictures exist for the length of the request.
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Callable

import cv2
import numpy as np

from app.core.clock import iso
from app.core.rand import hash_string
from app.cv.images import CheckedPhoto, js_round
from app.cv.lines import analyse
from app.cv.standin import build_analysis, plan_statuses
from app.llm.gemini import ModelService
from app.llm.report import REAL_META, STAND_IN_META, build_report, count_statuses
from app.llm.writer import write_reading
from app.schemas import Hands, HandSide, PhotoSize, Previews, Reading

#: the longest side of a preview picture
PREVIEW_SIDE = 400
PREVIEW_QUALITY = 80

# the website tints the black-and-white steps warm; the same colours here, in OpenCV's blue-green-red order
TINT_BASE = np.array([32, 18, 24], dtype=np.float32)
TINT_BRIGHT = np.array([170, 214, 255], dtype=np.float32)

#: the six pictures a reading sends back, in order, with the line shown under each step on screen
IMAGE_STAGES: list[tuple[str, str]] = [
    ('gray', 'Colour removed, brightness kept'),
    ('blur', 'Noise and skin texture smoothed away'),
    ('contrast', 'Local contrast lifted so faint creases stand out'),
    ('edges', 'Sharp changes in brightness traced as edges'),
    ('threshold', 'Marks darker than their surroundings turned white, the rest black'),
    ('morphology', 'Tiny specks removed and broken pieces joined'),
]


class Cancelled(Exception):
    """The browser went away. Stop, save nothing."""


# ------------------------------------------------------------------ the steps themselves


def to_gray(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def gaussian(gray: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(gray, (0, 0), sigma)


def clahe(gray: np.ndarray, clip: float = 2.6, tiles: int = 8) -> np.ndarray:
    """Contrast-limited adaptive histogram equalisation: each tile of the picture is stretched on its own, with a limit
    so noise is not blown up with it."""
    return cv2.createCLAHE(clipLimit=clip, tileGridSize=(tiles, tiles)).apply(gray)


def canny(gray: np.ndarray) -> np.ndarray:
    """Edges where brightness changes sharply. The thresholds come from the picture itself (the strongest 7% of
    gradients are sure edges), so a dim photo and a bright one are treated alike."""
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(gx, gy)
    high = max(8.0, float(np.percentile(magnitude, 93)))
    return cv2.Canny(gray, 0.45 * high, high, L2gradient=True)


def adaptive_threshold(gray: np.ndarray, block: int = 21, offset: int = 4) -> np.ndarray:
    """A pixel darker than the average of its own neighbourhood by more than `offset` becomes white (a crease-like
    mark), everything else black. How bright the whole photo is does not matter."""
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, offset)


def morphology(binary: np.ndarray) -> np.ndarray:
    """Opening (erode, then dilate) removes tiny specks; closing (dilate, then erode) joins the pieces of a line that a
    faint patch broke apart."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)


def tinted(binary: np.ndarray) -> np.ndarray:
    """A black-and-white picture in the website's warm colours."""
    v = (binary.astype(np.float32) / 255.0)[..., None]
    return np.clip(TINT_BASE + (TINT_BRIGHT - TINT_BASE) * v, 0, 255).astype(np.uint8)


def run_steps(work: np.ndarray) -> dict[str, np.ndarray]:
    """Every step, one after the other, each fed by the one before. Returns the picture of each step."""
    gray = to_gray(work)
    blurred = gaussian(gray, 1.6)
    contrast = clahe(blurred)
    smooth = gaussian(contrast, 1.3)  # a second, lighter smoothing so the edge and threshold steps do not chase noise
    edges = canny(smooth)
    thresh = adaptive_threshold(smooth)
    return {
        'gray': gray,
        'blur': blurred,
        'contrast': contrast,
        'edges': tinted(edges),
        'threshold': tinted(thresh),
        'morphology': tinted(morphology(thresh)),
    }


def preview(image: np.ndarray) -> str:
    """A small JPEG of a step as a data URL."""
    h, w = image.shape[:2]
    scale = min(1.0, PREVIEW_SIDE / max(w, h))
    if scale < 1.0:
        image = cv2.resize(image, (max(2, js_round(w * scale)), max(2, js_round(h * scale))), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_QUALITY])
    if not ok:
        raise RuntimeError('could not encode a preview')
    return 'data:image/jpeg;base64,' + base64.b64encode(encoded.tobytes()).decode('ascii')


# ------------------------------------------------------------------ the whole reading

#: emit(stage, state, detail, previews) sends one progress event to the browser. It is called from the worker thread.
Emit = Callable[[str, str, 'str | None', 'Previews | None'], None]


def uses_real_analysis(photos: dict[HandSide, CheckedPhoto]) -> bool:
    """True when both photos have a hand found in them by the hand model (and neither is a built-in sample drawing)."""
    return all(p.hand is not None and p.analysis is not None and not p.sample for p in photos.values())


def make_real_reading(
    reading_id: str,
    profile_id: str,
    photos: dict[HandSide, CheckedPhoto],
    created_at: str,
    cancelled: Callable[[], bool] | None = None,
) -> Reading:
    """The real findings and the report for two checked photos: the creases are traced in each photo."""
    hands = {}
    for side in ('left', 'right'):
        p = photos[side]
        assert p.hand is not None and p.analysis is not None and p.quality is not None
        hands[side] = analyse(
            side,  # type: ignore[arg-type]
            p.analysis,
            p.hand,
            PhotoSize(width=p.width, height=p.height),
            p.quality,
            cut_off=bool(p.facts and p.facts.cut_off_palm),
            cancelled=cancelled,
        ).result
    return Reading(
        id=reading_id,
        profileId=profile_id,
        createdAt=created_at,
        hands=Hands(left=hands['left'], right=hands['right']),
        report=build_report(hands, created_at),
        meta=REAL_META,
    )


def make_reading(
    reading_id: str,
    profile_id: str,
    photos: dict[HandSide, CheckedPhoto],
    created_at: str,
) -> Reading:
    """The stand-in findings and report for two checked photos. The same id always gives the same lines."""
    seed = hash_string(reading_id)
    quality = {side: photos[side].quality for side in ('left', 'right')}
    sizes = {side: PhotoSize(width=photos[side].width, height=photos[side].height) for side in ('left', 'right')}
    plan = plan_statuses(seed, quality)  # type: ignore[arg-type]
    hands = {side: build_analysis(side, plan[side], sizes[side], quality[side], seed) for side in ('left', 'right')}  # type: ignore[arg-type]
    return Reading(
        id=reading_id,
        profileId=profile_id,
        createdAt=created_at,
        hands=Hands(left=hands['left'], right=hands['right']),
        report=build_report(hands, created_at),
        meta=STAND_IN_META,
    )


def run_reading(
    reading_id: str,
    profile_id: str,
    photos: dict[HandSide, CheckedPhoto],
    emit: Emit,
    cancel: threading.Event,
    pause_ms: int,
    llm: ModelService | None = None,
) -> Reading:
    """Runs every step on both photos, reporting each one as it starts and ends. Runs in a worker thread.

    It stops at "the report is being written": saving the reading and the final events belong to the caller, so
    `reading` is only ever sent after the reading is stored. Raises Cancelled when the browser has gone.

    `llm` is the language-model service. When it has a key, the report of a real reading is written by Gemini and checked
    (llm/writer.py); a sample reading, or no key, keeps the fixed wording."""

    def pause(factor: float = 1.0) -> None:
        if cancel.wait(pause_ms * factor / 1000):
            raise Cancelled()

    def check() -> None:
        if cancel.is_set():
            raise Cancelled()

    check()

    # 1. the photos were checked again, whatever the browser said (the checks ran before the stream opened)
    emit('validate', 'running', None, None)
    pause()
    emit('validate', 'done', 'Both photos passed the checks', None)

    # 2. one working size
    emit('resize', 'running', None, None)
    pause()
    works = {side: photos[side].work for side in ('left', 'right')}
    longest = max(max(w.shape[:2]) for w in works.values() if w is not None)
    emit('resize', 'done', f'Both photos are {longest} px or less on the longest side', None)

    # 3. the image steps, each for both hands
    pictures = {side: run_steps(works[side]) for side in ('left', 'right')}  # type: ignore[arg-type]
    for key, detail in IMAGE_STAGES:
        check()
        emit(key, 'running', None, None)
        previews = Previews(left=preview(pictures['left'][key]), right=preview(pictures['right'][key]))
        pause(1.2)
        emit(key, 'done', detail, previews)

    # 4. find and name the lines: for real in the photos, or by the sample finder
    check()
    emit('lines', 'running', None, None)
    real = uses_real_analysis(photos)
    if real:
        reading = make_real_reading(reading_id, profile_id, photos, iso(), cancelled=cancel.is_set)
        check()
    else:
        pause(1.4)
        reading = make_reading(reading_id, profile_id, photos, iso())
    found = count_statuses({'left': reading.hands.left, 'right': reading.hands.right})
    summary = f'{found.detected} of 10 lines detected, {found.uncertain} uncertain, {found.not_visible} not visible'
    emit('lines', 'done', summary if real else f'Sample result: {summary}', None)

    # 5. the report is written; the caller saves the reading and then says so
    check()
    emit('reading', 'running', None, None)
    if real and llm is not None and llm.available:
        reading = write_reading(reading, llm, cancelled=cancel.is_set)  # takes as long as Gemini takes; it never raises
    else:
        pause(1.4)
    check()
    return reading
