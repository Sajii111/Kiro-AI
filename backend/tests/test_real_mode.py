"""Real analysis through the API.

A fake hand finder (synth.FakeFinder) stands in for the hand model, so these tests need neither MediaPipe nor the model
file. It knows where the landmarks of two drawn hands are and answers with them; for any other picture it finds no hand.
"""

from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from helpers import LEFT as SAMPLE_LEFT
from helpers import RIGHT as SAMPLE_RIGHT
from helpers import STAGES, add_profile, parse_stream, photo_files, start_guest
from starlette.datastructures import FormData
from synth import CREASES, FakeFinder, distance_to_polyline, found, jpeg, render

from app.api.uploads import flag
from app.core.config import Settings, read_settings
from app.main import create_app

LEFT_SIZE = (1300, 1250)
RIGHT_SIZE = (1300, 1300)
L_UNIT = 0.9925


@pytest.fixture(scope='module')
def hands():
    left_image, left_placed = render('left', 12, size=LEFT_SIZE, seed=2)
    right_image, right_placed = render('right', -8, size=RIGHT_SIZE, seed=3)
    return SimpleNamespace(
        left=jpeg(left_image),
        right=jpeg(right_image),
        left_placed=left_placed,
        right_placed=right_placed,
        known={LEFT_SIZE: [found(left_placed)], RIGHT_SIZE: [found(right_placed)]},
        stranger=jpeg(render('right', 0, size=(1100, 1100))[0]),  # looks like a hand, but the finder knows nothing about this size
    )


@pytest.fixture
def finder(hands):
    return FakeFinder(hands.known)


@pytest.fixture
def real_app(settings, finder):
    return create_app(settings, finder=finder)


@pytest.fixture
def real(real_app):
    client = TestClient(real_app)
    start_guest(client)
    return client


@pytest.fixture
def profile(real):
    return add_profile(real)


def validate(client, data: bytes, side: str = 'left', **fields):
    return client.post('/v1/photos/validate', data={'side': side, **fields}, files={'photo': ('photo.jpg', data, 'image/jpeg')})


def read(client, profile_id: str, left: bytes, right: bytes, **fields):
    return client.post('/v1/readings', data={'profileId': profile_id, **fields}, files=photo_files(left, right))


def palm_check(response) -> dict:
    return next(c for c in response.json()['checks'] if c['id'] == 'palm_visible')


def finished(response):
    """(the events of the stream, the reading that came last, what each step said when it finished)."""
    assert response.status_code == 200, response.text
    events = parse_stream(response.text)
    said = {d['stage']: d['detail'] for n, d in events if n == 'stage' and d['state'] == 'done'}
    assert events[-1][0] == 'reading'
    return events, events[-1][1], said


# ------------------------------------------------------------------ which kind of analysis is running


def test_health_says_which_kind_of_analysis_is_running(real, client):
    assert real.get('/v1/health').json()['analysis'] == 'real'
    assert client.get('/v1/health').json()['analysis'] == 'sample'  # the plain test app has no hand finder


def test_the_hand_model_is_released_when_the_server_stops(real_app, finder):
    with TestClient(real_app):
        assert not finder.closed
    assert finder.closed


def test_real_mode_does_not_start_without_the_hand_model(settings, tmp_path):
    broken = Settings(env='test', site_dir=settings.site_dir, stage_pause_ms=0, analysis_mode='real', hand_model=tmp_path / 'missing.task')
    with pytest.raises(RuntimeError, match='run.bat models'):
        create_app(broken)


def test_auto_mode_without_the_model_starts_as_a_sample_server_and_says_so(settings, tmp_path, caplog):
    auto = Settings(env='test', site_dir=settings.site_dir, stage_pause_ms=0, analysis_mode='auto', hand_model=tmp_path / 'missing.task')
    with caplog.at_level('WARNING', logger='kiro.hand'):
        app = create_app(auto)
    assert app.state.finder is None
    assert TestClient(app).get('/v1/health').json()['analysis'] == 'sample'
    assert 'SAMPLE readings' in caplog.text


def test_the_mode_comes_from_the_environment_and_defaults_to_auto(monkeypatch, tmp_path):
    monkeypatch.delenv('ANALYSIS_MODE', raising=False)
    monkeypatch.delenv('HAND_MODEL', raising=False)
    assert read_settings().analysis_mode == 'auto'
    assert Settings().analysis_mode == 'sample'  # a plain Settings() never loads the model (that is what the tests use)
    monkeypatch.setenv('ANALYSIS_MODE', ' REAL ')
    monkeypatch.setenv('HAND_MODEL', str(tmp_path / 'm.task'))
    assert read_settings().analysis_mode == 'real'
    assert read_settings().hand_model == tmp_path / 'm.task'
    monkeypatch.setenv('ANALYSIS_MODE', 'nonsense')
    assert read_settings().analysis_mode == 'auto'


