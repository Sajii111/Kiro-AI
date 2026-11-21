"""Checks on the project folder itself: keys left in files, what git ignores, exact package versions, forgotten packages.

    python scripts/repo_checks.py          prints one line per check and ends with  RESULT: PASS  or  RESULT: FAIL

The same checks run in the tests (backend/tests/test_repo_checks.py), in `run.bat preflight` and before `run.bat package`
makes the zip, so a key or a photo cannot reach a lecturer by accident. They need nothing but Python.

What they do NOT do: prove there is no secret anywhere. They look for the shapes that real keys have (a Google key starts
with AIza and is 39 characters long, a private key file says so in its first line) and for settings lines such as
SOME_API_KEY=<a long value>. A key that looks like none of these would not be found. The user's own key lives in
backend/.env, which is never read here (only checked to be ignored).
"""

from __future__ import annotations

import ast
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: folders that are never looked into: other people's code, caches, and what the build makes
SKIP_DIRS = frozenset({'.git', 'node_modules', '.venv', 'dist', 'dist-server', '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache'})
#: files that are not read at all (generated, or too large to hold anything typed by hand)
SKIP_FILES = frozenset({'package-lock.json'})
#: a file bigger than this is not text anyone wrote by hand
BIGGEST_TEXT = 1_500_000

#: the shapes real secrets have. (what to call it, the pattern). A pattern with a group checks that group, not the whole match.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('a Google API key', re.compile(r'AIza[0-9A-Za-z_\-]{35}')),
    ('a private key', re.compile(r'-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----')),
    ('a service-account file', re.compile(r'"type"\s*:\s*"service_account"')),
    ('a GitHub token', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{36,}')),
    ('a secret key (sk-...)', re.compile(r'\bsk-[A-Za-z0-9_\-]{32,}')),
    ('an AWS access key', re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('a Slack token', re.compile(r'\bxox[abprs]-[A-Za-z0-9\-]{10,}')),
    ('a key typed into a settings line', re.compile(r'(?m)^[ \t]*(?:export[ \t]+)?[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*[ \t]*=[ \t]*["\']?([^\s"\'#]{12,})')),
)
#: a value that contains one of these is an example, not a secret
FAKE_WORDS = ('your', 'paste', 'example', 'placeholder', 'xxx', '...', 'change', 'here', 'test', 'fake', 'dummy', 'not-a-real', '0123456789', 'abcdefghijklmnopqrstuvwxyz')

#: paths that must be ignored by git (they hold keys, photos, or things that can be made again), and paths that must NOT be
MUST_BE_IGNORED = (
    '.env', 'backend/.env', 'backend/secrets/service-account.json', 'backend/models/hand_landmarker.task', 'test-photos/person1/left.jpg',
    'debug/summary.txt', 'backend/.venv/pyvenv.cfg', 'node_modules/react/index.js', 'dist-server/index.html',
)
MUST_NOT_BE_IGNORED = ('.env.example', 'backend/secrets/.gitkeep', 'backend/models/.gitkeep', 'README.md', 'run.bat', 'backend/requirements.txt', 'scripts/serve.py')

#: import name -> the package that provides it (the name as written in requirements.txt). Only third-party imports are listed.
PROVIDED_BY = {
    'cv2': 'opencv-contrib-python',
    'fastapi': 'fastapi',
    'google': 'google-genai',  # from google import genai (google.auth and google.oauth2 come with it, as google-auth)
    'requests': 'requests',  # the Firestore connection (store/firestore.py); also needed by google-auth
    'cryptography': 'cryptography',  # makes a throwaway key for the Firebase tests (tests/fake_firebase.py); google-auth signs with it
    'mediapipe': 'mediapipe',
    'numpy': 'numpy',
    'pydantic': 'pydantic',
    'starlette': 'starlette',
    'uvicorn': 'uvicorn',
    'pytest': 'pytest',
    'httpx': 'httpx',
}
#: imports that are allowed to be missing from the lists, because the script that uses them says how to install them
OPTIONAL_IMPORTS = frozenset({'playwright'})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    what: str
    sample: str  # the start of what was found, never the whole of it

    def __str__(self) -> str:
        return f'{self.path}:{self.line}: {self.what} ({self.sample})'


# ------------------------------------------------------------------ which files


def is_private(rel: str) -> bool:
    """A file the person keeps their own secrets in. It is never read here."""
    name = rel.rsplit('/', 1)[-1]
    if name == '.env' or (name.startswith('.env.') and name != '.env.example'):
        return True
    return rel.startswith('backend/secrets/') and name != '.gitkeep'


def project_files(root: Path = ROOT, *, skip_dirs: frozenset[str] = SKIP_DIRS) -> list[tuple[Path, str]]:
    """Every file under `root` as (path, name with forward slashes), except what is in a skipped folder. Sorted."""
    found = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(n for n in names if n not in skip_dirs)
        for name in sorted(files):
            path = Path(directory) / name
            found.append((path, path.relative_to(root).as_posix()))
    return found


def read_text(path: Path) -> str | None:
    """The text in a file, or None when it is not text (a picture, a model) or too big to be hand-written."""
    try:
        if path.stat().st_size > BIGGEST_TEXT:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b'\0' in data[:4096]:
        return None
    return data.decode('utf-8', errors='replace')


# ------------------------------------------------------------------ keys


def looks_fake(value: str) -> bool:
    """A value that is plainly an example (the tests need keys that look real, and the README shows where to paste one)."""
    low = value.lower()
    return any(word in low for word in FAKE_WORDS)


def secrets_in(text: str, rel: str) -> list[Finding]:
    """What looks like a secret in one file's text. A line is reported once, under the most specific pattern that fits it."""
    found: dict[int, Finding] = {}
    for what, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1) if pattern.groups else match.group(0)
            line = text.count('\n', 0, match.start()) + 1
            if looks_fake(value) or line in found:
                continue
            found[line] = Finding(rel, line, f'looks like {what}', value[:4] + '...')
    return [found[line] for line in sorted(found)]


