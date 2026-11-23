"""Makes the zip file that is handed in.

    run.bat package                 builds the website if it is out of date, runs every check, then makes the zip
    run.bat package --dry-run       does every check and says what would be packed, but makes no zip
    run.bat package --no-model      leaves the hand model out (7 MB smaller; whoever runs the app then runs  run.bat models  once)
    run.bat package --out DIR       puts the zip in DIR instead of ..\\submission
    python scripts/package.py ...   the same from any terminal

The zip holds one folder, kiro-ai: the source code, the tests, the docs, run.bat, the README, the website as it was built (so that
a computer without Node.js can start it) and the MediaPipe hand model. Unzip it, double-click run.bat.

It is made so that the wrong thing cannot be handed in. It stops, and makes no zip, when

    - a file looks like it holds a key (the same check as `run.bat preflight`), or a private file would be packed
      (backend\\.env, backend\\secrets\\*, a .env or .env.local in the project folder)
    - a picture is among the files that is not one of the project's own drawn sample hands. A photo of a palm must never travel
      in the zip: the pictures that may be in it are small, and carry no camera data (no GPS position, no phone model)
    - the built website is not the one the sources make, or is the sample-data build
    - the hand model is damaged

After the zip is made it is opened again, unpacked into a temporary folder and checked a second time, from the other side:
what is in the zip is what was meant, nothing private is, and the website in it counts as up to date with the sources in it
(that is what lets a computer without Node.js start it). If that fails, the zip is deleted.

Left out on purpose, and said so at the end: the folders that can be made again (node_modules, backend\\.venv, the sample-data
build in dist), caches, your own folders test-photos, debug and submission, and every private file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

if hasattr(sys.stdout, 'reconfigure'):  # a Windows console may not speak UTF-8; never let a print crash the check
    sys.stdout.reconfigure(errors='replace')

import fetch_models
import repo_checks
import serve

INSIDE = 'kiro-ai'  # the one folder at the top of the zip
MODEL_REL = 'backend/models/hand_landmarker.task'
NOTICE_REL = 'backend/models/NOTICE.txt'
LICENSE_REL = 'docs/licenses/Apache-2.0.txt'

#: folders that are never packed, wherever they are, and why
LEFT_OUT_FOLDERS = {
    '.git': 'version history',
    'node_modules': 'made again by npm install',
    '.venv': 'the private Python environment, made again by run.bat',
    'dist': 'the sample-data build of the website',
    '__pycache__': 'caches',
    '.pytest_cache': 'caches',
    '.ruff_cache': 'caches',
    '.mypy_cache': 'caches',
    '.vscode': 'editor settings',
    '.idea': 'editor settings',
    'test-photos': 'your photos',
    'debug': 'what the checks wrote about your photos',
    'submission': 'zips made earlier',
}
LEFT_OUT_SUFFIXES = {'.pyc': 'caches', '.pyo': 'caches', '.log': 'logs', '.part': 'unfinished downloads', '.swp': 'editor files', '.tmp': 'temporary files'}
LEFT_OUT_NAMES = {'.DS_Store': 'system files', 'Thumbs.db': 'system files', 'desktop.ini': 'system files'}

#: a file in the project folder itself that feeds the website build. A zip made without it could not be started from.
BUILD_SETTINGS = ('.env', '.env.local')

RASTER = frozenset({'.jpg', '.jpeg', '.jpe', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.heif', '.avif', '.ico'})
#: the only places a picture may be (the two drawn hands the tests use; icons for the page) ...
PICTURE_FOLDERS = ('backend/tests/data/', 'public/', 'src/assets/')
PICTURE_TYPES = ('.jpg', '.jpeg', '.png')
#: ... and how big one may be. A phone photo of a palm is several megabytes; the drawn samples are 200 kB.
BIGGEST_PICTURE = 400_000
KNOWN_BINARY = frozenset({'.woff', '.woff2', '.task'})
#: a picture written into a text file (a data: address), long enough to be a photo and not an icon
DATA_PICTURE = re.compile(r'data:image/(?:jpe?g|png|webp|gif|bmp|tiff?|heic|heif|avif)[^,\'"\s]{0,40},[A-Za-z0-9+/=%_\-]{20000,}', re.IGNORECASE)

#: what a lecturer needs to find in the zip. The check opens the finished zip and looks for each of these.
REQUIRED = (
    'README.md', 'run.bat', '.gitignore', 'backend/requirements.txt', 'backend/.env.example', 'backend/app/main.py',
    'backend/secrets/.gitkeep', 'backend/models/.gitkeep', 'scripts/serve.py', 'scripts/preflight.py', 'scripts/package.py',
    'dist-server/index.html', 'dist-server/build-info.json', 'dist-server/source.sha256', 'docs/API_CONTRACT.md',
)

NOTICE = f"""hand_landmarker.task
====================
This is the MediaPipe Hand Landmarker model bundle (a palm detector and a hand-landmark model) made by Google. It is the file
that `run.bat models` downloads from
    {fetch_models.MODEL_URL}