# ------------------------------------------------------------------ checking a photo with the hand finder


def test_a_photo_of_a_palm_passes_when_the_finder_finds_one(real, hands, finder):
    r = validate(real, hands.right, 'right')
    assert r.status_code == 200 and r.json()['ok'] is True
    assert palm_check(r) == {'id': 'palm_visible', 'label': 'Palm in view', 'status': 'pass', 'message': 'A palm is in view.'}
    assert finder.calls == 1


def test_a_photo_with_no_hand_in_it_is_refused_and_says_what_to_do(real, hands):
    r = validate(real, hands.stranger, 'right')
    assert r.status_code == 200 and r.json()['ok'] is False
    check = palm_check(r)
    assert check['status'] == 'fail' and 'could not find a hand' in check['message']


def test_a_reading_is_refused_when_a_photo_has_no_hand_in_it(real, profile, hands):
    r = read(real, profile['id'], hands.left, hands.stranger)
    assert r.status_code == 422
    assert 'right photo did not pass the checks' in r.json()['error']['message']
    assert real.get('/v1/readings').json() == []  # nothing was kept


def test_a_hand_added_to_the_wrong_side_is_a_warning_that_does_not_block(real, hands):
    r = validate(real, hands.right, 'left')  # a right hand, added as the left one
    assert r.json()['ok'] is True
    check = palm_check(r)
    assert check['status'] == 'warn' and 'right hand' in check['message'] and 'swap' in check['message']


def test_the_other_five_checks_still_run_on_every_photo(real, hands):
    ids = [c['id'] for c in validate(real, hands.left, 'left').json()['checks']]
    assert ids == ['file_type', 'integrity', 'dimensions', 'blur', 'lighting', 'palm_visible']
    blurred = jpeg(cv2.GaussianBlur(render('left', 12, size=LEFT_SIZE, seed=2)[0], (0, 0), 14))
    r = validate(real, blurred, 'left')
    assert {c['id']: c['status'] for c in r.json()['checks']}['blur'] == 'fail'
    assert r.json()['ok'] is False


# ------------------------------------------------------------------ a reading made from the photos themselves


def test_a_reading_of_two_drawn_hands_is_found_in_the_photos_and_says_so(real, profile, hands, finder):
    events, reading, said = finished(read(real, profile['id'], hands.left, hands.right))
    stages = [(d['stage'], d['state']) for n, d in events if n == 'stage']
    assert stages == [(s, state) for s in STAGES for state in ('running', 'done')]
    assert said['lines'] == '8 of 10 lines detected, 0 uncertain, 2 not visible'  # four lines drawn on each hand; no "Sample result:"
    assert said['reading'] == 'Report written from the findings'
    assert finder.calls == 2  # once per photo: the hand is found when the photo is checked and not looked for again

    meta = reading['meta']
    assert (meta['mock'], meta['provider'], meta['model']) == (False, 'knowledge-base', 'rule-based-writer')
    assert meta['pipeline'] == 'opencv-steps 1.0 + palm-lines 1.1'
    for side, size in (('left', LEFT_SIZE), ('right', RIGHT_SIZE)):
        hand = reading['hands'][side]
        assert (hand['photo']['width'], hand['photo']['height']) == size
        assert hand['methodVersion'] == 'palm-lines 1.1'
        assert {f['id']: f['status'] for f in hand['features']} == {'heart': 'detected', 'head': 'detected', 'life': 'detected', 'fate': 'detected', 'sun': 'not_visible'}
        assert hand['palmShape']['status'] == 'detected'
    assert reading['report']['themes'] and reading['report']['summary']


def test_the_lines_in_the_reading_are_the_lines_drawn_in_the_photos(real, profile, hands):
    _, reading, _ = finished(read(real, profile['id'], hands.left, hands.right))
    for side, placed, size in (('left', hands.left_placed, LEFT_SIZE), ('right', hands.right_placed, RIGHT_SIZE)):
        by_id = {f['id']: f for f in reading['hands'][side]['features']}
        for fid, drawn in CREASES.items():
            path = np.array(by_id[fid]['path']) * size
            off = distance_to_polyline(path, placed.px(drawn)) / (placed.scale * L_UNIT)
            assert off.max() < 0.04, f'{side} {fid}: {off.max():.3f} palm lengths off'