def find_secrets(root: Path = ROOT, files: list[tuple[Path, str]] | None = None) -> list[Finding]:
    """Keys and private files left in the project. `files`: look only at these (path, name) pairs, as package.py does."""
    packaging = files is not None
    found = []
    for path, rel in files if files is not None else project_files(root):
        if is_private(rel):
            if packaging:  # a private file is expected in the folder on the person's own computer, but it must never be packaged
                found.append(Finding(rel, 0, 'is a private file and must not be packaged', rel))
            continue
        if path.name in SKIP_FILES:
            continue
        text = read_text(path)
        if text is not None:
            found.extend(secrets_in(text, rel))
    return found


# ------------------------------------------------------------------ keys that were removed but are still in git's history


def check_history(root: Path = ROOT) -> list[str]:
    """A key that was once typed into a file and committed, then deleted again, is gone from the files but not from git: whoever
    gets the repository can read it in the old commits. This looks at every line that was ever added. It does nothing when this
    is not a git folder (a zip has no history) or git cannot be asked, and it never prints more than the start of a key."""
    if not (root / '.git').exists():
        return []
    try:
        log = subprocess.run(
            ['git', 'log', '--all', '-p', '--no-color', '--no-ext-diff', '--format=commit %H'], cwd=root, capture_output=True, timeout=180, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if log.returncode != 0:
        return []
    problems: dict[tuple[str, str], str] = {}
    state = {'commit': '', 'rel': '', 'added': []}

    def flush() -> None:
        rel, added = state['rel'], state['added']
        state['added'] = []
        if not rel or not added:
            return
        if is_private(rel):
            problems.setdefault((rel, 'private'), f'commit {state["commit"][:8]}: {rel} (a private file) was committed once, and git still holds it')
            return
        for found in secrets_in('\n'.join(added), rel):
            problems.setdefault((rel, found.what), f'commit {state["commit"][:8]}: {rel} once held {found.what} ({found.sample}), and git still holds it')

    for line in log.stdout.decode('utf-8', errors='replace').splitlines():
        if line.startswith('commit '):
            flush()
            state['commit'], state['rel'] = line[7:].strip(), ''
        elif line.startswith('+++ '):
            flush()
            name = line[4:].strip()
            state['rel'] = '' if name == '/dev/null' else name.removeprefix('b/')
        elif line.startswith('+') and state['rel']:
            state['added'].append(line[1:])  # type: ignore[attr-defined]
    flush()
    return list(problems.values())


# ------------------------------------------------------------------ what git ignores


def parse_ignore(text: str) -> list[tuple[bool, str]]:
    """The rules of a .gitignore as (is it a "!" rule, pattern). Comments and blank lines are dropped."""
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        negated = line.startswith('!')
        rules.append((negated, line[1:] if negated else line))
    return rules


def rule_matches(pattern: str, rel: str) -> bool:
    """Does one .gitignore pattern cover this file? (The usual rules: a pattern with a slash in it is from the project folder,
    one without matches that name at any depth, a trailing slash means folders only, and a folder covers everything in it.)"""
    only_folders = pattern.endswith('/')
    body = pattern.strip('/')
    anchored = '/' in pattern.rstrip('/')
    parts = rel.split('/')
    for i in range(1, len(parts) + 1):
        is_folder = i < len(parts)
        if only_folders and not is_folder:
            continue
        target = '/'.join(parts[:i]) if anchored else parts[i - 1]
        if fnmatch.fnmatchcase(target, body):
            return True
    return False


def is_ignored(rules: list[tuple[bool, str]], rel: str) -> bool:
    ignored = False
    for negated, pattern in rules:
        if rule_matches(pattern, rel):
            ignored = not negated
    return ignored


def git_says_ignored(root: Path, rel: str) -> bool | None:
    """What git itself says, when this is a git folder and git is installed. None: cannot tell."""
    if not (root / '.git').exists():
        return None
    try:
        return subprocess.run(['git', 'check-ignore', '-q', rel], cwd=root, capture_output=True, timeout=20, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def check_ignored(root: Path = ROOT) -> list[str]:
    path = root / '.gitignore'
    if not path.is_file():
        return ['there is no .gitignore, so nothing keeps keys and photos out of git']
    rules = parse_ignore(path.read_text(encoding='utf-8', errors='replace'))
    problems = []
    for rel in MUST_BE_IGNORED:
        if not is_ignored(rules, rel):
            problems.append(f'.gitignore does not cover {rel}')
    for rel in MUST_NOT_BE_IGNORED:
        if is_ignored(rules, rel):
            problems.append(f'.gitignore hides {rel}, which has to be kept')
    for rel in ('backend/.env', 'test-photos/person1/left.jpg'):  # and what git itself says, when it can say
        if git_says_ignored(root, rel) is False:
            problems.append(f'git does not ignore {rel}')
    return problems


# ------------------------------------------------------------------ exact versions, and nothing forgotten

PIN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]*(?:\[[A-Za-z0-9_,\-]+\])?==[0-9][0-9A-Za-z.\-+!]*$')


def requirement_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.split('#', 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def normal(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def pinned_names(path: Path) -> set[str]:
    return {normal(line.split('==')[0].split('[')[0]) for line in requirement_lines(path) if PIN.match(line)}


#: the package lists, each of which must pin every package to one version. The last one is only for  run.bat evidence  and may be absent.
PACKAGE_LISTS = ('requirements.txt', 'requirements-dev.txt', 'requirements-evidence.txt')
OPTIONAL_LISTS = frozenset({'requirements-evidence.txt'})


def check_pins(root: Path = ROOT) -> list[str]:
    problems = []
    for name in PACKAGE_LISTS:
        path = root / 'backend' / name
        if not path.is_file():
            if name not in OPTIONAL_LISTS:
                problems.append(f'backend/{name} is missing')
            continue
        for line in requirement_lines(path):
            if line.startswith('-r ') or PIN.match(line):
                continue
            problems.append(f'backend/{name}: "{line}" is not pinned to one exact version (name==1.2.3)')
    return problems


def local_modules(root: Path) -> set[str]:
    names = {'app'}
    for folder in (root / 'scripts', root / 'backend' / 'tests'):
        if folder.is_dir():
            names.update(p.stem for p in folder.glob('*.py'))
    return names


def imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except SyntaxError:
        return set()
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split('.')[0])
    return found


def check_imports(root: Path = ROOT) -> list[str]:
    """Every package that the server and the scripts import has to be pinned in requirements.txt (the tests may also use
    requirements-dev.txt). This is what a fresh install would trip over."""
    backend = root / 'backend'
    if not (backend / 'requirements.txt').is_file():
        return ['backend/requirements.txt is missing']
    runtime = pinned_names(backend / 'requirements.txt')
    development = runtime | (pinned_names(backend / 'requirements-dev.txt') if (backend / 'requirements-dev.txt').is_file() else set())
    own = local_modules(root)
    problems = []
    for folder, allowed, label in ((backend / 'app', runtime, 'requirements.txt'), (root / 'scripts', runtime, 'requirements.txt'), (backend / 'tests', development, 'requirements-dev.txt')):
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob('*.py')):
            if SKIP_DIRS & set(path.parts):
                continue
            rel = path.relative_to(root).as_posix()
            for module in sorted(imports_of(path)):
                if module in sys.stdlib_module_names or module in own or module in OPTIONAL_IMPORTS:
                    continue
                package = PROVIDED_BY.get(module)
                if package is None:
                    problems.append(f'{rel} imports "{module}", which repo_checks.py does not know: add it to PROVIDED_BY and to the package list')
                elif normal(package) not in allowed:
                    problems.append(f'{rel} imports "{module}", but {package} is not pinned in {label}')
    return problems


# ------------------------------------------------------------------ all of them


def all_checks(root: Path = ROOT) -> list[tuple[str, list[str]]]:
    """(what was checked, what is wrong) for every check. An empty list means the check passed."""
    history = 'no key is hidden in the version history' + ('' if (root / '.git').exists() else ' (there is no version history here, so nothing to look in)')
    return [
        ('no keys or private files are written in the project', [str(f) for f in find_secrets(root)]),
        (history, check_history(root)),
        ('git ignores the keys, the hand model, the photos and the private environment', check_ignored(root)),
        ('every package is pinned to one exact version', check_pins(root)),
        ('every package the code imports is in the package list', check_imports(root)),
    ]


def main() -> int:
    failed = 0
    checks = all_checks()
    for what, problems in checks:
        print(f'  {"PASS" if not problems else "FAIL"}  {what}')
        for problem in problems:
            print(f'          {problem}')
        failed += bool(problems)
    print()
    print('RESULT: PASS' if not failed else f'RESULT: FAIL ({failed} of {len(checks)} checks)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
