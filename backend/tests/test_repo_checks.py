"""scripts/repo_checks.py: the checks that keep a key, a photo or a forgotten package out of what a lecturer receives."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'repo_checks.py'

# A key-shaped value that is NOT written out in one piece here, or the check would (rightly) flag this very file.
REAL_LOOKING_KEY = 'AIza' + 'Sy' + 'Dq8Zr3Xk1Lm9Wv2Bn7Ht4Jc6Pf0Gs5Yua'
PRIVATE_KEY_HEAD = '-----BEGIN ' + 'PRIVATE KEY-----'
RSA_KEY_HEAD = '-----BEGIN RSA ' + 'PRIVATE KEY-----'
SERVICE_ACCOUNT = '{"type": ' + '"service_account", "project_id": "x"}'


@pytest.fixture(scope='module')
def rc():
    spec = importlib.util.spec_from_file_location('repo_checks', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['repo_checks'] = module  # a dataclass looks its own module up by name
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop('repo_checks', None)


def make(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return root


# ------------------------------------------------------------------ keys


def test_the_key_used_in_these_tests_looks_real_to_the_check(rc):
    assert len(REAL_LOOKING_KEY) == 39 and not rc.looks_fake(REAL_LOOKING_KEY)


def test_a_google_key_in_any_file_is_found_and_never_printed_whole(rc, tmp_path):
    make(tmp_path, {'src/api/client.ts': f'const key = "{REAL_LOOKING_KEY}"\n', 'src/ok.ts': 'const x = 1\n'})
    [finding] = rc.find_secrets(tmp_path)
    assert finding.path == 'src/api/client.ts' and finding.line == 1 and 'Google API key' in finding.what
    assert REAL_LOOKING_KEY not in str(finding) and finding.sample == 'AIza...'


@pytest.mark.parametrize(
    'name, text, what',
    [
        ('keys/a.pem', PRIVATE_KEY_HEAD + '\nMIIE\n', 'private key'),
        ('keys/b.pem', RSA_KEY_HEAD + '\nMIIE\n', 'private key'),
        ('firebase.json', SERVICE_ACCOUNT, 'service-account'),
        ('notes.md', 'token ghp_' + 'a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s', 'GitHub token'),
        ('notes2.md', 'key sk-' + 'Zx9Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk0Lm9Nb8Vc7', 'secret key'),
        ('settings.txt', 'SOME_SERVICE_API_KEY=q1w2e3r4t5y6u7i8o9p0\n', 'settings line'),
        ('settings2.txt', 'export DB_PASSWORD="Zm9vYmFyYmF6cXV4"\n', 'settings line'),
    ],
)
def test_other_kinds_of_secret_are_found(rc, tmp_path, name, text, what):
    make(tmp_path, {name: text})
    found = rc.find_secrets(tmp_path)
    assert len(found) == 1 and what in found[0].what


def test_examples_and_the_tests_own_fake_keys_are_not_secrets(rc, tmp_path):
    make(
        tmp_path,
        {
            'README.md': 'In backend/.env write:\n\nGEMINI_API_KEY=paste-your-key-here\n',
            'backend/.env.example': 'GEMINI_API_KEY=\nMAX_TOKENS=16384\n',
            'backend/tests/test_x.py': 'KEY = "AIzaSyTestKeyForTheLoaderOnly0123456789"\nOTHER = "AIzaSyD-this-is-not-a-real-key-0123456789"\n',
        },
    )
    assert rc.find_secrets(tmp_path) == []


def test_the_private_environment_file_is_never_read_but_the_example_is(rc, tmp_path):
    make(tmp_path, {'backend/.env': f'GEMINI_API_KEY={REAL_LOOKING_KEY}\n', 'backend/secrets/firebase.json': SERVICE_ACCOUNT})
    assert rc.find_secrets(tmp_path) == []  # these are where the person's keys belong: they are not scanned
    make(tmp_path, {'backend/.env.example': f'GEMINI_API_KEY={REAL_LOOKING_KEY}\n'})
    assert [f.path for f in rc.find_secrets(tmp_path)] == ['backend/.env.example']  # a real key pasted into the example is a leak


def test_a_private_file_in_the_list_for_the_zip_is_a_finding(rc, tmp_path):
    make(tmp_path, {'backend/.env': 'GEMINI_API_KEY=x\n', 'backend/secrets/a.json': '{}', 'backend/secrets/.gitkeep': '', 'README.md': 'hi\n'})
    files = rc.project_files(tmp_path)
    found = rc.find_secrets(tmp_path, files)
    assert sorted(f.path for f in found) == ['backend/.env', 'backend/secrets/a.json']  # the .gitkeep is just a placeholder


def test_pictures_other_people_folders_and_big_files_are_not_read(rc, tmp_path):
    make(
        tmp_path,
        {
            'photo.jpg': b'\xff\xd8\xff\x00' + REAL_LOOKING_KEY.encode(),
            'node_modules/pkg/index.js': f'"{REAL_LOOKING_KEY}"',
            'backend/.venv/lib/x.py': f'"{REAL_LOOKING_KEY}"',
            'dist-server/assets/app.js': f'"{REAL_LOOKING_KEY}"',
            'package-lock.json': f'"{REAL_LOOKING_KEY}"',
            'big.txt': (REAL_LOOKING_KEY + '\n').encode() * 60_000,
        },
    )
    assert rc.find_secrets(tmp_path) == []


# ------------------------------------------------------------------ what git ignores


@pytest.mark.parametrize(
    'pattern, path, hit',
    [
        ('.env', '.env', True),
        ('.env', 'backend/.env', True),  # no slash: that name at any depth
        ('backend/.env', 'backend/.env', True),
        ('backend/.env', 'other/backend/.env', False),  # a slash: from the project folder only
        ('.env.*', '.env.local', True),
        ('.env.*', '.env.example', True),  # a "!" rule after it takes it back
        ('node_modules', 'node_modules/react/index.js', True),  # a folder covers everything in it
        ('test-photos/', 'test-photos/person1/left.jpg', True),
        ('test-photos/', 'test-photos', False),  # a trailing slash means folders only
        ('backend/secrets/*', 'backend/secrets/key.json', True),
        ('backend/secrets/*', 'backend/secrets/a/b.json', True),
        ('*.log', 'logs/server.log', True),
        ('*.log', 'README.md', False),
        ('debug/', 'debug/summary.txt', True),
        ('debug/', 'src/debug.ts', False),
    ],
)
def test_a_gitignore_rule_covers_what_git_would_cover(rc, pattern, path, hit):
    assert rc.rule_matches(pattern, path) is hit


def test_a_later_rule_can_take_a_file_back(rc):
    rules = rc.parse_ignore('# keys\n.env\n.env.*\n!.env.example\n\nbackend/secrets/*\n!backend/secrets/.gitkeep\n')
    assert rc.is_ignored(rules, 'backend/.env') and rc.is_ignored(rules, 'backend/secrets/a.json')
    assert not rc.is_ignored(rules, '.env.example') and not rc.is_ignored(rules, 'backend/secrets/.gitkeep')


def test_a_project_without_the_right_ignore_rules_is_told_what_is_open(rc, tmp_path):
    assert 'no .gitignore' in rc.check_ignored(tmp_path)[0]
    make(tmp_path, {'.gitignore': 'node_modules\n'})
    problems = rc.check_ignored(tmp_path)
    assert 'backend/.env' in ' '.join(problems) and 'test-photos/person1/left.jpg' in ' '.join(problems) and 'debug/summary.txt' in ' '.join(problems)


def test_ignoring_too_much_is_also_a_problem(rc, tmp_path):
    make(tmp_path, {'.gitignore': (ROOT / '.gitignore').read_text() + '\nscripts/\n'})
    assert any('scripts/serve.py' in p and 'has to be kept' in p for p in rc.check_ignored(tmp_path))


@pytest.mark.skipif(shutil.which('git') is None, reason='git is not installed here')
def test_what_git_itself_says_is_checked_when_the_folder_is_a_git_folder(rc, tmp_path):
    make(tmp_path, {'.gitignore': '.env\n', 'backend/x.txt': 'x'})
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    assert rc.git_says_ignored(tmp_path, 'backend/.env') is True and rc.git_says_ignored(tmp_path, 'backend/x.txt') is False
    assert rc.git_says_ignored(tmp_path / 'backend', 'x') is None  # not a git folder on its own: cannot tell
    assert any('git does not ignore test-photos/person1/left.jpg' in p for p in rc.check_ignored(tmp_path))


# ------------------------------------------------------------------ exact versions, and nothing forgotten


def test_a_package_that_is_not_pinned_is_named(rc, tmp_path):
    make(tmp_path, {'backend/requirements.txt': 'fastapi==0.1.2\nnumpy>=2\n# a comment\n\nrequests\n', 'backend/requirements-dev.txt': '-r requirements.txt\npytest==9.2.0  # tests\n'})
    problems = rc.check_pins(tmp_path)
    assert len(problems) == 2 and 'numpy>=2' in problems[0] and '"requests"' in problems[1]


def test_a_missing_package_list_is_a_problem(rc, tmp_path):
    assert any('requirements.txt is missing' in p for p in rc.check_pins(tmp_path))
    assert rc.check_imports(tmp_path) == ['backend/requirements.txt is missing']


def test_the_list_for_the_screenshots_is_held_to_exact_versions_too_but_may_be_absent(rc, tmp_path):
    make(tmp_path, {'backend/requirements.txt': 'fastapi==0.1.2\n', 'backend/requirements-dev.txt': '-r requirements.txt\npytest==9.2.0\n'})
    assert rc.check_pins(tmp_path) == []
    make(tmp_path, {'backend/requirements-evidence.txt': '-r requirements.txt\nplaywright>=1.50\ngreenlet==3.5.6\n'})
    problems = rc.check_pins(tmp_path)
    assert len(problems) == 1 and 'requirements-evidence.txt' in problems[0] and 'playwright>=1.50' in problems[0]


def test_the_real_list_for_the_screenshots_pins_playwright_and_what_it_needs():
    lines = [line.split('#')[0].strip() for line in (SCRIPT.parents[1] / 'backend' / 'requirements-evidence.txt').read_text(encoding='utf-8').splitlines()]
    pins = dict(line.split('==') for line in lines if '==' in line)
    assert '-r requirements.txt' in lines
    assert set(pins) == {'playwright', 'greenlet', 'pyee'}


def tree(tmp_path: Path, runtime: str, dev: str = '-r requirements.txt\npytest==9.2.0\n', **files: str) -> Path:
    base = {'backend/requirements.txt': runtime, 'backend/requirements-dev.txt': dev, 'backend/app/__init__.py': ''}
    base.update({rel.replace('__', '/'): text for rel, text in files.items()})
    return make(tmp_path, base)


def test_an_import_whose_package_is_not_in_the_list_is_found(rc, tmp_path):
    tree(tmp_path, 'fastapi==0.1.2\n', **{'backend__app__main.py': 'import fastapi\nimport numpy as np\nfrom cv2 import imread\n'})
    problems = rc.check_imports(tmp_path)
    assert len(problems) == 2
    assert 'imports "cv2", but opencv-contrib-python is not pinned' in problems[0] or 'imports "cv2"' in problems[0]
    assert any('"numpy"' in p for p in problems)


def test_the_standard_library_the_projects_own_modules_and_optional_ones_are_fine(rc, tmp_path):
    tree(
        tmp_path,
        'fastapi==0.1.2\n',
        **{
            'backend__app__main.py': 'import os, json\nfrom pathlib import Path\nfrom app.core import x\nfrom . import y\nimport fastapi\n',
            'scripts__tool.py': 'import tool_helper\nfrom playwright.sync_api import sync_playwright\n',
            'scripts__tool_helper.py': 'import sys\n',
        },
    )
    assert rc.check_imports(tmp_path) == []


def test_an_import_nobody_has_listed_is_a_problem_to_look_at(rc, tmp_path):
    tree(tmp_path, 'fastapi==0.1.2\n', **{'scripts__tool.py': 'import something_new\n'})
    [problem] = rc.check_imports(tmp_path)
    assert '"something_new"' in problem and 'PROVIDED_BY' in problem


def test_tests_may_use_what_only_the_dev_list_pins(rc, tmp_path):
    tree(tmp_path, 'fastapi==0.1.2\n', **{'backend__tests__test_x.py': 'import pytest\nimport fastapi\n'})
    assert rc.check_imports(tmp_path) == []
    tree(tmp_path, 'fastapi==0.1.2\n', dev='-r requirements.txt\n', **{'backend__tests__test_x.py': 'import pytest\n'})
    assert any('pytest is not pinned in requirements-dev.txt' in p for p in rc.check_imports(tmp_path))


def test_an_underscore_or_a_capital_in_a_package_name_makes_no_difference(rc, tmp_path):
    tree(tmp_path, 'Google_GenAI==1.0\n', **{'backend__app__x.py': 'from google import genai\n'})
    assert rc.check_imports(tmp_path) == []


# ------------------------------------------------------------------ keys that were removed but are still in git's history

needs_git = pytest.mark.skipif(shutil.which('git') is None, reason='git is not installed')


def git(root: Path, *args: str) -> None:
    subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false', *args], cwd=root, check=True, capture_output=True)


def commit(root: Path, message: str) -> None:
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', message)


def test_a_folder_without_a_history_has_nothing_to_look_in(rc, tmp_path):
    make(tmp_path, {'src/config.ts': f'export const key = "{REAL_LOOKING_KEY}"\n'})
    assert rc.check_history(tmp_path) == []  # (the key itself is found by the other check)
    assert len(rc.find_secrets(tmp_path)) == 1


@needs_git
def test_a_key_that_was_committed_and_removed_is_still_found_in_the_history_and_never_printed_whole(rc, tmp_path):
    git(tmp_path, 'init', '-q')
    make(tmp_path, {'src/config.ts': f'export const key = "{REAL_LOOKING_KEY}"\n'})
    commit(tmp_path, 'oops')
    make(tmp_path, {'src/config.ts': 'export const key = ""\n'})
    commit(tmp_path, 'remove it')
    assert rc.find_secrets(tmp_path) == []  # the files are clean now
    [problem] = rc.check_history(tmp_path)
    assert 'src/config.ts' in problem and 'Google API key' in problem and 'AIza...' in problem and 'git still holds it' in problem
    assert REAL_LOOKING_KEY not in problem and REAL_LOOKING_KEY[:10] not in problem


@needs_git
def test_the_same_key_added_again_and_again_is_reported_once(rc, tmp_path):
    git(tmp_path, 'init', '-q')
    for text in (f'k = "{REAL_LOOKING_KEY}"\n', 'k = ""\n', f'k = "{REAL_LOOKING_KEY}"\n', 'k = ""\n'):
        make(tmp_path, {'a.py': text})
        commit(tmp_path, 'edit')
    assert len(rc.check_history(tmp_path)) == 1


@needs_git
def test_a_private_file_that_was_committed_once_is_reported_even_if_it_is_gone_now(rc, tmp_path):
    git(tmp_path, 'init', '-q')
    make(tmp_path, {'backend/.env': 'GEMINI_API_KEY=something-typed-by-hand\n', 'README.md': 'hello\n'})
    commit(tmp_path, 'add everything')
    (tmp_path / 'backend' / '.env').unlink()
    commit(tmp_path, 'take it out')
    [problem] = rc.check_history(tmp_path)
    assert 'backend/.env' in problem and 'private file' in problem and 'something-typed-by-hand' not in problem


@needs_git
def test_a_history_of_examples_and_ordinary_edits_passes(rc, tmp_path):
    git(tmp_path, 'init', '-q')
    make(tmp_path, {'.env.example': 'GEMINI_API_KEY=paste-your-key-here\n', 'a.py': 'x = 1\n', 'b.bin': bytes(range(256))})
    commit(tmp_path, 'first')
    make(tmp_path, {'a.py': 'x = 2  # ++ not a header\n+++ nor this line\n'})
    commit(tmp_path, 'second')
    assert rc.check_history(tmp_path) == []


@needs_git
def test_a_key_on_another_branch_is_found_too(rc, tmp_path):
    git(tmp_path, 'init', '-q')
    make(tmp_path, {'a.py': 'x = 1\n'})
    commit(tmp_path, 'first')
    git(tmp_path, 'checkout', '-q', '-b', 'side')
    make(tmp_path, {'b.py': f'k = "{REAL_LOOKING_KEY}"\n'})
    commit(tmp_path, 'on the side')
    git(tmp_path, 'checkout', '-q', '-')
    assert len(rc.check_history(tmp_path)) == 1


def test_git_that_cannot_be_asked_is_not_a_failure(rc, tmp_path, monkeypatch):
    (tmp_path / '.git').mkdir()

    def no_git(*args, **kwargs):
        raise FileNotFoundError('git')

    monkeypatch.setattr(rc.subprocess, 'run', no_git)
    assert rc.check_history(tmp_path) == []


@needs_git
def test_a_git_folder_that_is_not_a_repository_is_not_a_failure(rc, tmp_path):
    (tmp_path / '.git').mkdir()
    assert rc.check_history(tmp_path) == []


def test_the_list_of_checks_says_whether_there_is_a_history_to_look_in(rc, tmp_path):
    without = [what for what, _ in rc.all_checks(tmp_path) if 'history' in what]
    assert without == ['no key is hidden in the version history (there is no version history here, so nothing to look in)']
    (tmp_path / '.git').mkdir()
    assert [what for what, _ in rc.all_checks(tmp_path) if 'history' in what] == ['no key is hidden in the version history']


# ------------------------------------------------------------------ this project


def test_this_project_passes_every_check(rc):
    for what, problems in rc.all_checks(ROOT):
        assert problems == [], f'{what}: {problems}'


def test_the_command_line_says_pass_for_this_project(rc, capsys):
    assert rc.main() == 0
    out = capsys.readouterr().out
    assert out.count('PASS') == 6 and out.strip().endswith('RESULT: PASS')  # five lines and the result
