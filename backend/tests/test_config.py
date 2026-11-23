"""Reading backend/.env. The Gemini key lives there, so the one thing that must never happen is a key that is silently ignored
because the file was saved in an unusual way on Windows."""

from __future__ import annotations

import pytest

from app.core.config import load_env_file, read_env_text, read_settings

KEY = 'AIzaSyTestKeyForTheLoaderOnly0123456789'


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Writes bytes to a settings file, clears the variables it may set, and loads the file."""
    for name in ('GEMINI_API_KEY', 'GEMINI_MODEL', 'NOTE_TEST'):
        monkeypatch.delenv(name, raising=False)

    def load(data: bytes):
        path = tmp_path / '.env'
        path.write_bytes(data)
        load_env_file(path)
        return path

    return load


def test_a_plain_file_sets_its_values(env_file, monkeypatch):
    env_file(f'# the key\nGEMINI_API_KEY={KEY}\n\nGEMINI_MODEL = gemini-test\n'.encode())
    assert read_settings().gemini_api_key == KEY
    assert read_settings().gemini_model == 'gemini-test'  # spaces around the equals sign do not matter


def test_a_byte_order_mark_does_not_hide_the_first_setting(env_file):
    # Some Windows editors save "UTF-8 with BOM". Without care the first name becomes "﻿GEMINI_API_KEY" and the key is ignored.
    env_file(b'\xef\xbb\xbf' + f'GEMINI_API_KEY={KEY}\n'.encode())
    assert read_settings().gemini_api_key == KEY


def test_a_file_that_powershell_saved_as_utf16_is_read(env_file):
    # Windows PowerShell's `echo X > file` writes UTF-16 with a mark. Reading it as UTF-8 used to fail or find nothing.
    env_file(f'GEMINI_API_KEY={KEY}\r\n'.encode('utf-16'))
    assert read_settings().gemini_api_key == KEY


def test_windows_line_endings_quotes_and_a_trailing_note_are_all_fine(env_file, monkeypatch):
    env_file(f'GEMINI_API_KEY="{KEY}"\r\nGEMINI_MODEL=gemini-test   # the model I chose\r\nNOTE_TEST=a#b\r\n'.encode())
    settings = read_settings()
    assert settings.gemini_api_key == KEY
    assert settings.gemini_model == 'gemini-test'
    import os

    assert os.environ['NOTE_TEST'] == 'a#b'  # a "#" inside a value (no space before it) is part of the value


def test_a_variable_already_set_wins_over_the_file(env_file, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'from-the-environment')
    env_file(f'GEMINI_API_KEY={KEY}\n'.encode())
    assert read_settings().gemini_api_key == 'from-the-environment'


def test_a_blank_variable_also_wins_so_the_tests_can_never_pick_up_a_real_key(env_file, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', '')
    env_file(f'GEMINI_API_KEY={KEY}\n'.encode())
    assert read_settings().gemini_api_key == ''


def test_a_missing_file_changes_nothing(tmp_path):
    load_env_file(tmp_path / 'not-there.env')  # no error


def test_bytes_that_are_not_text_do_not_stop_the_server_from_starting(tmp_path):
    path = tmp_path / '.env'
    path.write_bytes(b'GEMINI_MODEL=gemini-test\n# caf\xe9 (a Windows-1252 letter)\n')
    assert 'GEMINI_MODEL=gemini-test' in read_env_text(path)
