"""Test setup: a fresh server (no data, no pauses between steps) for every test, and a way to make more browsers."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

warnings.filterwarnings('ignore', category=DeprecationWarning)

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def never_reach_google(monkeypatch):
    """No test may reach Google, whatever is in backend/.env. The key is blanked in the environment (a variable that is already
    set, even to nothing, is never overridden by the file), and making a real Gemini client fails loudly. Tests use fake_gemini.py.
    A test that tried anyway fails at the end, even if the app swallowed the error and carried on with the fixed wording."""
    monkeypatch.setenv('GEMINI_API_KEY', '')
    monkeypatch.setenv('STORAGE', 'memory')  # and no test may write to a real database, even with a Firebase key in backend/secrets
    attempts: list[int] = []
    try:
        from google import genai
    except ImportError:  # the library is only needed once a key is set
        yield attempts
        return

    def refuse(*args, **kwargs):
        attempts.append(1)
        raise AssertionError('a test tried to create a real Gemini client; use tests/fake_gemini.py instead')

    monkeypatch.setattr(genai, 'Client', refuse)
    yield attempts
    assert not attempts, 'a test tried to create a real Gemini client; use tests/fake_gemini.py instead'


@pytest.fixture(autouse=True)
def never_wait_to_retry(monkeypatch):
    """A call that repeats after a temporary Gemini failure waits a few seconds in real life; in a test it must not wait at all."""
    from app.llm import gemini

    monkeypatch.setattr(gemini, 'RETRY_WAIT', 0.0)


@pytest.fixture
def site_dir(tmp_path):
    """A tiny built website."""
    root = tmp_path / 'dist'
    (root / 'assets').mkdir(parents=True)
    (root / 'index.html').write_text('<!doctype html><title>Kiro AI</title><div id="root"></div>')
    (root / 'assets' / 'app-123.js').write_text('console.log("hi")')
    (root / 'favicon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    return root


@pytest.fixture
def settings(site_dir):
    return Settings(env='test', site_dir=site_dir, stage_pause_ms=0)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    """One browser: it keeps its own cookies."""
    return TestClient(app)


@pytest.fixture
def browser(app):
    """Makes more browsers on the same server, each with its own cookies (one per person)."""

    def make() -> TestClient:
        return TestClient(app)

    return make