def test_the_reading_is_kept_as_it_was_made(real, profile, hands):
    _, reading, _ = finished(read(real, profile['id'], hands.left, hands.right))
    kept = real.get(f"/v1/readings/{reading['id']}")
    assert kept.status_code == 200
    assert kept.json()['meta']['mock'] is False and kept.json() == reading
    listed = real.get('/v1/readings').json()
    assert [r['id'] for r in listed] == [reading['id']] and listed[0]['counts']['detected'] == 8


def test_no_photo_is_kept_anywhere_after_a_real_reading(real, profile, hands):
    events, reading, _ = finished(read(real, profile['id'], hands.left, hands.right))
    assert any('data:image' in str(d) for n, d in events if n == 'stage')  # the pictures were streamed to the page while it ran...
    kept = real.get(f"/v1/readings/{reading['id']}")
    export = real.get('/v1/account/export')
    assert kept.status_code == 200 and export.status_code == 200
    for text in (kept.text, export.text):  # ...but only the findings are kept: no picture of any kind, and no copy of a photo
        assert 'data:image' not in text and 'previews' not in text and 'base64' not in text


# ------------------------------------------------------------------ the website's built-in sample drawings


def test_a_flag_form_field_is_a_yes_only_when_it_says_so():
    form = FormData([('a', '1'), ('b', 'true'), ('c', ' YES '), ('d', '0'), ('e', 'false'), ('f', ''), ('g', 'maybe')])
    assert [flag(form, n) for n in 'abc'] == [True, True, True]
    assert [flag(form, n) for n in 'defg'] == [False, False, False, False]
    assert flag(form, 'missing') is False


def test_a_photo_marked_as_a_sample_drawing_never_goes_to_the_hand_finder(real, finder):
    marked = validate(real, SAMPLE_LEFT, 'left', sample='1')
    assert marked.json()['ok'] is True and palm_check(marked)['status'] == 'pass'
    assert finder.calls == 0
    unmarked = validate(real, SAMPLE_LEFT, 'left')  # the same drawing, not marked: a hand is looked for, and not found
    assert unmarked.json()['ok'] is False and finder.calls == 1


def test_two_sample_drawings_get_a_sample_reading_even_while_the_hand_model_runs(real, profile, finder):
    _, reading, said = finished(read(real, profile['id'], SAMPLE_LEFT, SAMPLE_RIGHT, leftSample='1', rightSample='1'))
    assert reading['meta']['mock'] is True and reading['meta']['provider'] == 'sample'
    assert said['lines'].startswith('Sample result: ')
    assert said['reading'] == 'Sample report written from the findings'
    assert finder.calls == 0


@pytest.mark.parametrize('flags', [{'leftSample': '1'}, {'rightSample': '1'}])
def test_one_sample_photo_makes_the_whole_reading_a_sample(real, profile, hands, finder, flags):
    left = SAMPLE_LEFT if 'leftSample' in flags else hands.left
    right = SAMPLE_RIGHT if 'rightSample' in flags else hands.right
    _, reading, said = finished(read(real, profile['id'], left, right, **flags))
    assert reading['meta']['mock'] is True
    assert said['lines'].startswith('Sample result: ')
    assert finder.calls == 1  # only the real photo was shown to the hand finder


def test_the_flags_do_no_harm_on_a_server_with_no_hand_finder(client):
    start_guest(client)
    pid = add_profile(client)['id']
    assert validate(client, SAMPLE_LEFT, 'left', sample='1').json()['ok'] is True
    _, reading, said = finished(read(client, pid, SAMPLE_LEFT, SAMPLE_RIGHT, leftSample='1', rightSample='1'))
    assert reading['meta']['mock'] is True and said['lines'].startswith('Sample result: ')
    _, plain, _ = finished(read(client, pid, SAMPLE_LEFT, SAMPLE_RIGHT))  # and with no flags at all it is the same as before
    assert plain['meta']['mock'] is True


def test_a_real_reading_cannot_be_asked_for_by_marking_a_real_photo_as_a_sample(real, profile, hands):
    # marking a photo as a sample only ever makes the result LESS real, never more
    _, reading, _ = finished(read(real, profile['id'], hands.left, hands.right, leftSample='1', rightSample='1'))
    assert reading['meta']['mock'] is True
