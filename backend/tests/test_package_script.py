"""scripts/package.py, the zip that is handed in. It must hold what was meant and nothing else: no key, no private file, no photo of a
palm, a website that is the one the sources make. Every one of those is tried here with a small project made for the purpose."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest
from zip_helpers import SOURCES, build_site, jpeg, model_bytes, png, write

REAL_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REAL_ROOT / 'scripts' / 'package.py'

# Built at run time, in pieces, so that the scan of this very folder does not (rightly) flag this file.
KEY = 'AIza' + 'SyDq8Zr3Xk1Lm9Wv2Bn7Ht4Jc6Pf0Gs5Yua'


@pytest.fixture
def pk(monkeypatch):
    spec = importlib.util.spec_from_file_location('package_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['package_under_test'] = module  # a dataclass looks its own module up by name
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.fetch_models, 'MIN_BYTES', 10)  # the real model is 7 MB; the one made here is a few bytes
    yield module
    sys.modules.pop('package_under_test', None)


# ------------------------------------------------------------------ a small project


@pytest.fixture
def project(pk, tmp_path, monkeypatch):
    root = tmp_path / 'kiro-ai'
    write(root, SOURCES)
    build_site(pk, root)
    monkeypatch.setattr(pk, 'ROOT', root)
    return root


def names_in(archive: Path) -> set[str]:
    with zipfile.ZipFile(archive) as z:
        return set(z.namelist())


# ------------------------------------------------------------------ what is packed


def test_a_good_project_is_packed_under_one_folder_and_nothing_is_wrong(pk, project):
    plan = pk.make_plan(project, include_model=False)
    assert plan.problems == []
    assert set(plan.names()) == set(SOURCES) | {'dist-server/index.html', 'dist-server/build-info.json', 'dist-server/source.sha256'}


def test_what_can_be_made_again_and_what_is_private_is_left_out_and_said_so(pk, project):
    write(
        project,
        {
            'node_modules/react/index.js': 'x',
            'backend/.venv/pyvenv.cfg': 'x',
            'dist/index.html': 'x',
            'backend/app/__pycache__/main.cpython-314.pyc': b'\0',
            'backend/.pytest_cache/README.md': 'x',
            'backend/.env': 'GEMINI_API_KEY=' + KEY,
            'backend/secrets/service-account.json': '{}',
            'test-photos/person1/left.jpg': jpeg(exif=True),
            'debug/summary.txt': 'x',
            'submission/older.zip': b'PK',
            'scripts/notes.log': 'x',
            'Thumbs.db': b'\0',
        },
    )
    plan = pk.make_plan(project, include_model=False)
    packed = plan.names()
    for left in ('node_modules', '.venv', 'dist/', '__pycache__', '.pytest_cache', 'service-account', 'test-photos', 'debug/', 'submission', '.log'):
        assert not any(left in name for name in packed), left
    assert 'backend/.env' not in packed and 'Thumbs.db' not in packed and 'backend/.env.example' in packed
    assert plan.problems == []
    why = {reason for _, reason in plan.left_out}
    assert {'your photos', 'private files (keys and settings)', 'caches', 'the sample-data build of the website', 'logs', 'system files'} <= why
    assert ('backend/.env', 'private files (keys and settings)') in plan.left_out
    shown = '\n'.join(pk.summary_of_left_out(plan.left_out))
    assert 'backend\\.env' in shown and KEY not in shown  # the name of a private file is said, never what is in it


@pytest.mark.parametrize('name', ['.env', '.env.local'])
def test_a_settings_file_in_the_project_folder_stops_the_run_because_the_site_was_built_with_it(pk, project, name):
    write(project, {name: 'VITE_GUEST_SESSION_MINUTES=1\n'})
    plan = pk.make_plan(project, include_model=False)
    assert len(plan.problems) == 1 and name in plan.problems[0] and 'Rename it' in plan.problems[0]
    assert name not in plan.names()


def test_other_files_in_the_models_folder_are_not_packed(pk, project):
    write(project, {'backend/models/other.bin': b'1', 'backend/models/hand_landmarker.task.part': b'1'})
    plan = pk.make_plan(project, include_model=False)
    assert not any(name.startswith('backend/models/') and name != 'backend/models/.gitkeep' for name in plan.names())


# ------------------------------------------------------------------ the hand model


def test_the_hand_model_goes_in_with_its_notice_and_the_licence_text(pk, project, tmp_path):
    (project / 'backend/models/hand_landmarker.task').write_bytes(model_bytes(tmp_path))
    plan = pk.make_plan(project)
    assert plan.problems == [] and 'backend/models/hand_landmarker.task' in plan.names() and 'backend/models/NOTICE.txt' in plan.names()
    notice = plan.extra['backend/models/NOTICE.txt'].decode()
    assert 'Apache License, Version 2.0' in notice and 'docs/licenses/Apache-2.0.txt' in notice and 'storage.googleapis.com' in notice
    assert not any(name == 'backend/models/hand_landmarker.task' for name, _ in plan.left_out)


def test_without_the_model_file_or_by_choice_the_zip_has_none_and_says_how_to_get_it(pk, project, tmp_path):
    plan = pk.make_plan(project)
    assert 'backend/models/hand_landmarker.task' not in plan.names() and plan.problems == [] and 'run.bat models' in plan.notes[0]
    (project / 'backend/models/hand_landmarker.task').write_bytes(model_bytes(tmp_path))
    plan = pk.make_plan(project, include_model=False)
    assert 'backend/models/hand_landmarker.task' not in plan.names() and '--no-model' in plan.notes[0]


def test_a_damaged_model_or_a_missing_licence_stops_the_run(pk, project, tmp_path):
    model = project / 'backend/models/hand_landmarker.task'
    model.write_bytes(b'<html>404 not found</html>' * 3)
    plan = pk.make_plan(project)
    assert len(plan.problems) == 1 and 'not a sound model' in plan.problems[0] and 'run.bat models --force' in plan.problems[0]
    model.write_bytes(model_bytes(tmp_path))
    (project / 'docs/licenses/Apache-2.0.txt').unlink()
    plan = pk.make_plan(project)
    assert len(plan.problems) == 1 and 'licence' in plan.problems[0]


# ------------------------------------------------------------------ pictures


def test_camera_data_is_found_in_a_jpeg_and_a_png(pk):
    assert pk.camera_data_in(jpeg()) is None
    assert pk.camera_data_in(jpeg(exif=True)) == 'Exif or XMP'
    assert pk.camera_data_in(jpeg(xmp=True)) == 'Exif or XMP'
    assert pk.camera_data_in(png()) is None
    assert pk.camera_data_in(png(exif=True)) == 'Exif'
    assert 'may carry camera data' in pk.camera_data_in(b'RIFF....WEBPVP8 ')


def test_the_drawn_sample_hands_are_allowed(pk, project):
    write(project, {'backend/tests/data/sample-left.jpg': jpeg(extra=1000), 'backend/tests/data/sample-right.jpg': jpeg(), 'public/logo.png': png()})
    problems, allowed = pk.picture_problems(pk.make_plan(project, include_model=False).files)
    assert problems == [] and allowed == ['backend/tests/data/sample-left.jpg', 'backend/tests/data/sample-right.jpg', 'public/logo.png']


@pytest.mark.parametrize(
    'rel, content, expected',
    [
        ('docs/my-hand.jpg', jpeg(), 'is a picture. Only the drawn sample hands'),
        ('backend/tests/data/phone.jpg', jpeg(exif=True), 'carries camera data (Exif or XMP)'),
        ('backend/tests/data/phone.jpeg', jpeg(xmp=True), 'carries camera data'),
        ('backend/tests/data/phone.png', png(exif=True), 'carries camera data (Exif)'),
        ('backend/tests/data/big.jpg', jpeg(extra=500_000), 'The limit is 400,000 bytes'),
        ('backend/tests/data/photo.heic', b'ftypheic', 'may carry camera data'),
        ('backend/tests/data/photo.webp', b'RIFFxxxxWEBP', 'may carry camera data'),
        ('left.JPG', jpeg(), 'is a picture'),
        ('test-hands/right.png', png(), 'is a picture'),
    ],
)
def test_any_other_picture_stops_the_run(pk, project, rel, content, expected):
    write(project, {rel: content})
    problems, _ = pk.picture_problems(pk.make_plan(project, include_model=False).files)
    assert len(problems) == 1 and rel in problems[0] and expected in problems[0]


def test_a_photo_written_into_a_text_file_is_found_but_a_small_icon_is_not(pk, project):
    write(project, {'docs/notes.md': 'look: data:image/jpeg;base64,' + 'A' * 30000})
    problems, _ = pk.picture_problems(pk.make_plan(project, include_model=False).files)
    assert len(problems) == 1 and 'docs/notes.md' in problems[0] and 'data: address' in problems[0]
    (project / 'docs/notes.md').write_text('icon: data:image/png;base64,' + 'A' * 300 + ' and data:image/svg+xml;base64,' + 'B' * 30000)
    assert pk.picture_problems(pk.make_plan(project, include_model=False).files)[0] == []


def test_binary_files_of_an_unfamiliar_kind_are_pointed_out_and_fonts_and_big_text_are_not(pk, project):
    write(project, {'docs/report.pdf': b'%PDF-1.7\0\0\0', 'dist-server/assets/font.woff2': b'wOF2\0\0', 'dist-server/assets/big.js': 'var a=1;\n' * 300_000, 'backend/tests/data/a.jpg': jpeg()})
    odd = pk.unfamiliar_files(pk.make_plan(project, include_model=False).files)
    assert odd == ['docs/report.pdf']


# ------------------------------------------------------------------ the website


def test_the_site_must_be_the_one_the_sources_make_and_the_real_one(pk, project):
    assert pk.site_problem(project) is None
    path = project / 'src/App.tsx'
    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))  # line endings do not matter
    assert pk.site_problem(project) is None
    path.write_text('export default 2\n')
    assert 'older than its sources' in pk.site_problem(project)
    build_site(pk, project, mock=True)
    assert 'sample-data build' in pk.site_problem(project)
    build_site(pk, project)
    (project / 'dist-server/build-info.json').write_text('not json')
    assert 'cannot be read' in pk.site_problem(project)
    (project / 'dist-server/source.sha256').unlink()
    assert 'fingerprint' in pk.site_problem(project)
    (project / 'dist-server/index.html').unlink()
    assert 'has not been built' in pk.site_problem(project)


# ------------------------------------------------------------------ the zip itself


def packed(pk, project, tmp_path, **options):
    plan = pk.make_plan(project, **options)
    return plan, pk.build_zip(plan, tmp_path / 'out', stamp='20261119-120000')


def test_the_zip_holds_one_folder_with_exactly_the_planned_files(pk, project, tmp_path):
    plan, archive = packed(pk, project, tmp_path, include_model=False)
    assert archive.name == 'kiro-ai-20261119-120000.zip' and not list((tmp_path / 'out').glob('*.part'))
    assert names_in(archive) == {f'kiro-ai/{name}' for name in plan.names()}
    with zipfile.ZipFile(archive) as z:
        assert z.read('kiro-ai/run.bat') == SOURCES['run.bat']  # byte for byte: the Windows line endings are kept
    assert pk.check_zip(archive, plan.names()) == []


def test_a_zip_with_the_model_passes_its_own_check(pk, project, tmp_path):
    (project / 'backend/models/hand_landmarker.task').write_bytes(model_bytes(tmp_path))
    plan, archive = packed(pk, project, tmp_path)
    assert 'kiro-ai/backend/models/NOTICE.txt' in names_in(archive)
    assert pk.check_zip(archive, plan.names()) == []


def smuggle(archive: Path, files: dict[str, str | bytes], drop: tuple[str, ...] = ()) -> Path:
    """The same zip with other files in it, as if the script had gone wrong."""
    changed = archive.with_name('changed.zip')
    with zipfile.ZipFile(archive) as old, zipfile.ZipFile(changed, 'w') as new:
        for info in old.infolist():
            if info.filename not in files and not info.filename.endswith(drop):
                new.writestr(info.filename, old.read(info.filename))
        for name, content in files.items():
            new.writestr(name, content)
    return changed


def test_the_finished_zip_is_checked_from_the_other_side(pk, project, tmp_path):
    plan, archive = packed(pk, project, tmp_path, include_model=False)

    problems = pk.check_zip(smuggle(archive, {'kiro-ai/backend/.env': 'GEMINI_API_KEY=' + KEY}), plan.names())
    assert any('backend/.env is a private file and is in the zip' in p for p in problems)
    assert not any(KEY in p for p in problems)  # a private file is not even read, and a key is never printed in full

    problems = pk.check_zip(smuggle(archive, {'kiro-ai/src/lib/config.ts': f'export const key = "{KEY}"\n'}), plan.names())
    assert any('src/lib/config.ts:1' in p and 'looks like a Google API key' in p for p in problems) and not any(KEY in p for p in problems)

    assert any('.env.local is a private file' in p for p in pk.check_zip(smuggle(archive, {'kiro-ai/.env.local': 'x'}), plan.names()))
    assert any('backend/secrets/service-account.json' in p for p in pk.check_zip(smuggle(archive, {'kiro-ai/backend/secrets/service-account.json': '{}'}), plan.names()))
    assert any('test-photos/left.jpg is a picture' in p for p in pk.check_zip(smuggle(archive, {'kiro-ai/test-photos/left.jpg': jpeg(exif=True)}), plan.names()))

    assert any('README.md is missing' in p for p in pk.check_zip(smuggle(archive, {}, drop=('/README.md',)), plan.names()))
    assert any('dist-server/source.sha256 is missing' in p for p in pk.check_zip(smuggle(archive, {}, drop=('source.sha256',)), None))
    assert any('Unix line endings' in p for p in pk.check_zip(smuggle(archive, {'kiro-ai/run.bat': b'@echo off\nrem run it\n'}), plan.names()))
    assert any('older than its sources' in p for p in pk.check_zip(smuggle(archive, {'kiro-ai/src/App.tsx': 'export default 99\n'}), plan.names()))
    assert any('outside the kiro-ai folder' in p for p in pk.check_zip(smuggle(archive, {'other/readme.txt': 'x'}), plan.names()))
    assert any('does not hold what was meant' in p and 'extra.txt' in p for p in pk.check_zip(smuggle(archive, {'kiro-ai/extra.txt': 'x'}), plan.names()))


def test_a_zip_that_is_damaged_or_tries_to_leave_its_folder_is_refused(pk, project, tmp_path):
    _plan, archive = packed(pk, project, tmp_path, include_model=False)
    assert 'cannot be opened' in pk.check_zip(tmp_path / 'missing.zip')[0]
    broken = tmp_path / 'broken.zip'
    broken.write_bytes(archive.read_bytes()[:500])
    assert 'cannot be opened' in pk.check_zip(broken)[0]
    for name in ('kiro-ai/../evil.txt', '/etc/evil.txt', 'kiro-ai\\..\\..\\evil.txt', 'C:/evil.txt'):
        problems = pk.check_zip(smuggle(archive, {name: 'x'}), None)
        assert any('outside its folder' in p for p in problems), name
    assert not (tmp_path / 'evil.txt').exists()


# ------------------------------------------------------------------ the command


def run(pk, capsys, *argv):
    code = pk.main(list(argv))
    return code, capsys.readouterr().out


def test_a_dry_run_checks_everything_and_makes_no_zip(pk, project, tmp_path, capsys):
    code, out = run(pk, capsys, '--dry-run', '--no-model', '--out', str(tmp_path / 'out'))
    assert code == 0 and 'RESULT: PASS (dry run: no zip was made)' in out and 'WARN  hand model' in out
    assert not (tmp_path / 'out').exists()


def test_the_command_makes_the_zip_and_tells_its_hash(pk, project, tmp_path, capsys):
    (project / 'backend/models/hand_landmarker.task').write_bytes(model_bytes(tmp_path))
    write(project, {'backend/tests/data/sample-left.jpg': jpeg()})
    code, out = run(pk, capsys, '--out', str(tmp_path / 'out'))
    made = list((tmp_path / 'out').glob('kiro-ai-*.zip'))
    assert code == 0 and len(made) == 1 and out.rstrip().endswith('RESULT: PASS')
    assert hashlib.sha256(made[0].read_bytes()).hexdigest() in out and str(made[0]) in out
    for line in ('PASS  files to pack', 'PASS  no key or private file', 'PASS  no photo', 'PASS  the website is current', 'PASS  hand model', 'PASS  the finished zip, opened again'):
        assert line in out
    assert 'run.bat fresh' in out


def test_a_key_in_a_file_stops_the_command_and_no_zip_is_made(pk, project, tmp_path, capsys):
    write(project, {'src/lib/config.ts': f'export const key = "{KEY}"\n'})
    code, out = run(pk, capsys, '--out', str(tmp_path / 'out'), '--no-model')
    assert code == 1 and 'FAIL  no key or private file' in out and 'src/lib/config.ts:1' in out and 'No zip was made' in out and KEY not in out
    assert not (tmp_path / 'out').exists()


def test_a_photo_stops_the_command(pk, project, tmp_path, capsys):
    write(project, {'docs/palm.jpg': jpeg(exif=True)})
    code, out = run(pk, capsys, '--out', str(tmp_path / 'out'), '--no-model')
    assert code == 1 and 'FAIL  no photo' in out and 'docs/palm.jpg' in out and not (tmp_path / 'out').exists()


def test_a_website_older_than_its_sources_stops_the_command_and_says_what_to_run(pk, project, tmp_path, capsys):
    (project / 'src/App.tsx').write_text('export default 2\n')
    code, out = run(pk, capsys, '--out', str(tmp_path / 'out'), '--no-model')
    assert code == 1 and 'FAIL  the website is current' in out and 'run.bat --prepare-only' in out and not (tmp_path / 'out').exists()


def test_a_line_left_for_the_author_to_write_is_named_but_does_not_stop_the_zip(pk, project, tmp_path, capsys):
    code, out = run(pk, capsys, '--out', str(tmp_path / 'out'), '--no-model')
    assert code == 0 and 'lines for you to write' not in out
    write(project, {'README.md': '# Kiro AI\n\n## Help\n\n- **[AUTHOR TO COMPLETE before handing in: who made the website]**\n', 'docs/LLM_DESIGN.md': 'x\n[AUTHOR TO CHECK this]\n'})
    assert pk.lines_to_fill(project) == ['README.md, line 5', 'docs/LLM_DESIGN.md, line 2']
    code, out = run(pk, capsys, '--out', str(tmp_path / 'out2'), '--no-model')
    assert code == 0 and 'WARN  lines for you to write' in out and 'README.md, line 5 and 1 more' in out and 'RESULT: PASS' in out


def test_a_settings_file_stops_the_command(pk, project, tmp_path, capsys):
    write(project, {'.env.local': 'VITE_GUEST_SESSION_MINUTES=1\n'})
    code, out = run(pk, capsys, '--out', str(tmp_path / 'out'), '--no-model')
    assert code == 1 and 'FAIL  files to pack' in out and '.env.local is in the project folder' in out


def test_if_the_zip_fails_its_own_check_it_is_deleted(pk, project, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(pk, 'check_zip', lambda path, expected=None: ['backend/.env is a private file and is in the zip'])
    code, out = run(pk, capsys, '--out', str(tmp_path / 'out'), '--no-model')
    assert code == 1 and 'FAIL  the finished zip, opened again' in out and 'The zip was deleted' in out
    assert list((tmp_path / 'out').glob('*')) == []


def test_the_scan_still_guards_the_list_if_a_private_file_got_into_it(pk, project, tmp_path, capsys, monkeypatch):
    """The step that leaves private files out is not the only guard: the key scan refuses a list that holds one."""
    real_walk = pk.walk

    def careless(root):
        files, left_out, problems = real_walk(root)
        return [*files, (root / 'backend/.env', 'backend/.env')], left_out, problems

    write(project, {'backend/.env': 'GEMINI_API_KEY=' + KEY})
    monkeypatch.setattr(pk, 'walk', careless)
    code, out = run(pk, capsys, '--dry-run', '--no-model')
    assert code == 1 and 'is a private file and must not be packaged' in out and KEY not in out


# ------------------------------------------------------------------ this very project


def test_nothing_in_this_project_is_a_key_or_a_photo(pk):
    """Whatever state the website is in on this computer: the parts that never depend on it."""
    plan = pk.make_plan(REAL_ROOT, include_model=False)
    assert pk.repo_checks.find_secrets(REAL_ROOT, files=plan.files) == []
    assert pk.picture_problems(plan.files)[0] == []
    assert not any(problem for problem in plan.problems if 'sound model' in problem or 'licence' in problem)
    names = plan.names()
    assert 'run.bat' in names and 'scripts/package.py' in names and 'docs/licenses/Apache-2.0.txt' in names
    assert not any(name.startswith(('node_modules/', 'backend/.venv/', 'test-photos/', 'debug/')) or name in ('.env', 'backend/.env') for name in names)
