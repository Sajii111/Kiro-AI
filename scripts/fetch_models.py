"""Downloads the MediaPipe hand model (hand_landmarker.task) into backend/models/.

    run.bat models                    Windows: the easy way
    python scripts/fetch_models.py    the same, from any terminal

Phase 2 uses this model to find the hand in a photo. It is one file of about 7 MB from Google's public MediaPipe model
storage. Only the Python standard library is used, so this works before the private Python environment exists.

Options
    --force      download again even if a good copy is already there
    --check      only say whether a good copy is there (nothing is downloaded)
    --url URL    download from somewhere else (a mirror, or a web address on this computer)

The file is checked after the download (it must be a model bundle, not a web page saved by mistake), and it only
appears under its real name once the check has passed, so a half-finished download can never be mistaken for the model.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

MODEL_NAME = 'hand_landmarker.task'
MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task'
MODELS_DIR = Path(__file__).resolve().parents[1] / 'backend' / 'models'

MIN_BYTES = 1_000_000  # the real file is about 7.5 MB
MAX_BYTES = 100_000_000
CHUNK = 64 * 1024
TIMEOUT_SECONDS = 30  # for each wait on the network, not for the whole download


def say(text: str = '') -> None:
    print(text, flush=True)


def problem_with(path: Path) -> str | None:
    """None when `path` is a sound MediaPipe model bundle, otherwise one sentence that says what is wrong with it."""
    try:
        size = path.stat().st_size
    except OSError as error:
        return f'it cannot be read ({error})'
    if size < MIN_BYTES:
        return f'it is only {size:,} bytes, far too small to be the model'
    if size > MAX_BYTES:
        return f'it is {size:,} bytes, far too big to be this model'
    # a .task file is a zip archive that holds two or more .tflite models
    if not zipfile.is_zipfile(path):
        return 'it is not a model bundle (it is not a zip archive); a web page saved by mistake looks like this'
    try:
        with zipfile.ZipFile(path) as bundle:
            if bundle.testzip() is not None:
                return 'it is damaged (a part of it does not match its checksum)'
            models = [name for name in bundle.namelist() if name.endswith('.tflite')]
    except (zipfile.BadZipFile, OSError) as error:
        return f'it cannot be opened as a model bundle ({error})'
    if len(models) < 2:
        return f'it holds {len(models)} models and the hand model needs at least 2'
    return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, part: Path) -> str | None:
    """Saves `url` to `part`. None on success, otherwise one sentence that says what went wrong."""
    request = urllib.request.Request(url, headers={'User-Agent': 'kiro-ai-fetch-models/1'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response, open(part, 'wb') as out:
            total = int(response.headers.get('Content-Length') or 0)
            done = 0
            last_shown = -1
            while True:
                block = response.read(CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if total:
                    percent = done * 100 // total
                    if percent // 10 != last_shown // 10:
                        last_shown = percent
                        say(f'  {percent}%  ({done / 1_000_000:.1f} of {total / 1_000_000:.1f} MB)')
            if total and done != total:
                return f'the download stopped early ({done:,} of {total:,} bytes)'
    except urllib.error.HTTPError as error:
        return f'the server answered {error.code} {error.reason}'
    except urllib.error.URLError as error:
        return f'it could not connect ({error.reason}). Is the computer online? A firewall or proxy may be in the way'
    except (TimeoutError, OSError) as error:
        return f'the connection failed ({error})'
    return None


def main(argv: list[str], models_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description='Download the MediaPipe hand model into backend/models/.')
    parser.add_argument('--force', action='store_true', help='download again even if a good copy is already there')
    parser.add_argument('--check', action='store_true', help='only say whether a good copy is there')
    parser.add_argument('--url', default=MODEL_URL, help='download from this address instead of Google')
    args = parser.parse_args(argv)

    folder = models_dir if models_dir is not None else MODELS_DIR
    target = folder / MODEL_NAME
    part = folder / (MODEL_NAME + '.part')

    problem = problem_with(target) if target.exists() else None
    if target.exists() and problem is None and not args.force:
        say(f'The hand model is already in place ({target.stat().st_size / 1_000_000:.1f} MB): {target}')
        say('Nothing to do. Use --force to download it again.')
        return 0
    if args.check:
        if not target.exists():
            say(f'The hand model is not in place yet: {target}')
        else:
            say(f'The hand model needs to be downloaded again: {problem}.')
        say('Run:  run.bat models')
        return 1
    if problem is not None:
        say(f'The file that is there is no good: {problem}. It will be replaced.')

    folder.mkdir(parents=True, exist_ok=True)
    say(f'Downloading the hand model ({MODEL_NAME}, about 7 MB) from')
    say(f'  {args.url}')
    try:
        failure = download(args.url, part)
        if failure is None:
            failure = problem_with(part)
            if failure is not None:
                failure = f'what arrived is no good: {failure}'
        if failure is not None:
            say()
            say(f'The hand model could not be downloaded: {failure}.')
            say('You can also download it by hand: open the address above in a web browser, then save the file as')
            say(f'  {target}')
            return 1
        os.replace(part, target)  # only now does the file get its real name
    finally:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass

    say()
    say(f'Done. The hand model is in place: {target}')
    say(f'  {target.stat().st_size / 1_000_000:.1f} MB, sha256 {sha256_of(target)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
