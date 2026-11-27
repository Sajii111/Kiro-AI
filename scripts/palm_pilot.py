"""Palm lock pilot: runs the palm lock (ICA 02) on a few people's photos and shows how well it tells them apart.

    run.bat palm                         Windows: reads E:\\Project\\palm-photos, writes E:\\Project\\debug\\palm
    python scripts/palm_pilot.py         the same, from any terminal (use the Python in backend/.venv)
    python scripts/palm_pilot.py --photos some\\folder --out other\\folder
    python scripts/palm_pilot.py --drawn                 drawn test hands instead of photos (no hand model needed)
    python scripts/palm_pilot.py --calibrate             also write the threshold and normalisers measured here
                                                         into backend/app/cv/biometric/calibration.json
    python scripts/palm_pilot.py --sweep                 also try the square at several heights of the palm and show how well each
                                                         tells people apart (nothing is changed or written)

It runs the same code the server runs: the photo checks with the hand model, then the palm lock's steps (the square from
the middle of the palm, the preprocessing, the crease map and the competitive code). It writes:

    <person>_<photo>_palm.jpg   the photo with the square, the square, the even grey picture, the creases, the code
    scores.jpg                  every photo against every other: green = same person, red = different people
    palm_summary.txt            the scores, how far apart the same-person and different-person scores are, the
                                threshold at the equal error rate, and a pretend lock for each person: the first three
                                photos lock it, every other photo tries to open it

Photos: put them in the photos folder as   person1\\1.jpg  person1\\2.jpg ...  person2\\1.jpg ...  (one folder per person,
any file names). Every photo is taken as the RIGHT hand, unless its folder or file name contains "left". Use five or
more photos per person, on different occasions if you can (take the hand away between photos).

The photos are personal, and so are the pictures this makes: they are written outside the project, to E:\\Project\\debug.
Never commit them, and delete them when the pilot is done.
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
    print('  Run  run.bat  once (it makes backend\\.venv and installs them), then use  run.bat palm')
    print()
    raise SystemExit(1) from None

PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
TILE = 220
ENROL_PHOTOS = 3


def say(text: str = '') -> None:
    print(text, flush=True)


def find_people(folder: Path) -> dict[str, list[Path]]:
    people: dict[str, list[Path]] = {}
    for path in sorted(folder.rglob('*')):
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS:
            rel = path.relative_to(folder)
            person = rel.parts[0] if len(rel.parts) > 1 else 'person'
            people.setdefault(person, []).append(path)
    return people


def side_of(path: Path) -> str:
    return 'left' if 'left' in str(path).lower() else 'right'


def tile(picture: np.ndarray, title: str) -> np.ndarray:
    h, w = picture.shape[:2]
    scale = TILE / max(h, w)
    small = cv2.resize(picture, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST)
    if small.ndim == 2:
        small = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
    out = np.full((TILE + 30, TILE, 3), 24, np.uint8)
    out[30 : 30 + small.shape[0], : small.shape[1]] = small
    cv2.putText(out, title, (6, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 1, cv2.LINE_AA)
    return out


def sheet(bgr: np.ndarray, extraction, label: str) -> np.ndarray:
    from app.cv.biometric import visuals

    pics = visuals.steps(extraction)
    tiles = [
        tile(visuals.photo_with_square(bgr, extraction), 'photo + square'),
        tile(pics['roi'], 'square'),
        tile(pics['contrast'], 'even grey'),
        tile(pics['creases'], 'A: creases'),
        tile(pics['code'], 'B: code'),
    ]
    row = np.hstack(tiles)
    times = ', '.join(f'{k} {v:.0f}' for k, v in extraction.timings.items())
    foot = np.full((28, row.shape[1], 3), 24, np.uint8)
    text = f'{label}   on hand {extraction.roi.inside:.0%}   detail {extraction.prepared.spread:.1f}   ms: {times}'
    cv2.putText(foot, text, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA)
    return np.vstack([row, foot])


#: how each drawn photo of a person differs from the first: (turn in degrees, size, brightness)
DRAWN_SHOTS = [(0, 480, 1.0), (12, 430, 0.9), (-15, 520, 1.1), (25, 460, 1.0), (-6, 500, 0.95), (-20, 450, 1.05), (8, 490, 0.92)]


def drawn_people(people: int = 6, photos: int = 5) -> dict[str, list[tuple[str, np.ndarray, np.ndarray]]]:
    """Made-up people, a few drawn photos each: the same drawn palm turned, closer or further, lighter or darker."""
    sys.path.insert(0, str(BACKEND / 'tests'))
    from synth import found, render

    out: dict[str, list[tuple[str, np.ndarray, np.ndarray]]] = {}
    for p in range(people):
        shots = []
        for k, (angle, scale, gain) in enumerate(DRAWN_SHOTS[:photos]):
            img, placed = render(angle=angle, scale=scale, seed=100 + p)
            rng = np.random.default_rng(1000 * p + k)
            img = np.clip(img.astype(np.float32) * gain + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
            shots.append((f'drawn{p + 1}/{k + 1}', img, found(placed).points))
        out[f'drawn{p + 1}'] = shots
    return out


def matrix_picture(names: list[str], owners: list[str], scores: np.ndarray, threshold: float) -> np.ndarray:
    n = len(names)
    cell = max(18, min(48, 900 // max(n, 1)))
    margin, top = 150, 60
    img = np.full((top + n * cell + 10, margin + n * cell + 10, 3), 250, np.uint8)
    for i in range(n):
        for j in range(n):
            s = scores[i, j]
            same = owners[i] == owners[j]
            colour = np.array((90, 180, 60) if same else (60, 60, 220), float)  # BGR
            shade = (np.array([250, 250, 250]) * (1 - s) + colour * s).astype(np.uint8)
            y, x = top + i * cell, margin + j * cell
            img[y : y + cell - 1, x : x + cell - 1] = shade
            if i != j and s >= threshold:
                cv2.rectangle(img, (x, y), (x + cell - 2, y + cell - 2), (0, 0, 0), 1)
            if cell >= 30 and i != j:
                cv2.putText(img, f'{s:.2f}', (x + 2, y + cell // 2 + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(img, names[i][-18:], (4, top + i * cell + cell // 2 + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, f'fused score; boxed = at or above the threshold {threshold:.2f}', (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, 'green: same person   red: different people', (4, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return img


# The square used to be placed from the wrist point (its middle at 0.55 of the way from the wrist to the knuckles, turned
# with the wrist-to-knuckles line). This is that old placement, kept only to show how much it moved between photos.
OLD_CENTER = 0.55


def placement_lines(sources: list[tuple[str, str, np.ndarray, np.ndarray, str]]) -> list[str]:
    """Where the old, wrist-based square would have sat on each photo, measured against the knuckle line. The new square sits at
    the same place on every photo by construction, so the spread here is what the change removes."""
    from app.cv.biometric.roi import knuckle_frame
    from app.cv.hand import hand_frame

    rows: dict[str, list[tuple[str, float, float, float, float]]] = {}
    for person, label, _picture, points, _side in sources:
        palm, kf = hand_frame(points), knuckle_frame(points)
        if palm is None or kf is None:
            continue
        old = palm.wrist + palm.length * OLD_CENTER * palm.u
        d = old - kf.origin
        along = float(d @ kf.v) / kf.span
        below = -float(d @ kf.u) / kf.span
        turned = float(np.degrees(np.arctan2(kf.u[0] * palm.u[1] - kf.u[1] * palm.u[0], float(kf.u @ palm.u))))
        rows.setdefault(person, []).append((label, kf.span / palm.length, along, below, turned))
    if not rows:
        return []
    out = [
        'Where the earlier square (placed from the wrist point) sat on each photo, against the knuckle line.',
        'The square now follows the knuckle line, so it sits at the same place on every photo.',
        '  photo                 knuckle span / palm length   sideways (spans)   below the knuckles (spans)   turned (degrees)',
    ]
    for person, items in rows.items():
        for label, flat, along, below, turned in items:
            out.append(f'  {label:20s}  {flat:27.2f}   {along:+15.2f}   {below:25.2f}   {turned:+15.1f}')
        belows = [r[3] for r in items]
        turns = [r[4] for r in items]
        out.append(f'  {person}: the earlier square moved up to {max(belows) - min(belows):.2f} spans along the palm and turned up to {max(turns) - min(turns):.0f} degrees between its photos')
    return out


def sweep_lines(sources: list[tuple[str, str, np.ndarray, np.ndarray, str]], base) -> list[str]:
    """The same photos, with the square's middle at several heights below the knuckle line. A positive gap means every same-person
    pair scored above every different-people pair."""
    from dataclasses import replace

    from app.cv.biometric.engine import Problem, extract_from_image
    from app.cv.biometric.evaluate import calibrate

    out = [
        'The square at several heights of the palm (its middle, in knuckle spans below the line of the knuckles).',
        'Everything else is as it is now. gap = lowest same-person score minus highest different-people score (above 0 is a clean split).',
        '  below   photos   same person: mean (lowest)   different people: mean (highest)    gap     EER',
    ]
    for below in (0.55, 0.65, 0.75, 0.85, 1.0):
        variant = replace(base, roi=replace(base.roi, center_below=below))
        groups: dict[str, list] = {}
        refused = 0
        for person, _label, picture, points, side in sources:
            r = extract_from_image(picture, points, side, variant)
            if isinstance(r, Problem):
                refused += 1
            else:
                groups.setdefault(person, []).append(r.features)
        mark = '  <- now' if abs(below - base.roi.center_below) < 1e-9 else ''
        try:
            here, pairs = calibrate(groups, 'sweep', False, variant)
        except ValueError:
            out.append(f'  {below:4.2f}    too few usable photos ({refused} refused){mark}')
            continue
        g = [here.fuse(r) for r in pairs.genuine]
        i = [here.fuse(r) for r in pairs.impostor]
        out.append(
            f'  {below:4.2f}    {sum(len(v) for v in groups.values()):3d}      {np.mean(g):.2f} ({min(g):.2f})                 {np.mean(i):.2f} ({max(i):.2f})            '
            f'{min(g) - max(i):+.2f}   {here.measured["eer"]:.1%}' + (f'   ({refused} refused)' if refused else '') + mark
        )
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Runs the palm lock on a few people and shows how well it tells them apart.')
    parser.add_argument('--photos', type=Path, default=ROOT.parent / 'palm-photos', help='one folder per person (default: ..\\palm-photos)')
    parser.add_argument('--out', type=Path, default=ROOT.parent / 'debug' / 'palm', help='where the pictures go (default: ..\\debug\\palm)')
    parser.add_argument('--model', type=Path, default=None, help='the hand model file (default: backend\\models\\hand_landmarker.task)')
    parser.add_argument('--drawn', action='store_true', help='use drawn test hands instead of photos')
    parser.add_argument('--sweep', action='store_true', help='also try the square at several heights of the palm and compare how well each tells people apart')
    parser.add_argument('--calibrate', action='store_true', help='write the threshold and normalisers measured here into calibration.json')
    args = parser.parse_args(argv)

    from app.core.config import Settings
    from app.cv.biometric.config import DEFAULT
    from app.cv.biometric.engine import (
        Problem,
        enrol,
        extract,
        extract_from_image,
        score_matrix,
        verify,
    )
    from app.cv.biometric.evaluate import calibrate
    from app.cv.biometric.match import (
        CALIBRATION_PATH,
        CalibrationError,
        load_calibration,
        save_calibration,
    )
    from app.cv.images import check_photo

    settings = Settings()
    extracted: dict[str, list] = {}
    names: list[str] = []
    owners: list[str] = []
    refused: list[str] = []
    args.out.mkdir(parents=True, exist_ok=True)

    sources: list[tuple[str, str, np.ndarray, np.ndarray, str]] = []  # (person, label, picture, landmarks, side) of every usable photo

    def keep(person: str, label: str, bgr: np.ndarray, result, points: np.ndarray | None = None) -> None:
        if isinstance(result, Problem):
            refused.append(f'{label}: Invalid Image ({result.code}): {result.message}')
            say(f'    Invalid Image: {result.message}')
            return
        extracted.setdefault(person, []).append(result)
        if points is not None:
            sources.append((person, label, bgr, points, result.side))
        names.append(label)
        owners.append(person)
        cv2.imwrite(str(args.out / f'{label.replace("/", "_").rsplit(".", 1)[0]}_palm.jpg'), sheet(bgr, result, label), [cv2.IMWRITE_JPEG_QUALITY, 88])

    if args.drawn:
        for person, photos in drawn_people().items():
            for label, img, points in photos:
                say(f'  {label} ...')
                keep(person, label, img, extract_from_image(img, points, 'right', DEFAULT), points)
    else:
        from app.cv.hand import MediaPipeFinder

        model = args.model or settings.hand_model
        if not args.photos.is_dir():
            say()
            say(f'  The photo folder {args.photos} does not exist.')
            say('  Put the photos there as person1\\1.jpg, person1\\2.jpg ... person2\\1.jpg ..., or use  --photos FOLDER')
            say()
            return 1
        if not model.is_file():
            say()
            say(f'  The hand model {model} is missing. Run  run.bat models  first.')
            say()
            return 1
        people = find_people(args.photos)
        if not people:
            say(f'  No photos (jpg or png) found under {args.photos}.')
            return 1
        finder = MediaPipeFinder(model)
        try:
            for person, paths in people.items():
                for path in paths:
                    label = f'{person}/{path.name}'
                    say(f'  {label} ...')
                    checked = check_photo(path.read_bytes(), side_of(path), settings.max_pixels, finder)  # type: ignore[arg-type]
                    result = extract(checked, DEFAULT)
                    keep(person, label, checked.analysis if checked.analysis is not None else np.zeros((8, 8, 3), np.uint8), result, checked.hand.points if checked.hand is not None else None)
        finally:
            finder.close()

    usable = {p: v for p, v in extracted.items() if v}
    lines: list[str] = []
    out = lines.append
    out('Palm lock pilot')
    out('===============')
    out(f'{sum(len(v) for v in usable.values())} usable photo(s) of {len(usable)} person(s); {len(refused)} refused as Invalid Image.')
    for r in refused:
        out(f'  {r}')
    out('')
    if len(usable) < 2 or not any(len(v) >= 2 for v in usable.values()):
        out('Telling people apart needs at least two people, one of them with two usable photos or more.')
        (args.out / 'palm_summary.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        say('\n'.join(lines))
        return 1

    calibrated = (not args.drawn) and len(usable) >= 5 and all(len(v) >= 3 for v in usable.values())
    source = ('drawn test hands' if args.drawn else f'pilot photos: {len(usable)} people') + f', {sum(len(v) for v in usable.values())} photos'
    if not calibrated:
        source += ' (a placeholder until a real dataset is measured)'
    here, pairs = calibrate({p: [e.features for e in v] for p, v in usable.items()}, source, calibrated)

    out('Raw similarity of each method (its own scale), same person vs different people:')
    for m in ('crease', 'compcode', 'lbp'):
        g = np.array([s[m] for s in pairs.genuine])
        i = np.array([s[m] for s in pairs.impostor])
        gap = (g.mean() - i.mean()) / max(np.sqrt((g.var() + i.var()) / 2), 1e-9)
        role = 'decides' if m in here.weights else 'spare'
        out(f"  {m:9s} ({role:7s})  same {g.mean():.3f} (lowest {g.min():.3f})   different {i.mean():.3f} (highest {i.max():.3f})   separation d' = {gap:.2f}")
    out('')
    out('Fused score with normalisers fitted on these photos:')
    for k, v in here.measured.items():
        out(f'  {k}: {v}')
    out(f'  threshold at the equal error rate: {here.threshold:.4f}')
    out('')

    flat_samples = [e.features for p in usable for e in usable[p]]
    flat_names = [n for n, o in zip(names, owners, strict=True) if o in usable]
    flat_owners = [o for o in owners if o in usable]
    matrix = score_matrix(flat_samples, here, DEFAULT)
    cv2.imwrite(str(args.out / 'scores.jpg'), matrix_picture(flat_names, flat_owners, matrix, here.threshold), [cv2.IMWRITE_JPEG_QUALITY, 92])
    out('Fused score of every pair (rows and columns in this order):')
    for i, n in enumerate(flat_names):
        out(f'  {i + 1:2d} {n}')
    out('     ' + ' '.join(f'{j + 1:5d}' for j in range(len(flat_names))))
    for i in range(len(flat_names)):
        out(f'  {i + 1:2d} ' + ' '.join(f'{matrix[i, j]:5.2f}' for j in range(len(flat_names))))
    out('')

    out_lines = placement_lines(sources)
    lines.extend(out_lines)
    if out_lines:
        out('')

    try:
        shipped = load_calibration()
        out(f'The threshold the website uses now (calibration.json): {shipped.threshold:.4f} ({shipped.source})')
    except CalibrationError as e:
        shipped = None
        out(f'calibration.json could not be used: {e}')
    out('')
    out(f'A pretend lock for each person: the first {ENROL_PHOTOS} photos lock it, every other photo tries to open it')
    out('(with the threshold fitted here, so this is optimistic: the photos that set it are the ones tried).')
    tally = {'genuine': [0, 0], 'impostor': [0, 0]}
    for person, samples in usable.items():
        if len(samples) < ENROL_PHOTOS:
            out(f'  {person}: only {len(samples)} photo(s), not enough to lock')
            continue
        template = enrol(samples[:ENROL_PHOTOS], samples[0].side, here, DEFAULT)
        if not hasattr(template, 'samples'):
            out(f'  {person}: the lock was not made: {template.message}')  # type: ignore[union-attr]
            continue
        for other, tries in usable.items():
            start = ENROL_PHOTOS if other == person else 0
            for k, e in enumerate(tries[start:], start=start):
                d = verify(template, e, here, DEFAULT)  # type: ignore[arg-type]
                kind = 'genuine' if other == person else 'impostor'
                tally[kind][0] += 1
                tally[kind][1] += d.outcome == 'success'
                parts = f'crease {d.methods.get("crease", 0):.2f}, code {d.methods.get("compcode", 0):.2f}'
                out(f'  lock {person:12s} photo {other}/{k + 1:<3d} {d.title:26s} score {d.score:.3f}  ({parts})')
    g_tries, g_ok = tally['genuine']
    i_tries, i_ok = tally['impostor']
    out('')
    out(f'  same person opened their lock: {g_ok} of {g_tries}' + (f' (FRR {1 - g_ok / g_tries:.1%})' if g_tries else ''))
    out(f'  someone else opened a lock:    {i_ok} of {i_tries}' + (f' (FAR {i_ok / i_tries:.1%})' if i_tries else ''))

    if args.calibrate:
        save_calibration(here, CALIBRATION_PATH)
        out('')
        out(f'Wrote the threshold and normalisers to {CALIBRATION_PATH} (calibrated: {here.calibrated}).')
    elif shipped is None:
        out('')
        out('Run again with --calibrate to write these numbers into calibration.json.')

    if args.sweep:
        out('')
        lines.extend(sweep_lines(sources, DEFAULT))

    (args.out / 'palm_summary.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    say()
    say('\n'.join(lines))
    say()
    say(f'  Pictures, scores.jpg and palm_summary.txt are in {args.out}')
    if not args.drawn:
        say('  They contain your photos: keep them out of the project, never commit them, and delete them when done.')
    say()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