and it is included here, unchanged, so that Kiro AI can read photos without a download. Kiro AI claims no part of it.

Licence: its model card ("Model Card Hand Tracking (Lite_Full) with Fairness", Oct 2021) says
    LICENSED UNDER Apache License, Version 2.0.
The text of that licence is in docs/licenses/Apache-2.0.txt. The model is used to find where the hand and its fingers are in a
photo. Nothing in it says anything about palmistry.
"""


def say(text: str = '') -> None:
    print(text, flush=True)


# ------------------------------------------------------------------ what is packed


@dataclass
class Plan:
    root: Path
    files: list[tuple[Path, str]] = field(default_factory=list)  # (the file on disk, its name inside the project)
    extra: dict[str, bytes] = field(default_factory=dict)  # files this script writes itself, by name
    left_out: list[tuple[str, str]] = field(default_factory=list)  # (name, why)
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def names(self) -> list[str]:
        return sorted([rel for _, rel in self.files] + list(self.extra))


def walk(root: Path) -> tuple[list[tuple[Path, str]], list[tuple[str, str]], list[str]]:
    """Every file that may be packed, what was left out and why, and the problems found on the way."""
    kept: list[tuple[Path, str]] = []
    left_out: list[tuple[str, str]] = []
    problems: list[str] = []
    for directory, folders, names in os.walk(root):
        here = Path(directory)
        keep = []
        for folder in sorted(folders):
            if folder in LEFT_OUT_FOLDERS:
                left_out.append(((here / folder).relative_to(root).as_posix() + '/', LEFT_OUT_FOLDERS[folder]))
            else:
                keep.append(folder)
        folders[:] = keep
        for name in sorted(names):
            path = here / name
            rel = path.relative_to(root).as_posix()
            if rel in BUILD_SETTINGS:
                problems.append(
                    f'{rel} is in the project folder. It feeds the website build, and it is private, so a zip made without it could not '
                    'be started from. Rename it (for example to env.local.bak) and run  run.bat package  again: it builds the website again without it.'
                )
            elif repo_checks.is_private(rel):
                left_out.append((rel, 'private files (keys and settings)'))
            elif name in LEFT_OUT_NAMES:
                left_out.append((rel, LEFT_OUT_NAMES[name]))
            elif path.suffix.lower() in LEFT_OUT_SUFFIXES:
                left_out.append((rel, LEFT_OUT_SUFFIXES[path.suffix.lower()]))
            elif rel.startswith('backend/models/') and name != '.gitkeep':
                left_out.append((rel, 'downloads in backend/models (the hand model is added on its own)'))
            else:
                kept.append((path, rel))
    return kept, left_out, problems


def make_plan(root: Path | None = None, *, include_model: bool = True) -> Plan:
    root = root or ROOT
    files, left_out, problems = walk(root)
    plan = Plan(root=root, files=files, left_out=left_out, problems=problems)

    model = root / MODEL_REL
    if not include_model:
        plan.notes.append('The hand model is not in the zip (--no-model). Whoever runs the app must run  run.bat models  once.')
    elif not model.is_file():
        plan.notes.append(
            'There is no hand model in backend/models on this computer, so the zip has none. Run  run.bat models  and package again, '
            'or whoever runs the app must run it once.'
        )
    else:
        why = fetch_models.problem_with(model)
        if why:
            plan.problems.append(f'{MODEL_REL} is not a sound model: {why}. Run  run.bat models --force  to get it again.')
        elif not (root / LICENSE_REL).is_file():
            plan.problems.append(f'The hand model is packed with its licence, and {LICENSE_REL} is missing.')
        else:
            plan.files.append((model, MODEL_REL))
            plan.extra[NOTICE_REL] = NOTICE.encode('utf-8')
            plan.left_out = [(name, why) for name, why in plan.left_out if name != MODEL_REL]
    plan.files.sort(key=lambda pair: pair[1])
    return plan


# ------------------------------------------------------------------ pictures


def camera_data_in(data: bytes) -> str | None:
    """What a camera or a phone writes into a picture (Exif with the time and place, XMP), or None. A picture in a format that
    this does not read is reported as one that may carry such data."""
    if data[:2] == b'\xff\xd8':  # JPEG: a row of segments in front of the image data
        pos = 2
        while pos + 4 <= len(data) and data[pos] == 0xFF:
            marker = data[pos + 1]
            if marker in (0xDA, 0xD9):
                break
            if marker == 0x01 or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                pos += 1 if marker == 0xFF else 2
                continue
            size = int.from_bytes(data[pos + 2 : pos + 4], 'big')
            body = data[pos + 4 : pos + 2 + size]
            if marker == 0xE1 and (body.startswith(b'Exif\0\0') or b'ns.adobe.com/xap' in body[:64]):
                return 'Exif or XMP'
            if marker == 0xED:
                return 'Photoshop or IPTC'
            pos += 2 + size
        return None
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        pos = 8
        while pos + 8 <= len(data):
            size = int.from_bytes(data[pos : pos + 4], 'big')
            kind = data[pos + 4 : pos + 8]
            if kind == b'eXIf':
                return 'Exif'
            if kind == b'iTXt' and b'XML:com.adobe.xmp' in data[pos + 8 : pos + 8 + min(size, 80)]:
                return 'XMP'
            if kind in (b'IDAT', b'IEND'):
                break
            pos += 12 + size
        return None
    return 'a picture format that may carry camera data'


def picture_problems(files: list[tuple[Path, str]]) -> tuple[list[str], list[str]]:
    """(problems, the pictures that are allowed and were found). Only the project's own drawn samples may be packed."""
    problems: list[str] = []
    allowed: list[str] = []
    for path, rel in files:
        suffix = path.suffix.lower()
        text = None if suffix in RASTER or suffix in KNOWN_BINARY else repo_checks.read_text(path)
        if text is not None and DATA_PICTURE.search(text):
            problems.append(f'{rel} has a picture written into it (a data: address). A photo must never be packed, in any form.')
            continue
        if suffix not in RASTER:
            continue
        if not rel.startswith(PICTURE_FOLDERS):
            problems.append(f'{rel} is a picture. Only the drawn sample hands in backend/tests/data (and icons in public) may be in the zip: a photo of a palm must never be.')
        elif suffix not in PICTURE_TYPES:
            problems.append(f'{rel} is in a picture format that may carry camera data, so it is not allowed here.')
        elif path.stat().st_size > BIGGEST_PICTURE:
            problems.append(f'{rel} is {path.stat().st_size:,} bytes. The pictures in the zip are small drawings; a phone photo is not. The limit is {BIGGEST_PICTURE:,} bytes.')
        elif camera := camera_data_in(path.read_bytes()):
            problems.append(f'{rel} carries camera data ({camera}), so it is a real photo and may not be packed.')
        else:
            allowed.append(rel)
    return problems, allowed


