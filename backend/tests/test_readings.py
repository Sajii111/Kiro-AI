"""POST /readings and the processing stream, and the reading endpoints."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time

import photos as P
import pytest
from helpers import (
    IMAGE_STAGES,
    LEFT,
    RIGHT,
    STAGES,
    add_profile,
    make_reading,
    parse_stream,
    photo_files,
    run_reading,
    start_guest,
)

from app.api import readings as readings_api
from app.cv.images import check_photo


@pytest.fixture
def guest(client):
    start_guest(client)
    return client


@pytest.fixture
def profile(guest):
    return add_profile(guest)


def stage_events(events):
    return [(d['stage'], d['state']) for n, d in events if n == 'stage']


# ------------------------------------------------------------------ the stream


def test_the_stream_reports_every_step_in_order_and_ends_with_the_reading(guest, profile):
    r, events = run_reading(guest, profile['id'])
    assert r.headers['content-type'].startswith('text/event-stream')
    assert 'no-cache' in r.headers['cache-control'] and 'no-transform' in r.headers['cache-control']
    assert r.headers['x-accel-buffering'] == 'no'
    assert 'content-encoding' not in r.headers  # never compressed

    expected = [(s, state) for s in STAGES for state in ('running', 'done')]
    assert stage_events(events) == expected
    assert events[-1][0] == 'reading' and [n for n, _ in events].count('reading') == 1
    assert all(n in ('stage', 'reading') for n, _ in events)


def test_the_six_image_steps_carry_small_previews_of_both_hands(guest, profile):
    _, events = run_reading(guest, profile['id'])
    done = {d['stage']: d for n, d in events if n == 'stage' and d['state'] == 'done'}
    for stage in STAGES:
        assert done[stage].get('detail'), stage  # every finished step says something specific
        if stage in IMAGE_STAGES:
            previews = done[stage]['previews']
            assert set(previews) == {'left', 'right'}
            for url in previews.values():
                assert url.startswith('data:image/jpeg;base64,') and 2_000 < len(url) < 200_000
        else:
            assert 'previews' not in done[stage]
    running = [d for n, d in events if n == 'stage' and d['state'] == 'running']
    assert all('previews' not in d for d in running)


def test_previews_are_real_pictures_made_from_the_photo(guest, profile):
    """Each step does what its name says, measured on the pictures that come back."""
    import base64

    import cv2
    import numpy as np

    _, events = run_reading(guest, profile['id'])
    done = {d['stage']: d for n, d in events if n == 'stage' and d['state'] == 'done'}

    def picture(stage, side='left'):
        url = done[stage]['previews'][side]
        return cv2.imdecode(np.frombuffer(base64.b64decode(url.split(',', 1)[1]), np.uint8), cv2.IMREAD_COLOR)

    def luma(img):
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def specks(img):
        """How many separate bright blobs a black-and-white picture has."""
        return cv2.connectedComponents((luma(img) > 90).astype(np.uint8))[0]

    gray, blur, contrast = picture('gray'), picture('blur'), picture('contrast')
    edges, threshold, morphology = picture('edges'), picture('threshold'), picture('morphology')

    assert max(gray.shape[:2]) == 400  # about 400 px on the longest side
    assert gray.shape[0] / gray.shape[1] == pytest.approx(1000 / 800, abs=0.02)  # the shape of the photo is kept
    assert np.abs(gray[..., 0].astype(int) - gray[..., 2].astype(int)).max() <= 2  # colour removed
    sharp = lambda img: cv2.Laplacian(luma(img), cv2.CV_64F).var()
    assert sharp(blur) < sharp(gray)  # smoothing smoothed
    assert luma(contrast).std() > luma(gray).std()  # contrast was lifted
    bright = (luma(edges) > 90).mean()
    assert 0.002 < bright < 0.25  # a few thin bright lines on a dark ground: neither blank nor everything
    assert 0.005 < (luma(threshold) > 90).mean() < 0.5
    assert specks(morphology) < specks(threshold)  # tiny specks were removed
    assert picture('gray', 'right').shape == gray.shape or abs(picture('gray', 'right').shape[0] - gray.shape[0]) <= 1


def test_the_reading_has_the_shape_the_website_expects(guest, profile):
    reading = make_reading(guest, profile['id'])
    assert reading['id'].startswith('rd_') and reading['profileId'] == profile['id']
    assert set(reading) == {'id', 'profileId', 'createdAt', 'hands', 'report', 'meta'}
    assert reading['meta']['mock'] is True  # the stand-in line finder is labelled as a sample until Phase 2
    for side in ('left', 'right'):
        hand = reading['hands'][side]
        assert hand['side'] == side and hand['photo'] == {'width': 800, 'height': 1000}
        assert [f['id'] for f in hand['features']] == ['heart', 'head', 'life', 'fate', 'sun']
        assert set(hand['quality']) == {'sharpness', 'lighting', 'resolution', 'palmVisible', 'score'}
        assert 'palmShape' in hand and isinstance(hand['otherCreases'], list) and hand['outline']
    report = reading['report']
    assert [s['featureId'] for s in report['sections']] == ['heart', 'head', 'life', 'fate', 'sun']
    assert [t['themeId'] for t in report['themes']] == ['personality', 'career', 'financial', 'relationships', 'future']
    assert set(report['shape']) == {'observed', 'traditional', 'comparison'}
    assert 'reflection and entertainment' in report['disclaimer']


def test_the_reading_is_saved_before_it_is_announced(guest, profile):
    _, events = run_reading(guest, profile['id'])
    reading = events[-1][1]
    assert guest.get(f'/v1/readings/{reading["id"]}').json() == reading
    assert guest.get('/v1/profiles').json()[0]['readingCount'] == 1


def test_readings_are_added_never_replaced(guest, profile):
    a = make_reading(guest, profile['id'])
    b = make_reading(guest, profile['id'])
    assert a['id'] != b['id']
    rows = guest.get(f'/v1/readings?profileId={profile["id"]}').json()
    assert [r['id'] for r in rows] == [b['id'], a['id']]  # newest first
    assert set(rows[0]) == {'id', 'profileId', 'profileName', 'createdAt', 'counts', 'headline', 'conversationCount'}
    assert sum(rows[0]['counts'].values()) == 10 and rows[0]['profileName'] == 'Saji' and rows[0]['headline']


def test_a_failed_step_ends_the_stream_with_an_error_and_saves_nothing(guest, profile, monkeypatch):
    def crash(reading_id, profile_id, photos, emit, cancel, pause_ms, llm=None):
        emit('validate', 'done', 'Both photos passed the checks', None)
        emit('contrast', 'running', None, None)
        raise RuntimeError('boom')

    monkeypatch.setattr(readings_api, 'run_reading', crash)
    r = guest.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files())
    events = parse_stream(r.text)
    assert r.status_code == 200
    assert events[-2] == ('stage', {'stage': 'contrast', 'state': 'failed', 'detail': 'The step could not be completed'})
    name, error = events[-1]
    assert name == 'error' and error['code'] == 'processing_failed'
    assert 'Nothing was saved' in error['message'] and 'discarded' in error['message']
    assert 'reading' not in [n for n, _ in events]
    assert guest.get('/v1/readings').json() == []
    assert 'boom' not in r.text  # nothing technical leaks to the person


def test_a_guest_session_that_ends_mid_reading_saves_nothing(app, guest, profile, monkeypatch):
    real = readings_api.run_reading

    def slow_then_expire(*args, **kwargs):
        reading = real(*args, **kwargs)
        for g in app.state.store.guests.values():
            g.expires_at = 0  # the guest session runs out while the reading is being made
        return reading

    monkeypatch.setattr(readings_api, 'run_reading', slow_then_expire)
    r = guest.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files())
    events = parse_stream(r.text)
    assert events[-1][0] == 'error' and events[-1][1]['code'] == 'expired'
    assert 'reading' not in [n for n, _ in events]
    assert all(not g.bucket.readings for g in app.state.store.guests.values())


def test_a_profile_deleted_mid_reading_saves_nothing(app, guest, profile, monkeypatch):
    real = readings_api.run_reading

    def delete_then_finish(*args, **kwargs):
        reading = real(*args, **kwargs)
        for g in app.state.store.guests.values():
            g.bucket.profiles.clear()
        return reading

    monkeypatch.setattr(readings_api, 'run_reading', delete_then_finish)
    events = parse_stream(guest.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files()).text)
    assert events[-1][0] == 'error' and events[-1][1]['code'] == 'not_found'
    assert all(not g.bucket.readings for g in app.state.store.guests.values())


def test_a_ping_is_sent_when_a_step_is_slow(app, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    slow = create_app(Settings(env='test', site_dir=app.state.settings.site_dir, stage_pause_ms=120))
    monkeypatch.setattr(readings_api, 'PING_SECONDS', 0.05)
    c = TestClient(slow)
    start_guest(c)
    p = add_profile(c)
    r = c.post('/v1/readings', data={'profileId': p['id']}, files=photo_files())
    assert ': ping' in r.text
    assert parse_stream(r.text)[-1][0] == 'reading'  # pings are comments: they do not disturb the events


def test_the_browser_going_away_stops_the_work_and_saves_nothing(app, guest, profile):
    """Closes the stream part-way through, the way a cancelled request does, and checks nothing is saved."""
    settings = app.state.settings.with_(stage_pause_ms=60)
    caller = readings_api.Caller('guest', next(iter(app.state.store.guests.values())).bucket, guest=next(iter(app.state.store.guests.values())))
    photos = {s: check_photo(data, s, settings.max_pixels) for s, data in (('left', LEFT), ('right', RIGHT))}
    seen = []

    async def go():
        stream = readings_api.stream_reading(
            store=app.state.store, caller=caller, settings=settings, slots=asyncio.Semaphore(1), profile_id=profile['id'], photos=photos
        )
        async for chunk in stream:
            seen.append(chunk)
            if len(seen) == 4:
                break
        await stream.aclose()  # the browser has gone

    before = threading.active_count()
    asyncio.run(go())
    time.sleep(0.5)  # give the worker time to notice
    assert len(seen) == 4 and not any('event: reading' in s for s in seen)
    assert caller.bucket.readings == []
    assert threading.active_count() <= before  # the worker stopped


# ------------------------------------------------------------------ problems before the stream opens


def test_unknown_profile_is_404_before_any_stream(guest):
    r = guest.post('/v1/readings', data={'profileId': 'prf_nope'}, files=photo_files())
    assert r.status_code == 404 and r.json()['error']['code'] == 'not_found'
    r = guest.post('/v1/readings', files=photo_files())
    assert r.status_code == 404


def test_missing_photo_is_422(guest, profile):
    r = guest.post('/v1/readings', data={'profileId': profile['id']}, files={'left': ('l.jpg', LEFT, 'image/jpeg')})
    assert r.status_code == 422 and 'right photo is missing' in r.json()['error']['message']
    r = guest.post('/v1/readings', data={'profileId': profile['id']}, files={'left': ('l.jpg', b'', 'image/jpeg'), 'right': ('r.jpg', RIGHT, 'image/jpeg')})
    assert r.status_code == 422 and 'empty' in r.json()['error']['message']


def test_a_photo_that_fails_the_checks_stops_the_reading(guest, profile):
    for bad, word in [
        (P.jpeg(P.blurry(P.palm())), 'blurry'),
        (P.jpeg(P.dark(P.palm())), 'dark|blurry'),  # a dark photo is soft as well: the first failing check is the one reported
        (P.jpeg(P.not_a_palm()), 'palm'),
        (b'not a photo at all', 'JPG or PNG'),
        (LEFT[:3000], 'could not be opened'),
    ]:
        r = guest.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(left=bad))
        assert r.status_code == 422 and r.json()['error']['code'] == 'invalid', word
        message = r.json()['error']['message']
        assert message.startswith('The left photo did not pass the checks.') and any(w in message for w in word.split('|')), message
    assert guest.get('/v1/readings').json() == []


def test_the_second_photo_is_checked_too(guest, profile):
    r = guest.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(right=P.jpeg(P.blurry(P.palm()))))
    assert r.status_code == 422 and r.json()['error']['message'].startswith('The right photo')


def test_it_needs_a_session(client):
    r = client.post('/v1/readings', data={'profileId': 'x'}, files=photo_files())
    assert r.status_code == 401


# ------------------------------------------------------------------ photos are never kept


def test_no_photo_is_ever_written_to_disk(app, guest, profile, tmp_path, monkeypatch):
    """Even a photo bigger than Starlette's usual 1 MB limit for keeping uploads in memory stays in memory."""
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    monkeypatch.setattr(tempfile, 'tempdir', str(scratch))

    def refuse_to_spill(self, *args, **kwargs):
        raise AssertionError('an upload was about to be written to a temporary file')

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, 'rollover', refuse_to_spill)
    big = P.png(P.palm())  # a PNG of this picture is several MB, well past 1 MB
    assert len(big) > 1_100_000
    r = guest.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(left=big, right=big))
    assert r.status_code == 200 and parse_stream(r.text)[-1][0] == 'reading'
    assert list(scratch.iterdir()) == []


def test_nothing_that_is_stored_or_returned_contains_a_photo(guest, profile):
    reading = make_reading(guest, profile['id'])
    export = guest.get('/v1/account/export').text
    for text in (str(reading), export):
        assert 'data:image' not in text and 'base64' not in text and '/9j/' not in text  # no picture, no JPEG bytes


# ------------------------------------------------------------------ the other reading endpoints


def test_get_and_delete_a_reading(guest, profile):
    reading = make_reading(guest, profile['id'])
    assert guest.get(f'/v1/readings/{reading["id"]}').json() == reading
    assert guest.get('/v1/readings/rd_nope').status_code == 404
    r = guest.delete(f'/v1/readings/{reading["id"]}')
    assert r.json() == {'profiles': 0, 'readings': 1, 'conversations': 0, 'messages': 0}
    assert guest.get(f'/v1/readings/{reading["id"]}').status_code == 404
    assert guest.delete(f'/v1/readings/{reading["id"]}').status_code == 404
    assert guest.get('/v1/profiles').json()[0]['readingCount'] == 0
