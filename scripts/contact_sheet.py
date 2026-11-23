"""Contact sheets: shows, for each photo in a folder, exactly what the real analysis does with it.

    run.bat sheet                          Windows: reads E:\\Project\\test-photos, writes E:\\Project\\debug
    python scripts/contact_sheet.py        the same, from any terminal (use the Python in backend/.venv)
    python scripts/contact_sheet.py --photos some\\folder --out other\\folder

It runs the same code the server runs (the six photo checks, the hand model, the straightening, the ridge map and the line
tracer) and draws the working. For every photo it writes one picture, <name>_sheet.jpg, with four panels:

    1  the photo, with the hand's 21 landmarks, its outline and the lines found
    2  the palm straightened (wrist at the bottom, fingers up, thumb to the right), the lines, and the zones searched
    3  the ridge map the lines are traced on: dark = more likely to be a crease
    4  the verdicts: the six checks, the five lines (status, traits, confidence), the hand shape

and a second picture, <name>_steps.jpg, with the six image-processing steps the website shows while it works.
A summary.txt lists the numbers for every photo.

Photos: put them in the photos folder as   person1\\left.jpg  person1\\right.jpg   (any folder names; a file name that
contains "left" or "right" says which hand it is; any other file is checked as a left photo). The photos are personal, so
the pictures this makes (which contain them) are written outside the project, to E:\\Project\\debug. Never commit them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))

try:
    import cv2
    import numpy as np
except ImportError:
    print()
    print('  The Python packages are not installed in this Python.')
    print('  Run  run.bat  once (it makes backend\\.venv and installs them), then use  run.bat sheet')
    print()
    raise SystemExit(1) from None

PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
PANEL_HEIGHT = 560
COLOURS = {  # BGR
    'heart': (60, 60, 255),
    'head': (255, 140, 30),
    'life': (60, 200, 60),
    'fate': (255, 60, 255),
    'sun': (0, 220, 255),
}


def say(text: str = '') -> None:
    print(text, flush=True)


def find_photos(folder: Path) -> list[tuple[str, Path]]:
    """(label, path) for every photo under the folder, in a stable order."""
    found = []
    for path in sorted(folder.rglob('*')):
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS:
            found.append((str(path.relative_to(folder)).replace('\\', '/'), path))
    return found


def side_of(label: str) -> str:
    name = label.lower()
    if 'right' in name and 'left' not in name:
        return 'right'
    return 'left'


def ascii_only(text: str) -> str:
    return text.replace('\u00d7', 'x').replace('\u2019', "'").encode('ascii', 'replace').decode('ascii')


def put_lines(img, lines: list[tuple[str, tuple[int, int, int], float]], x: int, y: int, gap: int = 22) -> int:

    for text, colour, scale in lines:
        for chunk in wrap(ascii_only(text), int(54 / max(scale, 0.3) * 0.55)):
            cv2.putText(img, chunk, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 1, cv2.LINE_AA)
            y += gap if scale >= 0.5 else gap - 4
    return y


def wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ''
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f'{line} {word}'.strip()
    return [*lines, line] if line else ['']


def fit_height(img, height: int):

    scale = height / img.shape[0]
    return cv2.resize(img, (max(1, round(img.shape[1] * scale)), height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)


def dotted(img, points, colour, thickness: int) -> None:

    pts = np.asarray(points, np.float64)
    for i in range(0, len(pts) - 1, 2):
        cv2.line(img, tuple(np.round(pts[i]).astype(int)), tuple(np.round(pts[i + 1]).astype(int)), colour, thickness, cv2.LINE_AA)


def draw_photo_panel(analysis_img, hand, result, checked):

    img = analysis_img.copy()
    h, w = img.shape[:2]
    thick = max(2, round(max(h, w) / 400))
    if result is not None and result.outline:
        outline = np.array([(x * w, y * h) for x, y in result.outline], np.int32)
        cv2.polylines(img, [outline], True, (0, 255, 0), max(1, thick - 1), cv2.LINE_AA)
    if result is not None:
        for f in result.features:
            if f.status == 'not_visible' or not f.path:
                continue
            pts = [(x * w, y * h) for x, y in f.path]
            if f.status == 'detected':
                cv2.polylines(img, [np.round(np.array(pts)).astype(np.int32).reshape(-1, 1, 2)], False, COLOURS[f.id], thick + 1, cv2.LINE_AA)
            else:
                dotted(img, pts, COLOURS[f.id], thick)
            cv2.putText(img, f.id, (int(pts[0][0]) + 6, int(pts[0][1]) - 6), cv2.FONT_HERSHEY_SIMPLEX, max(0.6, w / 1500), COLOURS[f.id], 2, cv2.LINE_AA)
        for c in result.otherCreases:
            pts = np.round(np.array([(x * w, y * h) for x, y in c.path])).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(img, [pts], False, (255, 255, 0), max(1, thick - 1), cv2.LINE_AA)
    if hand is not None:
        for i, (x, y) in enumerate(hand.points):
            tip = i in (4, 8, 12, 16, 20)
            cv2.circle(img, (int(x), int(y)), thick + (2 if tip else 0), (0, 255, 255) if tip else (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(img, (int(x), int(y)), thick + (2 if tip else 0), (0, 0, 0), 1, cv2.LINE_AA)
    return fit_height(img, PANEL_HEIGHT)


def draw_straight_panels(analysis):
    """The straightened palm with the lines and zones, and the ridge map with the lines."""

    from app.cv.palm import to_px, to_rc

    view = analysis.view
    gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(view.image[..., 1])
    left = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    ridge = cv2.cvtColor((255 * (1 - np.clip(view.strength, 0, 1) ** 0.7)).astype(np.uint8), cv2.COLOR_GRAY2BGR)

    for fid, zone in analysis.zones.items():
        poly = np.round(np.array([to_px(x, y) for x, y in zone.corridor])).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(left, [poly], True, (170, 170, 170), 1, cv2.LINE_AA)
    k = view.knuckle_x()
    for x in k.values():
        c = round(to_px(x, 1.0)[0])
        cv2.line(left, (c, 0), (c, 10), (0, 255, 255), 2)
    found = {f.id: f for f in analysis.result.features}
    for fid, trace in analysis.traces.items():
        if trace is None:
            continue
        status = found[fid].status
        rc = np.round(to_rc(trace.xy)).astype(np.int32)[:, ::-1]
        colour = COLOURS[fid] if status != 'not_visible' else (150, 150, 150)
        thick = 3 if status == 'detected' else 1
        for img in (left, ridge):
            cv2.polylines(img, [rc.reshape(-1, 1, 2)], False, colour, thick, cv2.LINE_AA)
        cv2.putText(left, f'{fid} ({status})', (int(rc[0, 0]) + 4, int(rc[0, 1]) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)
    return left, ridge


def text_panel(label: str, side: str, checked, analysis) -> np.ndarray:
    img = np.full((PANEL_HEIGHT, 560, 3), 255, np.uint8)
    ink, grey, red, green, amber = (30, 30, 30), (110, 110, 110), (40, 40, 200), (40, 140, 40), (0, 130, 220)
    lines: list[tuple[str, tuple[int, int, int], float]] = [(label, ink, 0.6), (f'added as the {side} hand, {checked.width} x {checked.height} px', grey, 0.45), ('', ink, 0.4)]
    for c in checked.result.checks:
        colour = green if c.status == 'pass' else amber if c.status == 'warn' else red
        lines.append((f'[{c.status.upper():4s}] {c.label}', colour, 0.5))
        if c.status != 'pass':
            lines.append((f'        {c.message}', grey, 0.42))
    if checked.hand is not None:
        h = checked.hand
        lines.append(('', ink, 0.4))
        lines.append((f'hand model: {h.label} hand, sure {h.score:.2f}; palm length {checked.facts.length:.0f} px', grey, 0.45))
    if analysis is not None:
        r = analysis.result
        lines.append(('', ink, 0.4))
        lines.append(('LINES', ink, 0.55))
        for f in r.features:
            colour = green if f.status == 'detected' else amber if f.status == 'uncertain' else grey
            t = f.traits
            words = '/'.join(x for x in (t.length, t.curve, t.clarity) if x)
            conf = f'{f.confidence:.2f}' if f.confidence is not None else '-'
            lines.append((f'{f.name:11s} {f.status:11s} conf {conf:5s} {words}', colour, 0.45))
        s = r.palmShape
        if s.status == 'detected':
            lines.append((f'shape: {s.traits.palm} palm ({s.palmRatio:.2f}), {s.traits.fingers} fingers ({s.fingerRatio:.2f})', ink, 0.45))
        else:
            lines.append((f'shape: {s.status}', grey, 0.45))
        lines.append((f'other creases: {len(r.otherCreases)}    ridge contrast: {analysis.view.contrast:.4f}', grey, 0.45))
    put_lines(img, lines, 12, 26, 21)
    return img


def process_photo(label: str, path: Path, finder, settings, out: Path, summary: list[str]) -> None:

    from app.cv.images import check_photo
    from app.cv.lines import analyse
    from app.cv.pipeline import run_steps
    from app.schemas import PhotoSize

    side = side_of(label)
    data = path.read_bytes()
    checked = check_photo(data, side, settings.max_pixels, finder)
    stem = label.rsplit('.', 1)[0].replace('/', '_')

    analysis = None
    if checked.ok and checked.hand is not None and checked.analysis is not None and checked.quality is not None:
        analysis = analyse(side, checked.analysis, checked.hand, PhotoSize(width=checked.width, height=checked.height), checked.quality, cut_off=bool(checked.facts and checked.facts.cut_off_palm))

    summary.append(f'== {label} (as the {side} hand, {checked.width} x {checked.height} px)')
    for c in checked.result.checks:
        summary.append(f'   [{c.status:4s}] {c.label}: {c.message}')
    if analysis is not None:
        r = analysis.result
        for f in r.features:
            tr = analysis.traces.get(f.id)
            extra = f'length {tr.length:.2f}, mean strength {tr.mean:.2f}, coverage {tr.cover:.2f}' if tr is not None else 'no path'
            summary.append(f'   {f.name:11s} {f.status:11s} confidence {f.confidence}  {f.traits.model_dump(exclude_none=True)}  ({extra})')
        s = r.palmShape
        summary.append(f'   hand shape: {s.status} {s.traits.model_dump(exclude_none=True)} palm {s.palmRatio} fingers {s.fingerRatio}')
        summary.append(f'   other creases: {len(r.otherCreases)}; ridge contrast {analysis.view.contrast:.4f}')

    base = checked.analysis if checked.analysis is not None else checked.work
    if base is None:
        summary.append('   (the photo could not be opened, so there is nothing to draw)')
        return
    a_panel = draw_photo_panel(base, checked.hand, analysis.result if analysis else None, checked)
    panels = [a_panel]
    if analysis is not None and analysis.view is not None:
        left, ridge = draw_straight_panels(analysis)
        panels += [fit_height(left, PANEL_HEIGHT), fit_height(ridge, PANEL_HEIGHT)]
    panels.append(text_panel(label, side, checked, analysis))
    sheet = np.hstack(panels)
    cv2.imwrite(str(out / f'{stem}_sheet.jpg'), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])

    if checked.work is not None:
        steps = run_steps(checked.work)
        names = ['gray', 'blur', 'contrast', 'edges', 'threshold', 'morphology']
        tiles = []
        for name in names:
            tile = steps[name]
            if tile.ndim == 2:
                tile = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
            tile = fit_height(tile, 420)
            cv2.putText(tile, name, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
            tiles.append(tile)
        top, bottom = np.hstack(tiles[:3]), np.hstack(tiles[3:])
        width = max(top.shape[1], bottom.shape[1])
        rows = [np.pad(m, ((0, 0), (0, width - m.shape[1]), (0, 0))) for m in (top, bottom)]
        cv2.imwrite(str(out / f'{stem}_steps.jpg'), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Draws what the real analysis does with each test photo.')
    parser.add_argument('--photos', type=Path, default=ROOT.parent / 'test-photos', help='the folder with the photos (default: ..\\test-photos)')
    parser.add_argument('--out', type=Path, default=ROOT.parent / 'debug', help='where the pictures go (default: ..\\debug)')
    parser.add_argument('--model', type=Path, default=None, help='the hand model file (default: backend\\models\\hand_landmarker.task)')
    parser.add_argument('--only', default=None, help='only photos whose path contains this text')
    args = parser.parse_args(argv)

    from app.core.config import Settings
    from app.cv.hand import MediaPipeFinder

    settings = Settings()
    model = args.model or settings.hand_model
    if not args.photos.is_dir():
        say()
        say(f'  The photo folder {args.photos} does not exist.')
        say('  Put the photos there as person1\\left.jpg and person1\\right.jpg, or use  --photos FOLDER')
        say()
        return 1
    if not model.is_file():
        say()
        say(f'  The hand model {model} is missing. Run  run.bat models  first.')
        say()
        return 1
    photos = [p for p in find_photos(args.photos) if not args.only or args.only.lower() in p[0].lower()]
    if not photos:
        say(f'  No photos (jpg or png) found under {args.photos}.')
        return 1
    args.out.mkdir(parents=True, exist_ok=True)

    finder = MediaPipeFinder(model)
    summary: list[str] = []
    try:
        for label, path in photos:
            say(f'  {label} ...')
            process_photo(label, path, finder, settings, args.out, summary)
    finally:
        finder.close()
    (args.out / 'summary.txt').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    say()
    say(f'  Done: {len(photos)} photo(s). Pictures and summary.txt are in {args.out}')
    say('  They contain your photos: keep them out of the project and never commit them.')
    say()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