def is_binary(path: Path) -> bool:
    """Not text: a NUL byte near the start (the way git tells). A large text file, such as the built website, is still text."""
    try:
        with open(path, 'rb') as handle:
            return b'\0' in handle.read(8192)
    except OSError:
        return False


#: what marks a line in the documents that the author still has to write, such as who made the original website
TO_FILL = re.compile(r'\[AUTHOR TO (?:COMPLETE|CHECK)\b')
#: the documents a lecturer reads, where such a line could be left behind
READ_BY_PEOPLE = ('README.md', 'backend/README.md', 'backend/app/llm/kb/README.md', 'docs/API_CONTRACT.md', 'docs/LLM_DESIGN.md')


def lines_to_fill(root: Path) -> list[str]:
    """The places still marked for the author to write ("README.md, line 350"). Not a reason to refuse the zip: a draft can be
    packed to try it out. It is a reason to look before the zip is handed in."""
    found = []
    for rel in READ_BY_PEOPLE:
        try:
            text = (root / rel).read_text(encoding='utf-8')
        except OSError:
            continue
        found += [f'{rel}, line {number}' for number, line in enumerate(text.splitlines(), 1) if TO_FILL.search(line)]
    return found


def unfamiliar_files(files: list[tuple[Path, str]]) -> list[str]:
    """Binary files of a kind this project does not make (a PDF, a spreadsheet). They may hold pictures, so the person is told."""
    odd = []
    for path, rel in files:
        suffix = path.suffix.lower()
        if suffix in RASTER or suffix in KNOWN_BINARY:
            continue
        if is_binary(path):
            odd.append(rel)
    return odd


