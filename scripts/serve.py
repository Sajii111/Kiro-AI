"""Starts Kiro AI: installs and builds whatever is missing, runs the server, and opens the browser.

    run.bat                      Windows: double-click it
    python scripts/serve.py      any system (any Python 3.12 or newer will do; it makes its own private environment)

Safe to run again and again: it only installs or builds what is missing or out of date. The first run takes a few
minutes (it downloads the Python packages and builds the website); after that it starts in a few seconds.

Options
    --no-browser   do not open the browser
    --port N       listen on this port (default 8000, or the next free one)
    --rebuild      build the website again even if it looks up to date
    --no-build     use the website in dist-server as it is, and never try to build it (run.bat preflight uses this)
    --prepare-only install and build, then stop without starting the server
    --packages-only make the private environment and install the Python packages, then stop (run.bat gemini and run.bat live use it)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the folder that holds package.json
BACKEND = ROOT / 'backend'
VENV = BACKEND / '.venv'
SITE = ROOT / 'dist-server'
REQUIREMENTS = BACKEND / 'requirements.txt'
STAMP = VENV / 'requirements.sha256'

MIN_PYTHON = (3, 12)
MIN_NODE = (20, 19)
CHILD_FLAG = 'KIRO_SERVE_CHILD'  # set for the copy that runs inside the private environment
HOST = '127.0.0.1'  # only this computer can reach the server
FIRST_PORT = 8000

#: importable names that prove the packages are installed
NEEDED_MODULES = ('fastapi', 'starlette', 'uvicorn', 'multipart', 'pydantic', 'numpy', 'cv2', 'mediapipe')
#: what the website is built from. If any of it has changed since the build, the build is out of date.
SOURCE_FOLDERS = ('src', 'public')
SOURCE_FILES = ('index.html', 'package.json', 'package-lock.json', 'vite.config.ts', 'tsconfig.json', 'tsconfig.app.json', 'tsconfig.node.json', '.env', '.env.local')
#: written beside the website after every build: a fingerprint of the sources it was built from. A zip that carries the website
#: and this file starts on a computer with no Node.js at all, because the fingerprint still matches there.
SITE_STAMP = SITE / 'source.sha256'

# requests to this computer must never go through a proxy that the Windows or company settings might name
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def say(text: str = '') -> None:
    print(text, flush=True)


def stop(text: str, code: int = 1) -> int:
    say()
    say('  ' + text.strip().replace('\n', '\n  '))
    say()
    return code


# ------------------------------------------------------------------ 1. a private Python environment


def venv_python() -> Path:
    return VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def inside_project_venv() -> bool:
    here = os.path.normcase(os.path.realpath(sys.prefix))
    return here == os.path.normcase(os.path.realpath(VENV))


def start_inside_venv(argv: list[str]) -> int:
    """Makes the private environment on the first run, then runs this same script inside it."""
    if not venv_python().is_file():
        say('Making a private Python environment in backend/.venv (first run only)...')
        made = subprocess.run([sys.executable, '-m', 'venv', str(VENV)], check=False)
        if made.returncode != 0 or not venv_python().is_file():
            return stop(
                'Could not make the private Python environment.\n'
                'Is Python installed with its standard "venv" part? On Windows the python.org installer includes it.'
            )
    child = subprocess.Popen([str(venv_python()), str(Path(__file__).resolve()), *argv], env={**os.environ, CHILD_FLAG: '1'})
    try:
        return child.wait()
    except KeyboardInterrupt:
        # Ctrl+C reaches the child too, and it shuts down by itself. Give it a moment before ending it.
        try:
            return child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            return 0


# ------------------------------------------------------------------ 2. the Python packages


def wanted_stamp() -> str:
    # line endings must not matter: Git on Windows may turn \n into \r\n
    return hashlib.sha256(REQUIREMENTS.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def packages_ready() -> bool:
    if not STAMP.is_file() or STAMP.read_text(encoding='utf-8').strip() != wanted_stamp():
        return False
    return all(importlib.util.find_spec(name) is not None for name in NEEDED_MODULES)


def install_packages() -> int:
    say('[2/4] Installing the Python packages (first run, or the list changed). This can take a few minutes...')
    cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(REQUIREMENTS)]
    if subprocess.run(cmd, check=False).returncode != 0:
        return stop(
            'The Python packages could not be installed.\n'
            'The most common reason is no internet connection: check it and run this again.\n'
            'If the message above says "No matching distribution", this Python is too old or not 64-bit. Install\n'
            '64-bit Python 3.12 or newer from python.org, delete the folder backend\\.venv, and run this again.'
        )
    STAMP.write_text(wanted_stamp(), encoding='utf-8')
    return 0


# ------------------------------------------------------------------ 3. the website


def source_files(root: Path | None = None) -> list[Path]:
    """Every file the website is built from, in a fixed order. `root`: another copy of the project (package.py looks at the
    unpacked zip this way); the default is this one."""
    root = root or ROOT
    files = [root / name for name in SOURCE_FILES if (root / name).is_file()]
    for folder in SOURCE_FOLDERS:
        for directory, names, names_in_folder in os.walk(root / folder):
            names.sort()
            files.extend(Path(directory) / name for name in names_in_folder)
    return sorted(files)


def source_stamp(root: Path | None = None) -> str:
    """A fingerprint of what the website is built from. File dates are no use for this: copying a folder, zipping it or
    cloning it from Git all change them. The content and the names do not change, and line endings are ignored."""
    root = root or ROOT
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes().replace(b'\r\n', b'\n'))
        digest.update(b'\0')
    return digest.hexdigest()


def site_is_current() -> bool:
    """Is the built website the one these sources make? A build from before the fingerprint existed counts as out of date."""
    index = SITE / 'index.html'
    if not index.is_file() or not SITE_STAMP.is_file():
        return False
    return SITE_STAMP.read_text(encoding='utf-8').strip() == source_stamp()


def node_version(node: str) -> tuple[int, int] | None:
    try:
        out = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=30, check=False).stdout.strip()
        major, minor = out.lstrip('v').split('.')[:2]
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def needs_npm_install() -> bool:
    modules = ROOT / 'node_modules'
    if not modules.is_dir():
        return True
    installed = modules / '.package-lock.json'
    lock = ROOT / 'package-lock.json'
    return not installed.is_file() or (lock.is_file() and lock.stat().st_mtime > installed.stat().st_mtime)


def build_site(force: bool) -> int:
    have_old_build = (SITE / 'index.html').is_file()
    if not force and site_is_current():
        say('[3/4] The website is already built and up to date.')
        return 0

    say('[3/4] Building the website (first run, or the screens changed)...')
    node, npm = shutil.which('node'), shutil.which('npm')
    if not node or not npm:
        if have_old_build:
            say('      Node.js was not found, so the older build of the website will be used.')
            return 0
        return stop(
            'Node.js is needed once, to build the website, and was not found.\n'
            'Install the LTS version from https://nodejs.org/ , close this window, and run this again.'
        )
    version = node_version(node)
    if version is not None and version < MIN_NODE:
        say(f'      Warning: Node {version[0]}.{version[1]} is older than {MIN_NODE[0]}.{MIN_NODE[1]}. The build may fail; update Node if it does.')

    if needs_npm_install():
        say('      Installing the website packages (npm install)...')
        if subprocess.run([npm, 'install', '--no-audit', '--no-fund'], cwd=ROOT, check=False).returncode != 0 and not (ROOT / 'node_modules').is_dir():
            return stop('npm install failed, and there are no website packages yet. Check the internet connection and run this again.')

    if subprocess.run([npm, 'run', 'build:server'], cwd=ROOT, check=False).returncode != 0:
        if have_old_build:
            say('      The build failed, so the older build of the website will be used. The message above says why.')
            return 0
        return stop('The website build failed. The message above says why. Fix it, then run this again.')
    SITE_STAMP.write_text(source_stamp(), encoding='utf-8')
    return 0


# ------------------------------------------------------------------ 4. the server


def port_in_use(port: int) -> bool:
    # Connecting is the reliable test: on Windows a second program can bind a busy port without any error.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((HOST, port)) == 0


def kiro_answers_at(port: int) -> bool:
    try:
        with LOCAL.open(f'http://{HOST}:{port}/v1/health', timeout=2) as reply:
            return json.load(reply).get('service') == 'kiro-ai'
    except (OSError, ValueError):
        return False


def open_browser_when_ready(port: int) -> None:
    for _ in range(150):  # up to about 45 seconds
        if kiro_answers_at(port):
            webbrowser.open(f'http://{HOST}:{port}/')
            return
        time.sleep(0.3)


def choose_port(asked: int | None) -> tuple[int | None, bool]:
    """(port to listen on, True if Kiro AI is already running there). port None: nothing usable was found."""
    if asked is not None:
        if not port_in_use(asked):
            return asked, False
        return (asked, True) if kiro_answers_at(asked) else (None, False)
    for port in range(FIRST_PORT, FIRST_PORT + 20):
        if not port_in_use(port):
            return port, False
        if kiro_answers_at(port):
            return port, True
    return None, False


def say_analysis_mode() -> None:
    """Says plainly whether photos will be read for real or only get sample readings, before the server starts."""
    from app.core.config import read_settings
    from app.cv.hand import mediapipe_installed

    settings = read_settings()
    ready = mediapipe_installed() and settings.hand_model.is_file()
    if settings.analysis_mode == 'sample':
        say('      Analysis: SAMPLE only (ANALYSIS_MODE=sample). Every reading is a labelled sample.')
    elif ready:
        say('      Analysis: REAL. The hand model finds the hand in each photo, and the lines are traced in the photo.')
    elif settings.analysis_mode == 'real':
        say(f'      ANALYSIS_MODE=real, but the hand model is missing ({settings.hand_model.name}). The server will stop.')
        say('      Run   run.bat models   once to download it.')
    else:
        say('      Analysis: SAMPLE ONLY, because the hand model file is missing. Photos get labelled sample readings.')
        say('      Run   run.bat models   once to download it, then start again for real analysis.')


def say_writer_mode() -> None:
    """Says plainly who writes the reports and the chat answers: Gemini (a key is set) or the fixed wording from the knowledge base."""
    from app.core.config import read_settings

    settings = read_settings()
    if settings.gemini_api_key:
        models = settings.gemini_models or [settings.gemini_model]
        say(f'      Writer: GEMINI ({models[0]}) writes the report text and the chat answers, and every passage is checked.')
        if len(models) > 1:
            say(f'      If that model is busy or used up, the next one answers: {", ".join(models[1:])} (all on your one key).')
            if settings.gemini_discover:
                say('      The first time, the app asks Google which models your key may use: it leaves out the ones you cannot')
                say('      use and adds a few more Flash models, so a model that Google retired does not slow anything down.')
        say(f'      When Google says "busy", a report waits and asks again for up to {settings.gemini_timeout_s} seconds before the fixed wording is used.')
        say('      Only the findings, as words, go to Google: never photos, names or contact details. On the free tier,')
        say('      Google may use what it receives to improve its products. Check the key once with   run.bat gemini')
    else:
        say('      Writer: the fixed wording from the knowledge base (there is no Gemini key in backend\\.env).')
        say('      To use Gemini, put a free key in backend\\.env, then check it with   run.bat gemini')


def say_storage_mode() -> None:
    """Says plainly where accounts are kept: in the online database (a usable Firebase key is in place) or in memory only."""
    from app.core.config import read_settings
    from app.store.build import check_key

    settings = read_settings()
    if settings.storage == 'memory':
        say('      Storage: MEMORY (STORAGE=memory in backend\\.env). Accounts last until this window closes.')
        return
    if not settings.firebase_key_given:
        if settings.storage == 'firestore':
            say(f'      STORAGE=firestore, but there is no Firebase key at {settings.firebase_key}. The server will stop.')
            return
        say('      Storage: MEMORY. Accounts last until this window closes. To keep them, put the Firebase key in')
        say('      backend\\secrets (see the README), then check it with   run.bat firebase')
        return
    project, problem = check_key(settings)
    if problem:
        if settings.storage == 'firestore':
            say(f'      STORAGE=firestore, but the Firebase key cannot be used: {problem}. The server will stop.')
        else:
            say(f'      Storage: MEMORY, because the Firebase key cannot be used: {problem}.')
            say('      Make a new key (see the README), then check it with   run.bat firebase')
        return
    say(f'      Storage: FIRESTORE (Firebase project {project}). Accounts, their hand profiles, readings and chats are')
    say('      saved there (never photos; guest sessions are never saved). Check the connection with   run.bat firebase')


def run_server(port: int, browser: bool) -> int:
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    os.environ['HOST'] = HOST
    os.environ['PORT'] = str(port)
    os.environ.setdefault('SITE_DIR', str(SITE))

    say(f'[4/4] Starting Kiro AI at http://{HOST}:{port}/')
    say_analysis_mode()
    say_writer_mode()
    say_storage_mode()
    say('      Leave this window open while you use it. Press Ctrl+C here to stop.')
    say()
    if browser:
        threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()

    import uvicorn

    uvicorn.run('app.main:app', host=HOST, port=port, log_level='info', use_colors=False, timeout_graceful_shutdown=5)
    return 0


# ------------------------------------------------------------------ main


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Starts Kiro AI.')
    parser.add_argument('--no-browser', action='store_true', help='do not open the browser')
    parser.add_argument('--port', type=int, default=None, help='listen on this port')
    parser.add_argument('--rebuild', action='store_true', help='build the website again')
    parser.add_argument('--no-build', action='store_true', help='use the website in dist-server as it is')
    parser.add_argument('--prepare-only', action='store_true', help='install and build, then stop')
    parser.add_argument('--packages-only', action='store_true', help='make the private environment and install the Python packages, then stop')
    args = parser.parse_args(argv)

    if sys.version_info < MIN_PYTHON:
        return stop(f'This needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer. This one is {sys.version_info[0]}.{sys.version_info[1]}.')
    if not REQUIREMENTS.is_file():
        return stop(f'Cannot find {REQUIREMENTS}. Run this from inside the Kiro AI folder.')

    if not inside_project_venv() and not os.environ.get(CHILD_FLAG):
        return start_inside_venv(argv)

    say('[1/4] The private Python environment is ready.')
    if packages_ready():
        say('[2/4] The Python packages are installed.')
    else:
        code = install_packages()
        if code:
            return code

    if args.packages_only:
        say('The Python packages are installed. (--packages-only: nothing else was done.)')
        return 0

    if args.no_build:
        say('[3/4] The website is used as it is (--no-build).')
    else:
        code = build_site(args.rebuild)
        if code:
            return code

    if args.prepare_only:
        say('Everything is installed and built. (--prepare-only: not starting the server.)')
        return 0

    port, already = choose_port(args.port)
    if port is None:
        return stop(
            f'Port {args.port or FIRST_PORT} is used by another program, and so are the next ones.\n'
            'Close that program, or pick another port:   run.bat --port 8100'
        )
    if already:
        url = f'http://{HOST}:{port}/'
        say(f'Kiro AI is already running at {url}')
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    if args.port is None and port != FIRST_PORT:
        say(f'      Port {FIRST_PORT} is busy, so Kiro AI will use port {port}.')
    return run_server(port, browser=not args.no_browser)


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        say()
        say('Stopped.')
        sys.exit(0)
