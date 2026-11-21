"""scripts/serve.py, the part that decides whether the website has to be built again. A computer that has no Node.js must still start
the app from a zip that carries the built website, so the answer may not depend on file dates (copying and unzipping change them)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'serve.py'


@pytest.fixture
def serve(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('serve_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    site = tmp_path / 'dist-server'
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'SITE', site)
    monkeypatch.setattr(module, 'SITE_STAMP', site / 'source.sha256')
    for rel, text in {
        'index.html': '<html></html>\n',
        'package.json': '{"name": "x"}\n',
        'src/App.tsx': 'export default 1\n',
        'src/lib/a.ts': 'export const a = 1\n',
        'public/logo.svg': '<svg/>\n',
    }.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(text.encode())
    return module


def build(serve, text: str = '<html>built</html>') -> None:
    """What `npm run build:server` and then serve.py leave behind."""
    serve.SITE.mkdir(parents=True, exist_ok=True)
    (serve.SITE / 'index.html').write_text(text)
    serve.SITE_STAMP.write_text(serve.source_stamp() + '\n')


class NoNode:
    """shutil.which for a computer with no Node.js."""

    def __call__(self, name):
        return None


# ------------------------------------------------------------------ is the build current


def test_there_is_no_current_site_before_the_first_build(serve):
    assert serve.site_is_current() is False


def test_a_build_made_from_these_sources_is_current(serve):
    build(serve)
    assert serve.site_is_current() is True


def test_file_dates_make_no_difference(serve, tmp_path):
    build(serve)
    later = time.time() + 86_400
    for path in serve.source_files():  # as after unzipping: every source looks newer than the build
        os.utime(path, (later, later))
    assert serve.site_is_current() is True
    earlier = time.time() - 86_400 * 30
    os.utime(serve.SITE / 'index.html', (earlier, earlier))
    assert serve.site_is_current() is True


def test_line_endings_make_no_difference(serve, tmp_path):
    build(serve)
    path = tmp_path / 'src' / 'App.tsx'
    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))  # what Git on Windows does to a text file
    assert serve.site_is_current() is True


@pytest.mark.parametrize('change', ['edit', 'add', 'remove', 'rename', 'package', 'env'])
def test_any_change_to_what_the_site_is_built_from_makes_the_build_out_of_date(serve, tmp_path, change):
    build(serve)
    if change == 'edit':
        (tmp_path / 'src' / 'App.tsx').write_text('export default 2\n')
    elif change == 'add':
        (tmp_path / 'src' / 'new.ts').write_text('export {}\n')
    elif change == 'remove':
        (tmp_path / 'public' / 'logo.svg').unlink()
    elif change == 'rename':
        (tmp_path / 'src' / 'lib' / 'a.ts').rename(tmp_path / 'src' / 'lib' / 'b.ts')
    elif change == 'package':
        (tmp_path / 'package.json').write_text('{"name": "y"}\n')
    else:
        (tmp_path / '.env.local').write_text('VITE_GUEST_SESSION_MINUTES=1\n')
    assert serve.site_is_current() is False


def test_a_build_from_before_the_fingerprint_existed_counts_as_out_of_date(serve):
    serve.SITE.mkdir()
    (serve.SITE / 'index.html').write_text('<html>old</html>')
    assert serve.site_is_current() is False


def test_the_fingerprint_does_not_look_at_what_the_site_is_not_built_from(serve, tmp_path):
    before = serve.source_stamp()
    (tmp_path / 'README.md').write_text('# hello\n')
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend' / 'x.py').write_text('x = 1\n')
    (tmp_path / 'node_modules').mkdir()
    (tmp_path / 'node_modules' / 'm.js').write_text('1')
    assert serve.source_stamp() == before


# ------------------------------------------------------------------ building, or not


def test_a_current_build_is_used_without_any_node(serve, monkeypatch, capsys):
    build(serve)
    monkeypatch.setattr(serve.shutil, 'which', NoNode())
    monkeypatch.setattr(serve.subprocess, 'run', lambda *a, **k: pytest.fail('nothing should be run for a build that is current'))
    assert serve.build_site(False) == 0
    assert 'already built and up to date' in capsys.readouterr().out


def test_without_node_an_out_of_date_build_is_used_and_it_says_so(serve, tmp_path, monkeypatch, capsys):
    build(serve)
    (tmp_path / 'src' / 'App.tsx').write_text('export default 3\n')
    monkeypatch.setattr(serve.shutil, 'which', NoNode())
    assert serve.build_site(False) == 0
    assert 'older build of the website will be used' in capsys.readouterr().out
    assert serve.site_is_current() is False  # the stamp was not touched: it still tells the truth


def test_without_node_and_without_any_build_it_says_what_to_install(serve, monkeypatch, capsys):
    monkeypatch.setattr(serve.shutil, 'which', NoNode())
    assert serve.build_site(False) == 1
    out = capsys.readouterr().out
    assert 'Node.js is needed once' in out and 'nodejs.org' in out


def fake_npm(serve, monkeypatch, *, code: int = 0):
    """Node is there; `npm run build:server` writes a site (or fails with `code`). Returns the commands that were run."""
    ran: list[list[str]] = []
    monkeypatch.setattr(serve.shutil, 'which', lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr(serve, 'node_version', lambda node: (22, 0))
    monkeypatch.setattr(serve, 'needs_npm_install', lambda: False)

    def run(cmd, **kwargs):
        ran.append(list(cmd))
        if code == 0 and cmd[1:3] == ['run', 'build:server']:
            serve.SITE.mkdir(parents=True, exist_ok=True)
            (serve.SITE / 'index.html').write_text('<html>new</html>')
        return subprocess.CompletedProcess(cmd, code)

    monkeypatch.setattr(serve.subprocess, 'run', run)
    return ran


def test_a_finished_build_is_stamped_so_it_counts_as_current(serve, monkeypatch):
    ran = fake_npm(serve, monkeypatch)
    assert serve.build_site(False) == 0
    assert ran == [['/usr/bin/npm', 'run', 'build:server']]
    assert serve.site_is_current() is True


def test_a_failed_build_keeps_the_older_site_and_does_not_stamp_it(serve, tmp_path, monkeypatch, capsys):
    build(serve, '<html>older</html>')
    (tmp_path / 'src' / 'App.tsx').write_text('export default 4\n')
    fake_npm(serve, monkeypatch, code=1)
    assert serve.build_site(False) == 0
    assert 'The build failed, so the older build of the website will be used' in capsys.readouterr().out
    assert (serve.SITE / 'index.html').read_text() == '<html>older</html>' and serve.site_is_current() is False


def test_a_failed_first_build_stops_with_a_message(serve, monkeypatch, capsys):
    fake_npm(serve, monkeypatch, code=1)
    assert serve.build_site(False) == 1
    assert 'The website build failed' in capsys.readouterr().out


def test_rebuild_builds_again_even_when_the_site_is_current(serve, monkeypatch):
    build(serve)
    ran = fake_npm(serve, monkeypatch)
    assert serve.build_site(True) == 0
    assert ran == [['/usr/bin/npm', 'run', 'build:server']]


def test_no_build_uses_the_site_as_it_is(serve, monkeypatch, capsys):
    monkeypatch.setattr(serve, 'inside_project_venv', lambda: True)
    monkeypatch.setattr(serve, 'packages_ready', lambda: True)
    monkeypatch.setattr(serve, 'build_site', lambda force: pytest.fail('--no-build must not build'))
    assert serve.main(['--no-build', '--prepare-only']) == 0
    assert 'used as it is' in capsys.readouterr().out


# ------------------------------------------------------------------ what the start-up window says about where accounts are kept


@pytest.fixture
def storage_env(monkeypatch, tmp_path):
    """Points the settings at a key file in a temporary folder (the real backend/secrets is never looked at)."""
    key = tmp_path / 'secrets' / 'firebase-service-account.json'
    monkeypatch.setenv('FIREBASE_KEY', str(key))

    def use(storage: str) -> Path:
        monkeypatch.setenv('STORAGE', storage)
        return key

    return use


def window_text(serve, capsys) -> str:
    serve.say_storage_mode()
    return ' '.join(capsys.readouterr().out.split())


def test_the_window_says_firestore_and_the_project_when_the_key_can_be_used(serve, capsys, storage_env):
    from fake_firebase import PROJECT, private_key_text, write_key_file

    write_key_file(storage_env('auto'))
    text = window_text(serve, capsys)
    assert f'Storage: FIRESTORE (Firebase project {PROJECT})' in text and 'never photos' in text and 'run.bat firebase' in text
    assert private_key_text().split()[3] not in text and 'PRIVATE KEY' not in text  # [3]: the first line of the key itself


def test_the_window_says_memory_when_there_is_no_key_or_storage_memory(serve, capsys, storage_env):
    storage_env('auto')
    assert 'Storage: MEMORY. Accounts last until this window closes' in window_text(serve, capsys)
    storage_env('memory')
    assert 'Storage: MEMORY (STORAGE=memory' in window_text(serve, capsys)


def test_the_window_warns_about_a_key_that_cannot_be_used(serve, capsys, storage_env):
    from fake_firebase import write_key_file

    key = storage_env('firestore')
    assert 'STORAGE=firestore, but there is no Firebase key' in window_text(serve, capsys)
    write_key_file(key, private_key='cut short')
    assert 'STORAGE=firestore, but the Firebase key cannot be used' in window_text(serve, capsys)
    storage_env('auto')
    text = window_text(serve, capsys)
    assert 'Storage: MEMORY, because the Firebase key cannot be used' in text and 'cannot be read' in text