# ------------------------------------------------------------------ the website


def site_problem(root: Path) -> str | None:
    """Why the built website in `root` is not the one to hand in, or None."""
    site = root / 'dist-server'
    if not (site / 'index.html').is_file():
        return 'the website has not been built (there is no dist-server folder)'
    stamp = site / 'source.sha256'
    if not stamp.is_file():
        return 'the website was built before run.bat wrote a fingerprint for it'
    if stamp.read_text(encoding='utf-8').strip() != serve.source_stamp(root):
        return 'the built website is older than its sources (something in src, public or package.json changed after the build)'
    try:
        info = json.loads((site / 'build-info.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 'dist-server/build-info.json cannot be read'
    if info.get('mock') is not False:
        return 'the website in dist-server is the sample-data build, which does not talk to the server'
    return None


# ------------------------------------------------------------------ the zip


def safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    """Unpacks a zip, but refuses a name that would land outside `destination` (a name with .. in it, an absolute path)."""
    base = destination.resolve()
    for info in archive.infolist():
        name = info.filename
        target = (destination / name).resolve()
        parts = re.split(r'[\\/]', name)
        if name.startswith(('/', '\\')) or ':' in parts[0] or '..' in parts or base not in (target, *target.parents):
            raise ValueError(f'the zip holds a file that would be unpacked outside its folder: {name}')
    archive.extractall(destination)


def build_zip(plan: Plan, out_dir: Path, stamp: str | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f'{INSIDE}-{stamp or datetime.now().strftime("%Y%m%d-%H%M%S")}.zip'
    final = out_dir / name
    part = out_dir / (name + '.part')
    try:
        with zipfile.ZipFile(part, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, strict_timestamps=False) as archive:
            for path, rel in plan.files:
                archive.write(path, f'{INSIDE}/{rel}')
            for rel, content in sorted(plan.extra.items()):
                info = zipfile.ZipInfo(f'{INSIDE}/{rel}', date_time=time.localtime()[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, content)
        os.replace(part, final)
    finally:
        part.unlink(missing_ok=True)
    return final


def check_zip(path: Path, expected: list[str] | None = None) -> list[str]:
    """Opens a finished zip and looks at what is really in it. The problems found; none means it can be handed in."""
    problems: list[str] = []
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        return [f'the zip cannot be opened: {error}']
    with archive:
        damaged = archive.testzip()
        if damaged:
            return [f'{damaged} is damaged inside the zip']
        names = [i.filename for i in archive.infolist() if not i.is_dir()]
        outside = [n for n in names if not n.startswith(INSIDE + '/')]
        if outside:
            problems.append(f'files outside the {INSIDE} folder: {", ".join(outside[:3])}')
        inside = {n[len(INSIDE) + 1 :] for n in names if n.startswith(INSIDE + '/')}
        if expected is not None and inside != set(expected):
            missing, unexpected = sorted(set(expected) - inside), sorted(inside - set(expected))
            problems.append(f'the zip does not hold what was meant. Missing: {missing[:3]}. Not meant: {unexpected[:3]}')
        problems += [f'{rel} is a private file and is in the zip' for rel in sorted(inside) if repo_checks.is_private(rel) or rel in BUILD_SETTINGS]
        problems += [f'{rel} is missing from the zip' for rel in REQUIRED if rel not in inside]
        if f'{INSIDE}/run.bat' in names:
            batch = archive.read(f'{INSIDE}/run.bat')
            if batch.count(b'\n') != batch.count(b'\r\n'):
                problems.append('run.bat has Unix line endings in the zip, and Windows may not run it properly')
        with tempfile.TemporaryDirectory(prefix='kiro-zipcheck-', ignore_cleanup_errors=True) as scratch:
            try:
                safe_extract(archive, Path(scratch))
            except ValueError as error:
                return [*problems, str(error)]
            copy = Path(scratch) / INSIDE
            files = repo_checks.project_files(copy, skip_dirs=frozenset())
            problems += [str(f) for f in repo_checks.find_secrets(copy, files=files)]
            pictures, _ = picture_problems(files)
            problems += pictures
            if (why := site_problem(copy)) and 'dist-server/index.html' in inside:
                problems.append(f'inside the zip, {why}')
    return problems


# ------------------------------------------------------------------ the run


def megabytes(size: int) -> str:
    return f'{size / 1_000_000:.1f} MB'


def summary_of_left_out(left_out: list[tuple[str, str]]) -> list[str]:
    groups: dict[str, list[str]] = {}
    for name, why in left_out:
        groups.setdefault(why, []).append(name)
    lines = []
    for why, names in sorted(groups.items()):
        shown = ', '.join(n.replace('/', '\\') for n in names[:3]) + (f', and {len(names) - 3} more' if len(names) > 3 else '')
        lines.append(f'  {why}: {shown}')
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Makes the zip that is handed in.')
    parser.add_argument('--dry-run', action='store_true', help='do every check and say what would be packed, but make no zip')
    parser.add_argument('--no-model', action='store_true', help='leave the hand model out')
    parser.add_argument('--out', default=None, help='put the zip in this folder (default: ..\\submission)')
    args = parser.parse_args(argv)

    root = ROOT
    say('\nKiro AI: checking what goes into the zip\n')
    results: list[str] = []

    def line(status: str, name: str, note: str) -> None:
        results.append(status)
        say(f'  {status}  {name}   [{note}]')

    plan = make_plan(root, include_model=not args.no_model)
    if plan.problems:
        for problem in plan.problems:
            line('FAIL', 'files to pack', problem)
    else:
        size = sum(path.stat().st_size for path, _ in plan.files) + sum(len(c) for c in plan.extra.values())
        line('PASS', 'files to pack', f'{len(plan.names())} files, {megabytes(size)} before compression')

    findings = repo_checks.find_secrets(root, files=plan.files)
    for rel, content in plan.extra.items():  # what this script writes itself is looked at too
        findings += repo_checks.secrets_in(content.decode('utf-8'), rel)
    if findings:
        for finding in findings:
            line('FAIL', 'no key or private file', str(finding))
    else:
        line('PASS', 'no key or private file', f'{len(plan.names())} files looked at, for the shapes real keys have and for private file names')

    pictures, allowed = picture_problems(plan.files)
    if pictures:
        for problem in pictures:
            line('FAIL', 'no photo', problem)
    else:
        line('PASS', 'no photo', f'{len(allowed)} small picture(s), all drawings with no camera data' if allowed else 'no picture at all')

    why = site_problem(root)
    if why:
        line('FAIL', 'the website is current', f'{why}. Run  run.bat --prepare-only  (it builds the website), then this again')
    else:
        line('PASS', 'the website is current', 'built from these sources, with the real server (not the sample data)')

    if MODEL_REL in plan.names():
        line('PASS', 'hand model', f'{megabytes((root / MODEL_REL).stat().st_size)}, with its notice and licence text')
    else:
        line('WARN', 'hand model', plan.notes[-1] if plan.notes else 'not packed')

    odd = unfamiliar_files(plan.files)
    if odd:
        line('WARN', 'unfamiliar files', f'{", ".join(odd[:3])}: these may hold pictures. Open them and make sure they hold nothing you do not want shared')

    blanks = lines_to_fill(root)
    if blanks:
        more = f' and {len(blanks) - 1} more' if len(blanks) > 1 else ''
        verb = 'say' if more else 'says'
        line('WARN', 'lines for you to write', f'{blanks[0]}{more} still {verb} [AUTHOR TO ...]: write it and delete the marker before you hand the zip in')

    if 'FAIL' in results:
        say('\nNo zip was made. Fix the FAIL lines above, then run this again.')
        say('\nRESULT: FAIL')
        return 1
    if args.dry_run:
        say(f'\nThis is what would be packed: {len(plan.names())} files.')
        for text in summary_of_left_out(plan.left_out):
            say(text)
        say('\nRESULT: PASS (dry run: no zip was made)')
        return 0

    out_dir = Path(args.out) if args.out else root.parent / 'submission'
    archive = build_zip(plan, out_dir)
    problems = check_zip(archive, plan.names())
    if problems:
        archive.unlink(missing_ok=True)
        line('FAIL', 'the finished zip, opened again', problems[0])
        for problem in problems[1:6]:
            say(f'        {problem}')
        say('\nThe zip was deleted. Fix the problem above, then run this again.')
        say('\nRESULT: FAIL')
        return 1
    line('PASS', 'the finished zip, opened again', 'nothing private in it, every needed file in it, and it counts as up to date without Node.js')

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    say(f'\nMade {archive}')
    say(f'  {len(plan.names())} files, {megabytes(archive.stat().st_size)}')
    say(f'  SHA-256  {digest}')
    say('\nLeft out on purpose (never packed):')
    for text in summary_of_left_out(plan.left_out):
        say(text)
    say('\nNext: run.bat fresh   unpacks the newest zip somewhere else and starts it with no Node.js, no key and none of your files.')
    say('\nRESULT: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
