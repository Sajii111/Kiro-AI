"""Reading and checking one photo, with OpenCV and NumPy. Port of src/api/mock/measure.ts (which the website used while
it had no server), now run on the server so the checks cannot be skipped.

A photo lives in memory only. Nothing here writes it anywhere: the bytes come in, a smaller working copy comes out, and
the original is dropped.

The six checks, in the order the website lists them:
  file_type     first bytes say JPEG or PNG (the name and the Content-Type the browser sent are not trusted)
  integrity     the file opens
  dimensions    big enough to show fine lines (and not so big that it is a decompression bomb)
  blur          variance of the Laplacian
  lighting      average brightness, and how uneven it is
  palm_visible  a hand is in the photo, palm to the camera, big enough, not cut off. With the hand model installed
                this is decided from the hand's 21 landmarks (cv/hand.py). Without it (and for the website's built-in
                sample drawings) it is a simpler guess: enough skin-coloured pixels, not running off the edge.

The thresholds were picked by trying photos, the same way the website's were; they are the knobs to turn if real
photos are judged too strictly or too loosely.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

import cv2
import numpy as np

from app.cv.hand import FoundHand, HandFacts, HandFinder, describe, hand_frame
from app.schemas import (
    CheckStatus,
    HandSide,
    PhotoCheck,
    PhotoQuality,
    QualityLevel,
    ValidationResult,
)

# ------------------------------------------------------------------ thresholds

SHARP_FAIL = 14
SHARP_WARN = 40
DARK_FAIL = 38
DARK_WARN = 70
BRIGHT_WARN = 205
BRIGHT_FAIL = 238
UNEVEN_WARN = 3.4
SHORT_SIDE_FAIL = 500
SHORT_SIDE_WARN = 800
SKIN_MIN = 0.09
SKIN_NONE = 0.005

#: the longest side of the working copy every step after "resize" runs on
WORK_SIDE = 640
#: the longest side of the copy the hand is found and the creases are traced in (the website already keeps photos under this)
ANALYSIS_SIDE = 1600

#: palm length (wrist to knuckles) in pixels of the analysis copy: below the first a warning, below the second a refusal
SMALL_PALM_PX = 260
TINY_PALM_PX = 120
#: knuckle width divided by palm length: how squarely the palm faces the camera (about 0.7 when it does)
TILTED_PALM = 0.45
EDGE_ON_PALM = 0.30
#: middle finger divided by palm length: below this the fingers look curled
CURLED_FINGERS = 0.70
#: a second hand this big, compared with the first, means two hands are in the photo
SECOND_HAND = 0.60

JPEG_MAGIC = b'\xff\xd8\xff'
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


def js_round(value: float) -> int:
    return math.floor(value + 0.5)


# ------------------------------------------------------------------ what is in the file


def sniff_type(data: bytes) -> str | None:
    """'jpeg', 'png' or None, from the first bytes alone."""
    if data.startswith(JPEG_MAGIC):
        return 'jpeg'
    if data.startswith(PNG_MAGIC):
        return 'png'
    return None


_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def header_size(data: bytes, kind: str) -> tuple[int, int] | None:
    """Width and height read from the file header, without decoding any pixels. None when the header is unreadable.
    This is what lets a huge picture be refused before it is expanded in memory."""
    try:
        if kind == 'png':
            if len(data) >= 24 and data[12:16] == b'IHDR':
                w, h = struct.unpack('>II', data[16:24])
                return int(w), int(h)
            return None
        i = 2
        n = len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker == 0xFF:  # a fill byte
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # markers with no length
                i += 2
                continue
            if marker == 0xD9:
                return None
            (seg_len,) = struct.unpack('>H', data[i + 2 : i + 4])
            if marker in _SOF_MARKERS:
                h, w = struct.unpack('>HH', data[i + 5 : i + 9])
                return int(w), int(h)
            i += 2 + max(2, seg_len)
    except (struct.error, IndexError):
        return None
    return None


def decode(data: bytes) -> np.ndarray | None:
    """The picture as a BGR array, or None when the file will not open. The camera's rotation is NOT applied: the
    browser already applied it, and turning the picture again would put every line in the wrong place."""
    try:
        array = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    except cv2.error:
        return None
    if image is None or image.ndim != 3 or image.shape[0] < 1 or image.shape[1] < 1:
        return None
    return image


# ------------------------------------------------------------------ measuring


@dataclass(frozen=True)
class Measures:
    width: int
    height: int
    #: average brightness, 0 to 255
    mean_luma: float
    #: brightest quarter of the picture divided by the darkest quarter
    unevenness: float
    #: how much fine detail there is (variance of the Laplacian). Low means blurry.
    sharpness: float
    #: share of the picture that looks like skin, 0 to 1
    skin_fraction: float
    #: skin reaching the top / side edges suggests fingers or the hand are cut off
    cut_off_top: bool
    cut_off_sides: bool


def measure(bgr: np.ndarray) -> Measures:
    """Rough, fast numbers about a photo, taken on a copy of at most 320 px."""
    height, width = bgr.shape[:2]
    scale = min(1.0, 320 / max(width, height))
    w = max(8, js_round(width * scale))
    h = max(8, js_round(height * scale))
    small = bgr if (w, h) == (width, height) else cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA)

    f = small.astype(np.float32)
    blue, green, red = f[..., 0], f[..., 1], f[..., 2]
    luma = 0.299 * red + 0.587 * green + 0.114 * blue

    # classic skin range in YCbCr space
    cb = 128 - 0.168736 * red - 0.331264 * green + 0.5 * blue
    cr = 128 + 0.5 * red - 0.418688 * green - 0.081312 * blue
    skin = (cb >= 77) & (cb <= 127) & (cr >= 133) & (cr <= 180) & (luma > 30)

    top_rows = max(1, js_round(h * 0.03))
    side_cols = max(1, js_round(w * 0.02))
    top_share = float(skin[:top_rows].any(axis=0).sum()) / w
    left_share = float(skin[:, :side_cols].sum()) / (h * side_cols)
    right_share = float(skin[:, w - side_cols :].sum()) / (h * side_cols)

    # Laplacian variance: sharp pictures have lots of fine contrast, blurry ones do not
    lap = 4 * luma[1:-1, 1:-1] - luma[1:-1, :-2] - luma[1:-1, 2:] - luma[:-2, 1:-1] - luma[2:, 1:-1]
    sharpness = float((lap * lap).mean() - lap.mean() ** 2)

    # the brightest and darkest quarter (rows y < h/2 are the upper half)
    hh, ww = (h + 1) // 2, (w + 1) // 2
    quarters = [luma[:hh, :ww].mean(), luma[:hh, ww:].mean(), luma[hh:, :ww].mean(), luma[hh:, ww:].mean()]
    unevenness = float(max(quarters) / max(1.0, min(quarters)))

    return Measures(
        width=width,
        height=height,
        mean_luma=float(luma.mean()),
        unevenness=unevenness,
        sharpness=sharpness,
        skin_fraction=float(skin.mean()),
        cut_off_top=top_share > 0.12,
        cut_off_sides=left_share > 0.3 or right_share > 0.3,
    )


# ------------------------------------------------------------------ the checklist

LABELS = {
    'file_type': 'File type',
    'integrity': 'File opens',
    'dimensions': 'Size',
    'blur': 'Focus',
    'lighting': 'Lighting',
    'palm_visible': 'Palm in view',
}
ORDER = ['file_type', 'integrity', 'dimensions', 'blur', 'lighting', 'palm_visible']


def _level(status: CheckStatus) -> QualityLevel:
    return 'good' if status == 'pass' else 'fair' if status == 'warn' else 'poor'


def checks_from_measures(m: Measures) -> list[PhotoCheck]:
    """Turns the raw numbers into the checklist the photo screen shows."""
    short_side = min(m.width, m.height)

    dims: CheckStatus = 'fail' if short_side < SHORT_SIDE_FAIL else 'warn' if short_side < SHORT_SIDE_WARN else 'pass'
    blur: CheckStatus = 'fail' if m.sharpness < SHARP_FAIL else 'warn' if m.sharpness < SHARP_WARN else 'pass'
    if m.mean_luma < DARK_FAIL or m.mean_luma > BRIGHT_FAIL:
        light: CheckStatus = 'fail'
    elif m.mean_luma < DARK_WARN or m.mean_luma > BRIGHT_WARN or m.unevenness > UNEVEN_WARN:
        light = 'warn'
    else:
        light = 'pass'
    cut = m.cut_off_top or m.cut_off_sides
    palm: CheckStatus = 'fail' if m.skin_fraction < SKIN_NONE else 'warn' if m.skin_fraction < SKIN_MIN or cut else 'pass'

    if dims == 'fail':
        dims_msg = (
            f'Only {m.width} × {m.height} px, which is too small to find fine lines. '
            f'Please use a photo at least {SHORT_SIDE_WARN} px on its short side. Phone cameras do this by default.'
        )
    elif dims == 'warn':
        dims_msg = f'{m.width} × {m.height} px is on the small side. It can work, but a larger photo shows the lines better.'
    else:
        dims_msg = f'{m.width} × {m.height} px.'

    if blur == 'fail':
        blur_msg = 'This photo is too blurry to see the creases. Tap the palm to focus, hold still, and retake it.'
    elif blur == 'warn':
        blur_msg = 'A little soft. Fine lines may be marked uncertain. A sharper photo gives a better reading.'
    else:
        blur_msg = 'Sharp enough to see fine lines.'

    if light == 'fail':
        light_msg = (
            'This photo is too dark. Move to daylight or a bright room and retake it.'
            if m.mean_luma < 128
            else 'This photo is washed out by bright light. Move out of direct light, turn the flash off and retake it.'
        )
    elif light == 'warn':
        if m.unevenness > UNEVEN_WARN:
            light_msg = 'The light is uneven, with strong shadow on part of the hand. Even light works best.'
        elif m.mean_luma < DARK_WARN:
            light_msg = 'A bit dim. Faint lines may be hard to find. More light would help.'
        else:
            light_msg = 'Quite bright. Avoid flash and direct sun so creases do not wash out.'
    else:
        light_msg = 'Even and bright enough.'

    if palm == 'fail':
        palm_msg = 'We could not find a palm in this photo. Hold the whole palm flat to the camera in even light, then take it again.'
    elif cut:
        palm_msg = 'Parts of the hand look cut off by the edge of the photo. Step back so the whole hand fits, fingertips to wrist.'
    elif m.skin_fraction < SKIN_MIN:
        palm_msg = 'We could not clearly see a palm in this photo. Is the whole palm facing the camera?'
    else:
        palm_msg = 'A palm is in view.'

    return [
        PhotoCheck(id='file_type', label=LABELS['file_type'], status='pass', message='A JPG or PNG photo.'),
        PhotoCheck(id='integrity', label=LABELS['integrity'], status='pass', message='The photo opened normally.'),
        PhotoCheck(id='dimensions', label=LABELS['dimensions'], status=dims, message=dims_msg),
        PhotoCheck(id='blur', label=LABELS['blur'], status=blur, message=blur_msg),
        PhotoCheck(id='lighting', label=LABELS['lighting'], status=light, message=light_msg),
        PhotoCheck(id='palm_visible', label=LABELS['palm_visible'], status=palm, message=palm_msg),
    ]


def quality_from(checks: list[PhotoCheck], m: Measures, palm_visible: bool | None = None) -> PhotoQuality:
    status = {c.id: c.status for c in checks}

    def pts(s: CheckStatus) -> float:
        return 1.0 if s == 'pass' else 0.62 if s == 'warn' else 0.25

    score = pts(status['blur']) * 0.4 + pts(status['lighting']) * 0.3 + pts(status['dimensions']) * 0.15 + pts(status['palm_visible']) * 0.15
    return PhotoQuality(
        sharpness=_level(status['blur']),
        lighting=_level(status['lighting']),
        resolution=_level(status['dimensions']),
        palmVisible=(m.skin_fraction >= SKIN_MIN) if palm_visible is None else palm_visible,
        score=js_round(score * 100) / 100,
    )


# ------------------------------------------------------------------ one photo, start to finish


@dataclass
class CheckedPhoto:
    """Everything learned about one uploaded photo. `work` is the only picture kept: a copy of at most WORK_SIDE px
    that the later steps run on. It is dropped when the request ends."""

    side: HandSide
    result: ValidationResult
    #: the size of the photo as uploaded
    width: int
    height: int
    measures: Measures | None = None
    quality: PhotoQuality | None = None
    work: np.ndarray | None = None
    #: the copy (at most ANALYSIS_SIDE px) the hand was found in, kept only when the hand model was used
    analysis: np.ndarray | None = None
    hand: FoundHand | None = None
    facts: HandFacts | None = None
    #: the person said this is one of the website's built-in sample drawings: judged by the simple check, never by the hand model
    sample: bool = False

    @property
    def ok(self) -> bool:
        return self.result.ok

    def first_problem(self) -> str:
        """The sentence for the first failing check, which already says what to do next."""
        for c in self.result.checks:
            if c.status == 'fail':
                return c.message
        return 'This photo did not pass the checks.'


def working_copy(bgr: np.ndarray, side: int = WORK_SIDE) -> np.ndarray:
    """Brings a picture to one working size: at most `side` px on its longest side. Never enlarges."""
    h, w = bgr.shape[:2]
    scale = min(1.0, side / max(w, h))
    if scale >= 1.0:
        return bgr.copy()
    return cv2.resize(bgr, (max(2, js_round(w * scale)), max(2, js_round(h * scale))), interpolation=cv2.INTER_AREA)


def palm_check_from_hands(hands: list[FoundHand], side: HandSide, width: int, height: int) -> tuple[PhotoCheck, FoundHand | None, HandFacts | None]:
    """The "palm in view" check, decided from the landmarks of the biggest hand found. The first problem found is the one
    reported, most serious first."""

    def result(status: CheckStatus, message: str, hand: FoundHand | None = None, facts: HandFacts | None = None):
        return PhotoCheck(id='palm_visible', label=LABELS['palm_visible'], status=status, message=message), hand, facts

    lost = 'We could not find a hand in this photo. Hold the whole palm flat to the camera in even light, then take it again.'
    if not hands:
        return result('fail', lost)
    hand = hands[0]
    frame = hand_frame(hand.points)
    if frame is None:
        return result('fail', lost)
    facts = describe(hand, frame, width, height, side)

    if facts.shows_palm is False:
        return result('fail', 'This looks like the back of the hand. Turn your hand over so the palm faces the camera, then take it again.', hand, facts)
    if facts.length < TINY_PALM_PX:
        return result('fail', 'The hand is very small in this photo. Move closer so the palm fills most of the frame, then take it again.', hand, facts)
    if facts.flatness < EDGE_ON_PALM:
        return result('fail', 'The palm is turned away from the camera. Hold it flat, facing the camera, then take it again.', hand, facts)

    if facts.side_matches is False:
        other = 'right' if side == 'left' else 'left'
        return result(
            'warn',
            f'This looks like a {other} hand, but it was added as the {side} hand. If that is right, swap the photos. (A photo taken in selfie mode can come out mirrored.)',
            hand,
            facts,
        )
    if len(hands) > 1 and hands[1].size >= SECOND_HAND * hand.size:
        return result('warn', 'Two hands are in this photo, and only the larger one is read. Please photograph one hand at a time.', hand, facts)
    if facts.flatness < TILTED_PALM:
        return result('warn', 'The palm is tilted away from the camera, which squeezes the lines. Hold it flat and facing the camera if you can.', hand, facts)
    if facts.cut_off_palm:
        return result('warn', 'Parts of the hand look cut off by the edge of the photo. Step back so the whole hand fits, fingertips to wrist.', hand, facts)
    if facts.cut_off:
        return result('warn', 'The thumb looks cut off by the edge of the photo. Step back a little so the whole hand fits.', hand, facts)
    if facts.length < SMALL_PALM_PX:
        return result('warn', 'The palm fills only a small part of this photo, so fine lines may be missed. Move closer so the palm fills most of the frame.', hand, facts)
    if facts.finger_reach < CURLED_FINGERS:
        return result('warn', 'The fingers look curled. Open the hand and spread the fingers a little.', hand, facts)
    return result('pass', 'A palm is in view.', hand, facts)


def _not_checked(why: str, ids: list[str]) -> list[PhotoCheck]:
    return [PhotoCheck(id=i, label=LABELS[i], status='warn', message=f'Not checked, because {why}.') for i in ids]  # type: ignore[arg-type]


def check_photo(data: bytes, side: HandSide, max_pixels: int, finder: HandFinder | None = None, sample: bool = False) -> CheckedPhoto:
    """Runs the six checks on one photo. Never raises for a bad photo: a bad photo is an answer (ok = false), not an error.

    With a `finder` the hand is found for real and the "palm in view" check is decided from it. Without one, or when
    `sample` says the photo is one of the website's built-in sample drawings, the simple skin-colour guess is used."""

    def done(width: int, height: int, checks: list[PhotoCheck], **extra) -> CheckedPhoto:
        ok = not any(c.status == 'fail' for c in checks)
        return CheckedPhoto(
            side=side,
            result=ValidationResult(side=side, ok=ok, width=width, height=height, checks=checks),
            width=width,
            height=height,
            **extra,
        )

    kind = sniff_type(data)
    if kind is None:
        checks = [
            PhotoCheck(id='file_type', label=LABELS['file_type'], status='fail', message='This does not look like a JPG or PNG photo. Please choose a different file.'),
            *_not_checked('the file is not a JPG or PNG photo', ORDER[1:]),
        ]
        return done(0, 0, checks)

    declared = header_size(data, kind)
    if declared is None:
        checks = [
            PhotoCheck(id='file_type', label=LABELS['file_type'], status='pass', message='A JPG or PNG photo.'),
            PhotoCheck(id='integrity', label=LABELS['integrity'], status='fail', message='This photo could not be opened. It may be damaged. Please choose a different one.'),
            *_not_checked('the photo could not be opened', ORDER[2:]),
        ]
        return done(0, 0, checks)

    dw, dh = declared
    if dw < 1 or dh < 1 or dw * dh > max_pixels:
        too_big = dw * dh > max_pixels
        message = (
            f'This photo is {dw * dh / 1e6:.0f} megapixels, which is more than can be opened safely (the limit is {max_pixels / 1e6:.0f}). '
            'Please use a smaller photo. Anything a phone camera takes is fine.'
            if too_big
            else 'This photo could not be opened. It may be damaged. Please choose a different one.'
        )
        checks = [
            PhotoCheck(id='file_type', label=LABELS['file_type'], status='pass', message='A JPG or PNG photo.'),
            PhotoCheck(id='integrity', label=LABELS['integrity'], status='warn' if too_big else 'fail', message='Not opened, because it is too large.' if too_big else message),
            PhotoCheck(id='dimensions', label=LABELS['dimensions'], status='fail', message=message if too_big else 'Not checked, because the photo could not be opened.'),
            *_not_checked('the photo could not be opened', ORDER[3:]),
        ]
        return done(dw, dh, checks)

    image = decode(data)
    if image is None:
        checks = [
            PhotoCheck(id='file_type', label=LABELS['file_type'], status='pass', message='A JPG or PNG photo.'),
            PhotoCheck(id='integrity', label=LABELS['integrity'], status='fail', message='This photo could not be opened. It may be damaged. Please choose a different one.'),
            *_not_checked('the photo could not be opened', ORDER[2:]),
        ]
        return done(dw, dh, checks)

    height, width = image.shape[:2]
    m = measure(image)
    checks = checks_from_measures(m)

    analysis: np.ndarray | None = None
    hand: FoundHand | None = None
    facts: HandFacts | None = None
    palm_ok: bool | None = None
    if finder is not None and not sample:
        analysis = working_copy(image, ANALYSIS_SIDE)
        palm_check, hand, facts = palm_check_from_hands(finder.find(analysis), side, analysis.shape[1], analysis.shape[0])
        assert checks[-1].id == 'palm_visible'
        checks[-1] = palm_check
        palm_ok = palm_check.status != 'fail'

    quality = quality_from(checks, m, palm_ok)
    # the original is not needed again: keep only the working copies
    work = working_copy(image)
    return done(width, height, checks, measures=m, quality=quality, work=work, analysis=analysis, hand=hand, facts=facts, sample=sample)
