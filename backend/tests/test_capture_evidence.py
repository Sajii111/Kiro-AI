"""scripts/capture_evidence.py, which takes the screenshots for the report with a real browser going through the real app. The browser part is
run for real by `run.bat evidence` (and was rehearsed against the real app); here are the pieces around it: the names of the pictures, the
list of them, what a rerun may delete, the wrong files it makes, which browser it tries first, and what it refuses to do."""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
ROOT = SCRIPTS.parent


@pytest.fixture(scope='module')
def ce():
    spec = importlib.util.spec_from_file_location('capture_evidence_under_test', SCRIPTS / 'capture_evidence.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['capture_evidence_under_test'] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop('capture_evidence_under_test', None)


def test_playwright_is_only_imported_when_the_pictures_are_taken():
    """The tests, the code check and a computer without Playwright must all be able to load the script."""
    tree = ast.parse((SCRIPTS / 'capture_evidence.py').read_text(encoding='utf-8'))
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            top.add(node.module.split('.')[0])
    assert 'playwright' not in top


def test_the_script_is_plain_ascii_so_a_windows_console_cannot_garble_it():
    assert (SCRIPTS / 'capture_evidence.py').read_bytes().isascii()


def test_names_of_pictures_are_numbered_per_group_and_safe(ce, tmp_path):
    album = ce.Album(tmp_path)
    assert album.reserve('person1', 'upload-empty') == (1, 'person1-01-upload-empty.png')
    assert album.reserve('person1', 'Step: CLAHE contrast / left') == (2, 'person1-02-step-clahe-contrast-left.png')
    assert album.reserve('bad-blurry', 'photos-checked') == (1, 'bad-blurry-01-photos-checked.png')
    for name in ('person1-01-upload-empty.png', 'person1-02-step-clahe-contrast-left.png', 'bad-blurry-01-photos-checked.png'):
        assert ce.OWN_NAME.match(name)


@pytest.mark.parametrize(
    ('text', 'expected'),
    [('Gaussian smoothing', 'gaussian-smoothing'), ('  What does my heart line say?  ', 'what-does-my-heart-line-say'), ('***', 'x'), ('Ünïcode name', 'n-code-name')],
)
def test_slug_keeps_letters_digits_and_single_dashes(ce, text, expected):
    assert ce.slug(text) == expected


def test_a_long_slug_is_cut_without_a_dash_at_the_end(ce):
    out = ce.slug('a' * 30 + ' ' + 'b' * 30, limit=31)
    assert out == 'a' * 30 and not out.endswith('-')


def test_short_keeps_the_first_line_and_cuts_a_long_one(ce):
    assert ce.short(RuntimeError('\n  first line\nsecond line')) == 'first line'
    assert ce.short(RuntimeError('')) == 'RuntimeError'
    long = ce.short(RuntimeError('x' * 500))
    assert len(long) == 160 and long.endswith('...')


def test_edge_is_tried_first_on_windows_and_a_chosen_browser_alone(ce):
    assert ce.browser_order('auto', windows=True) == ['msedge', 'chrome', 'chromium']
    assert ce.browser_order('auto', windows=False)[0] == 'chromium'
    assert ce.browser_order('chrome', windows=True) == ['chrome']


@pytest.mark.parametrize(('name', 'side'), [('bad_blurry.jpg', 'left'), ('dark-right.jpg', 'right'), ('blur_left_right.jpg', 'left'), ('RIGHT_dark.png', 'right')])
def test_a_photo_meant_to_fail_goes_into_the_slot_its_name_says(ce, name, side):
    assert ce.hand_for(Path(name)) == side


def test_the_first_person_gets_every_question_and_the_others_two(ce):
    assert ce.questions_for(0, 7) == ce.QUESTIONS
    assert ce.questions_for(1, 7) == ce.QUESTIONS[:2]
    assert ce.questions_for(2, 1) == ce.QUESTIONS[:1]
    assert ce.questions_for(0, 0) == ()
    # five that are answered from the reading, then two that the app must decline
    assert len(ce.QUESTIONS) == 7 and ce.QUESTIONS[5:] == ('Will I get married?', 'Should I quit my job?')


@pytest.mark.parametrize(
    ('folder', 'person', 'expected'),
    [('person1', 0, 'Person1'), ('person_2', 1, 'Person 2'), ('anna-maria', 2, 'Anna-maria'), ('___', 3, 'Person 4'), ('0771234567', 0, 'Person 1')],
)
def test_profile_names_are_ones_the_website_accepts(ce, folder, person, expected):
    name = ce.profile_name(folder, person)
    assert name == expected
    # the website's own rule (src/lib/validate.ts): letters, digits, spaces, apostrophes, dots and dashes; at most 24; no phone numbers
    assert re.fullmatch(r"[A-Za-z0-9 '.-]+", name) and len(name) <= 24 and not re.search(r'\d{5,}', name)


def test_a_very_long_folder_name_is_cut_to_24_characters(ce):
    assert len(ce.profile_name('a really very long folder name indeed', 0)) <= 24


def test_the_wrong_files_are_a_text_file_named_jpg_a_heic_photo_and_one_over_15_mb(ce, tmp_path):
    made = ce.make_wrong_files(tmp_path / 'wrong')
    assert [key for key, _, _ in made] == ['corrupt-file', 'heic-photo', 'too-large']
    corrupt, heic, large = (path for _, path, _ in made)
    assert corrupt.suffix == '.jpg' and not corrupt.read_bytes().startswith(b'\xff\xd8')
    assert heic.suffix == '.heic' and b'ftypheic' in heic.read_bytes()[:16]
    assert large.suffix == '.jpg' and large.stat().st_size > 15 * 1024 * 1024
    assert all(path.parent == tmp_path / 'wrong' for _, path, _ in made)


def test_a_rerun_takes_away_only_what_the_run_before_made(ce, tmp_path):
    album = ce.Album(tmp_path)
    for key in ('upload-empty', 'photos-checked'):
        number, name = album.reserve('person1', key)
        (tmp_path / name).write_bytes(b'png')
        album.shots.append(ce.Shot('person1', number, key, 'caption', name))
    (tmp_path / ce.INDEX).write_text('index', encoding='utf-8')
    ce.write_manifest(album)
    mine = tmp_path / 'my-own-notes.docx'
    mine.write_bytes(b'the author')
    looks_like_ours_but_not_listed = tmp_path / 'person2-01-upload-empty.png'
    looks_like_ours_but_not_listed.write_bytes(b'png')
    assert ce.clear_previous(tmp_path) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([ce.MANIFEST, mine.name, looks_like_ours_but_not_listed.name])


def test_a_manifest_that_names_other_files_or_is_broken_deletes_nothing(ce, tmp_path):
    (tmp_path / 'report.docx').write_bytes(b'x')
    (tmp_path / ce.MANIFEST).write_text('{"files": ["report.docx", "../outside.png", "person1-01-x.png"]}', encoding='utf-8')
    assert ce.previous_files(tmp_path) == []
    (tmp_path / ce.MANIFEST).write_text('not json', encoding='utf-8')
    assert ce.previous_files(tmp_path) == []
    (tmp_path / ce.MANIFEST).unlink()
    assert ce.clear_previous(tmp_path) == 0


def test_the_index_lists_every_picture_with_what_it_shows_and_why_one_is_missing(ce, tmp_path):
    album = ce.Album(tmp_path)
    album.titles['person1'] = 'person1: a pair of real palms'
    album.note('person1', 'Left photo (left.jpg): This photo looks good.')
    album.shots.append(ce.Shot('person1', 1, 'upload-empty', 'The upload page <b>bold</b>', 'person1-01-upload-empty.png'))
    album.shots.append(ce.Shot('person1', 2, 'reading-top', 'The reading page', None, 'Timeout 30000ms exceeded'))
    page = ce.index_html(album, [('Taken', 'today'), ('Browser', 'Microsoft Edge')])
    assert 'person1-01-upload-empty.png' in page and 'The upload page &lt;b&gt;bold&lt;/b&gt;' in page and '<b>bold</b>' not in page
    assert 'not taken' in page and 'Timeout 30000ms exceeded' in page
    assert 'This photo looks good.' in page and 'Microsoft Edge' in page
    assert 'never commit them' in page


def test_a_picture_that_cannot_be_taken_is_listed_and_the_run_goes_on(ce, tmp_path):
    class Broken(Exception):
        pass

    class Page:
        def evaluate(self, script):
            return True

        def wait_for_timeout(self, ms):
            pass

        def screenshot(self, path, **options):
            if 'second' in path:
                raise Broken('Target page, context or browser has been closed\nmore detail')
            Path(path).write_bytes(b'png')

    album = ce.Album(tmp_path)
    cam = ce.Camera(Page(), album, 'person1', (Broken,))
    assert cam.page_shot('first', 'One') is True
    assert cam.page_shot('second', 'Two') is False
    assert cam.page_shot('third', 'Three') is True
    assert [s.file for s in album.shots] == ['person1-01-first.png', None, 'person1-03-third.png']
    assert album.missed()[0].why == 'Target page, context or browser has been closed'
    assert (tmp_path / 'person1-03-third.png').is_file()


def test_the_options_are_checked(ce):
    args = ce.parse([])
    assert args.out == ROOT.parent / 'evidence' and args.photos == ROOT.parent / 'test-photos' and args.chat == 7 and args.browser == 'auto'
    with pytest.raises(SystemExit):
        ce.parse(['--chat', '8'])
    with pytest.raises(SystemExit):
        ce.parse(['--url', 'http://127.0.0.1:8000', '--no-gemini'])
    assert ce.parse(['--people', 'person1', '--people', 'person2']).people == ['person1', 'person2']


def test_without_playwright_it_says_how_to_install_it(ce, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ce, 'load_playwright', lambda: None)
    assert ce.run(ce.parse(['--out', str(tmp_path / 'evidence')])) == 2
    assert 'requirements-evidence.txt' in capsys.readouterr().out
    assert not (tmp_path / 'evidence').exists()


def test_it_never_saves_pictures_of_palms_inside_the_project(ce, monkeypatch, capsys):
    monkeypatch.setattr(ce, 'load_playwright', lambda: object())
    assert ce.run(ce.parse(['--out', str(ROOT / 'evidence')])) == 2
    assert 'may not be saved inside the project folder' in capsys.readouterr().out
    assert not (ROOT / 'evidence').exists()


def test_asking_for_a_folder_of_photos_that_is_not_there_stops_before_anything_starts(ce, monkeypatch, capsys, tmp_path):
    photos = tmp_path / 'test-photos' / 'person1'
    photos.mkdir(parents=True)
    for side in ('left', 'right'):
        (photos / f'{side}.jpg').write_bytes(b'\xff\xd8\xff')
    monkeypatch.setattr(ce, 'load_playwright', lambda: object())
    code = ce.run(ce.parse(['--photos', str(tmp_path / 'test-photos'), '--out', str(tmp_path / 'evidence'), '--people', 'person9']))
    assert code == 2 and 'person9' in capsys.readouterr().out
    assert not (tmp_path / 'evidence').exists()


def test_run_bat_installs_playwright_from_its_own_list_before_it_runs_the_script():
    text = (ROOT / 'run.bat').read_text(encoding='utf-8')
    body = text.split(':evidence', 1)[1]
    install = body.index('requirements-evidence.txt')
    start = body.index('scripts\\capture_evidence.py')
    assert body.index('serve.py --prepare-only') < install < start
    assert 'import playwright' in body[:install]


def test_the_chat_pictures_get_a_taller_window_and_show_the_last_question_at_the_top(ce):
    """A long answer under its question does not fit a chat panel 900 px high, so the window grows while the questions are asked."""
    assert ce.CHAT_VIEWPORT['width'] == ce.VIEWPORT['width'] and ce.CHAT_VIEWPORT['height'] >= 2 * ce.VIEWPORT['height'] - 100
    assert "querySelector('[role=log]')" in ce.SHOW_LAST_EXCHANGE and 'scrollTop' in ce.SHOW_LAST_EXCHANGE
    body = (SCRIPTS / 'capture_evidence.py').read_text(encoding='utf-8').split('def capture_chat', 1)[1].split('\ndef ', 1)[0]
    assert 'set_viewport_size(CHAT_VIEWPORT)' in body and 'finally:' in body and 'set_viewport_size(VIEWPORT)' in body
