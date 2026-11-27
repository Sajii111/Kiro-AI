"""Palm lock evaluation (ICA 02): the numbers for the report, measured on a class dataset.

    run.bat palmeval                       Windows: reads E:\\Project\\palm-dataset, writes E:\\Project\\debug\\palm-eval
    python scripts/palm_evaluate.py         the same, from any terminal (use the Python in backend/.venv)
    python scripts/palm_evaluate.py --photos some\\folder --out other\\folder
    python scripts/palm_evaluate.py --enrol 3 --validate 2      how many photos of each person lock, then set the threshold
    python scripts/palm_evaluate.py --drawn                     drawn test hands instead of photos (a check that the script works)
    python scripts/palm_evaluate.py --write-calibration         also write the threshold and normalisers, fitted on the
                                                                validation photos only, into backend/app/cv/biometric/calibration.json

Photos: one folder per person, named with a pseudonym, the photos numbered in the order they were taken:

    palm-dataset\\P01\\1.jpg ... 7.jpg
    palm-dataset\\P02\\1.jpg ... 7.jpg

Every photo is the RIGHT hand unless its folder or file name contains "left". Per person, in number order (2 comes before 10):

    photos 1-3   lock the palm (enrolment)
    photos 4-5   set the threshold (validation), and nothing else
    photos 6-7   test the lock; the reported numbers come from these only

Take photos 1-4 in one sitting and 5-7 in another (another day, or after the hand has been away and the light has changed),
so that the validation photos hold one of each and the test photos come after the lock was made.

It runs the code the server runs: the photo checks with the hand model, the palm steps, the lock made from the enrolment
photos, and every test photo tried against every lock, ones that are the owner's and ones that are not. It writes:

    palm_evaluation.txt   the report: the split, the threshold, trial counts, FAR, FRR, accuracy and its balance, mean latency,
                          a confusion matrix, each method alone and fused, the threshold moved, the worst cases
    palm_attempts.csv     one row per test attempt (labels, outcome, score, milliseconds)
    palm_scores.png       the scores of same-person and different-person attempts, and the ROC curve

Nothing in these files is a photo or a template, and no photo is written anywhere. The photos are personal, though: keep them
outside the project, never commit them, and delete them when the work is marked.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import cv2
    import numpy as np  # noqa: F401
except ImportError:
    print()
    print('  The Python packages are not installed in this Python.')
    print('  Run  run.bat  once (it makes backend\\.venv and installs them), then use  run.bat palmeval')
    print()
    raise SystemExit(1) from None


def say(text: str = '') -> None:
    print(text, flush=True)


def load_shots(folder: Path, split, model: Path | None) -> list:
    """Every photo of every person, checked and put through the palm steps, with the time it took."""
    from palm_pilot import find_people, side_of

    from app.core.config import Settings
    from app.cv.biometric.config import DEFAULT
    from app.cv.biometric.engine import extract
    from app.cv.biometric.protocol import Shot, natural_key
    from app.cv.hand import MediaPipeFinder
    from app.cv.images import check_photo

    settings = Settings()
    model = model or settings.hand_model
    if not model.is_file():
        raise SystemExit(f'\n  The hand model {model} is missing. Run  run.bat models  first.\n')
    people = find_people(folder)
    shots: list = []
    finder = MediaPipeFinder(model)
    try:
        warmed = False
        for person, paths in people.items():
            paths = sorted(paths, key=lambda p: natural_key(p.relative_to(folder).as_posix()))
            for path, role in zip(paths, split.roles(len(paths)), strict=True):
                label = f'{person}/{path.name}'
                side = side_of(path)
                data = path.read_bytes()
                if not warmed:  # the first photo loads the hand model: do it once without the clock
                    extract(check_photo(data, side, settings.max_pixels, finder), DEFAULT)  # type: ignore[arg-type]
                    warmed = True
                say(f'  {label} ({role}) ...')
                t0 = time.perf_counter()
                result = extract(check_photo(data, side, settings.max_pixels, finder), DEFAULT)  # type: ignore[arg-type]
                ms = (time.perf_counter() - t0) * 1000
                if not hasattr(result, 'features'):
                    say(f'    Invalid Image: {result.message}')  # type: ignore[union-attr]
                shots.append(Shot(person, label, role, side, result, round(ms, 1)))
    finally:
        finder.close()
    return shots


def drawn_shots(split, people: int = 6) -> list:
    """Made-up people with seven drawn photos each, to see the script work without a hand model or any photos."""
    from palm_pilot import drawn_people

    from app.cv.biometric.config import DEFAULT
    from app.cv.biometric.engine import extract_from_image
    from app.cv.biometric.protocol import Shot

    shots: list = []
    for person, photos in drawn_people(people=people, photos=7).items():
        for (label, img, points), role in zip(photos, split.roles(len(photos)), strict=True):
            t0 = time.perf_counter()
            result = extract_from_image(img, points, 'right', DEFAULT)
            ms = (time.perf_counter() - t0) * 1000
            shots.append(Shot(person, label, role, 'right', result, round(ms, 1)))
    return shots


def duplicate_warnings(folder: Path) -> list[str]:
    """The same file twice would make a same-person pair look better than it is."""
    from palm_pilot import find_people

    seen: dict[str, Path] = {}
    out: list[str] = []
    for paths in find_people(folder).values():
        for path in paths:
            digest = hashlib.sha1(path.read_bytes()).hexdigest()
            if digest in seen:
                out.append(f'{path.relative_to(folder).as_posix()} is the same file as {seen[digest].relative_to(folder).as_posix()}.')
            else:
                seen[digest] = path
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Measures the palm lock on a class dataset and writes the numbers for the report.')
    parser.add_argument('--photos', type=Path, default=ROOT.parent / 'palm-dataset', help='one folder per person (default: ..\\palm-dataset)')
    parser.add_argument('--out', type=Path, default=ROOT.parent / 'debug' / 'palm-eval', help='where the report goes (default: ..\\debug\\palm-eval)')
    parser.add_argument('--model', type=Path, default=None, help='the hand model file (default: backend\\models\\hand_landmarker.task)')
    parser.add_argument('--enrol', type=int, default=3, help='photos of each person that make the lock (default 3)')
    parser.add_argument('--validate', type=int, default=2, help='photos after those that set the threshold (default 2); the rest are the test')
    parser.add_argument('--drawn', action='store_true', help='use drawn test hands instead of photos')
    parser.add_argument('--drawn-people', type=int, default=6, help='how many drawn people with --drawn (default 6)')
    parser.add_argument('--write-calibration', action='store_true', help='write the threshold and normalisers fitted on the validation photos into calibration.json')
    args = parser.parse_args(argv)

    from app.cv.biometric import visuals
    from app.cv.biometric.config import DEFAULT
    from app.cv.biometric.match import CALIBRATION_PATH, save_calibration
    from app.cv.biometric.protocol import (
        EvaluationError,
        Split,
        attempts_csv,
        evaluate,
        report_lines,
    )

    if args.write_calibration and args.drawn:
        say('\n  --write-calibration with --drawn would put drawn-hand numbers into the website. Use it with the real dataset.\n')
        return 1
    split = Split(args.enrol, args.validate)
    warnings: list[str] = []
    if args.drawn:
        shots = drawn_shots(split, args.drawn_people)
    else:
        if not args.photos.is_dir():
            say()
            say(f'  The photo folder {args.photos} does not exist.')
            say('  Put the photos there as P01\\1.jpg ... P01\\7.jpg, P02\\1.jpg ..., or use  --photos FOLDER')
            say()
            return 1
        shots = load_shots(args.photos, split, args.model)
        warnings = duplicate_warnings(args.photos)
    if not shots:
        say(f'  No photos (jpg or png) found under {args.photos}.')
        return 1

    try:
        ev = evaluate(shots, DEFAULT, split)
    except EvaluationError as e:
        say()
        say(f'  Cannot evaluate yet: {e}')
        say()
        return 1

    lines = report_lines(ev)
    if warnings:
        lines[3:3] = ['WARNING: the same photo is in the dataset twice, which makes same-person scores look better than they are:', *[f'  {w}' for w in warnings], '']
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'palm_evaluation.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (args.out / 'palm_attempts.csv').write_text(attempts_csv(ev), encoding='utf-8')
    cv2.imwrite(str(args.out / 'palm_scores.png'), visuals.score_picture(*ev.fused, ev.calibration.threshold, f'Palm lock, {len(ev.people)} people'))
    say()
    say('\n'.join(lines))
    say()
    if args.write_calibration:
        save_calibration(ev.calibration, CALIBRATION_PATH)
        say(f'  Wrote the threshold {ev.calibration.threshold:.4f} and the normalisers to {CALIBRATION_PATH}')
        say(f'  (calibrated: {ev.calibration.calibrated}; fitted on the validation photos only). Restart run.bat to use it.')
        say()
    say(f'  The report, the attempts and the picture are in {args.out}')
    say('  They hold labels and numbers only, no photos or templates. The photos themselves stay where they are: never commit them.')
    say()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
