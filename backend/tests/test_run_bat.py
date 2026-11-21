"""run.bat is the one file a lecturer double-clicks, and Windows is unforgiving about it: a bare line feed can break a label or a goto, a letter
with an accent can turn into something else, and a command that points at a script that is not there only fails on their computer.
These tests read the file as it is."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BAT = ROOT / 'run.bat'
SCRIPTS = ROOT / 'scripts'

#: scripts that run.bat starts with the Python it finds on the computer, before any package is installed
SYSTEM_PYTHON = re.compile(r'^%PY% scripts\\([a-z_]+)\.py', re.MULTILINE)
#: scripts that run.bat starts inside the private environment, where the packages are
VENV_PYTHON = re.compile(r'^"backend\\\.venv\\Scripts\\python\.exe" scripts\\([a-z_]+)\.py', re.MULTILINE)


@pytest.fixture(scope='module')
def raw() -> bytes:
    return BAT.read_bytes()


@pytest.fixture(scope='module')
def text(raw) -> str:
    return raw.decode('utf-8')


def test_every_line_ends_the_windows_way_and_nothing_but_plain_letters_is_in_it(raw):
    assert raw.count(b'\n') == raw.count(b'\r\n') and raw.endswith(b'\r\n')
    assert raw.isascii()  # a command window reads the file in the computer's own code page


def test_git_is_told_to_keep_it_that_way():
    assert '*.bat text eol=crlf' in (ROOT / '.gitattributes').read_text(encoding='utf-8')


def test_every_goto_has_its_label_and_every_word_has_the_label_of_its_name(text):
    labels = set(re.findall(r'^:([a-z]+)\s*$', text, re.MULTILINE))
    jumps = re.findall(r'goto :([a-z]+)', text)
    assert jumps and set(jumps) <= labels
    for word, label in re.findall(r'if /i "%~1"=="([a-z]+)" goto :([a-z]+)', text):
        assert word == label
    assert len(labels) == len(re.findall(r'^:[a-z]+\s*$', text, re.MULTILINE))  # no label twice


def test_every_command_in_the_header_is_there_and_the_other_way_round(text):
    # "rem    run.bat <word>    what it does" (the first line, plain run.bat, has no word and is not matched)
    words = {m.group(1) for line in text.splitlines() if (m := re.match(r'rem {4}run\.bat +(\S+) {2,}', line))}
    words_that_start_something = {w for w in words if not w.startswith('--')}
    in_the_file = set(re.findall(r'if /i "%~1"=="([a-z]+)"', text))
    assert words_that_start_something == in_the_file
    assert {'preflight', 'package', 'fresh'} <= in_the_file
    serve = (SCRIPTS / 'serve.py').read_text(encoding='utf-8')
    for option in words - words_that_start_something:
        assert f"'{option}'" in serve, f'run.bat says {option} but serve.py does not know it'


def test_every_script_it_starts_is_there(text):
    started = set(SYSTEM_PYTHON.findall(text)) | set(VENV_PYTHON.findall(text))
    assert started >= {'serve', 'smoke', 'fetch_models', 'contact_sheet', 'check_gemini', 'live_report', 'preflight', 'package', 'fresh_copy'}
    for name in started:
        assert (SCRIPTS / f'{name}.py').is_file(), name


def test_every_target_gives_back_the_exit_code_of_what_it_ran(text):
    for body in re.split(r'^:[a-z]+\s*$', text, flags=re.MULTILINE)[1:]:
        assert body.rstrip().endswith('exit /b %CODE%') or body.rstrip().endswith('exit /b 1')
        assert 'pause' in body  # the window stays open, so that the message can be read


def top_level_imports(path: Path) -> set[str]:
    names = set()
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Import):
            names |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split('.')[0])
    return names


def test_what_runs_before_the_packages_are_installed_uses_nothing_but_python_itself(text):
    """The first thing a lecturer runs is run.bat, and the packages are not there yet: these scripts may import only what
    comes with Python, and each other."""
    siblings = {p.stem for p in SCRIPTS.glob('*.py')}
    for name in sorted(set(SYSTEM_PYTHON.findall(text))):
        outside = {m for m in top_level_imports(SCRIPTS / f'{name}.py') if m not in sys.stdlib_module_names and m not in siblings and m != '__future__'}
        assert not outside, f'scripts/{name}.py is started with the computer\'s own Python, and imports {sorted(outside)}'
    # and what they import from each other must hold to the same rule
    for name in sorted(set(SYSTEM_PYTHON.findall(text))):
        for sibling in top_level_imports(SCRIPTS / f'{name}.py') & siblings:
            outside = {m for m in top_level_imports(SCRIPTS / f'{sibling}.py') if m not in sys.stdlib_module_names and m not in siblings}
            assert not outside, f'scripts/{name}.py imports scripts/{sibling}.py, which imports {sorted(outside)}'
