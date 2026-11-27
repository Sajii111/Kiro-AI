"""Palm locks (ICA 02) through the API: locking a profile, unlocking it, the three outcomes, the attempt log, the lockout, one
open profile per session, the idle re-lock, the password instead of the palm, the Palm lab's test, and that nothing of a
locked profile leaks out of any route.

Drawn hands stand in for photos (see synth.py), each drawn at a size of its own so the fake hand finder can answer for it.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fake_firebase import FakeBackend
from fastapi.testclient import TestClient
from helpers import (
    LEFT,
    RIGHT,
    add_conversation,
    add_profile,
    parse_stream,
    sign_up,
    start_guest,
)
from synth import FakeFinder, found, jpeg, render

from app.core.config import Settings
from app.cv.biometric.match import load_calibration
from app.cv.biometric.template import new_key
from app.locks import FAILURES
from app.main import create_app
from app.store.persist import PersistentStore

PASSWORD = 'a-long-password'
SHOTS = [(0, 480, 1.0), (12, 430, 0.9), (-15, 520, 1.1), (25, 460, 1.0), (-6, 500, 0.95)]


class Photos:
    """Drawn palm photos, each at its own size, with the fake hand finder told where the hand is in each."""

    def __init__(self) -> None:
        self.finder = FakeFinder()
        self.made: dict[tuple, bytes] = {}

    def __call__(self, person: int, k: int, side: str = 'right') -> bytes:
        key = (person, k, side)
        if key not in self.made:
            angle, scale, gain = SHOTS[k % len(SHOTS)]
            size = (1300 + 10 * person + k + (5 if side == 'left' else 0), 1300)
            img, placed = render(side=side, angle=angle, scale=scale, seed=100 + person, size=size)
            rng = np.random.default_rng(1000 * person + k)
            img = np.clip(img.astype(np.float32) * gain + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
            self.finder.hands[(img.shape[1], img.shape[0])] = [found(placed)]
            self.made[key] = jpeg(img)
        return self.made[key]

    def no_hand(self) -> bytes:
        img, _ = render(size=(1299, 1300))
        return jpeg(img)  # the finder was never told about this size: no hand in it


@pytest.fixture
def photos() -> Photos:
    return Photos()


@pytest.fixture
def app(settings, photos):
    return create_app(settings, finder=photos.finder)  # type: ignore[arg-type]


@pytest.fixture
def client(app):
    return TestClient(app)


def signed_in(client) -> None:
    sign_up(client, password=PASSWORD)


def lock(client, profile_id: str, files: list[bytes], side: str = 'right', consent: bool = True):
    data = {'side': side}
    if consent:
        data['consent'] = '1'
    return client.post(f'/v1/profiles/{profile_id}/lock', data=data, files={f'photo{i}': (f'{i}.jpg', b, 'image/jpeg') for i, b in enumerate(files)})


def locked_profile(client, photos: Photos, name: str = 'Saji', person: int = 0) -> dict:
    p = add_profile(client, name=name)
    r = lock(client, p['id'], [photos(person, k) for k in range(3)])
    assert r.status_code == 201, r.text
    return r.json()


def attempt(client, profile_id: str, photo: bytes, test: bool = False):
    """(status, events) of an unlock (or a Palm lab test)."""
    files = {'photo': ('palm.jpg', photo, 'image/jpeg')}
    if test:
        r = client.post('/v1/palm-lock/test', data={'profileId': profile_id}, files=files)
    else:
        r = client.post(f'/v1/profiles/{profile_id}/unlock', files=files)
    if r.status_code != 200:
        return r.status_code, r.json()
    return 200, parse_stream(r.text)


def result_of(events) -> dict:
    name, data = events[-1]
    assert name == 'result', events[-1]
    return data  # type: ignore[return-value]


def profile(client, profile_id: str) -> dict:
    return next(p for p in client.get('/v1/profiles').json() if p['id'] == profile_id)


def sample_reading(client, profile_id: str) -> dict:
    """A reading of the built-in sample drawings (judged without the hand model)."""
    r = client.post(
        '/v1/readings',
        data={'profileId': profile_id, 'leftSample': '1', 'rightSample': '1'},
        files={'left': ('l.jpg', LEFT, 'image/jpeg'), 'right': ('r.jpg', RIGHT, 'image/jpeg')},
    )
    assert r.status_code == 200, r.text
    name, data = parse_stream(r.text)[-1]
    assert name == 'reading', data
    return data  # type: ignore[return-value]


def session_key(client) -> str:
    return f'user:{client.cookies.get("kiro_session")}'


# ------------------------------------------------------------------ locking


def test_a_profile_locks_with_three_photos_and_stays_open_for_now(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    assert p['lock']['side'] == 'right' and p['lock']['samples'] == 3 and p['lock']['engineVersion']
    assert p['open'] is True and p['locked'] is False
    log = client.get('/v1/activity').json()
    assert [a['kind'] for a in log] == ['lock_added']
    assert log[0]['hand'] == 'right' and log[0]['profileId'] == p['id'] and log[0]['id'].startswith('att_')


def test_a_guest_cannot_lock_a_profile(client, photos):
    start_guest(client)
    p = add_profile(client)
    r = lock(client, p['id'], [photos(0, k) for k in range(3)])
    assert r.status_code == 403 and 'account' in r.json()['error']['message']


def test_locking_needs_consent_and_three_to_five_photos(client, photos):
    signed_in(client)
    p = add_profile(client)
    r = lock(client, p['id'], [photos(0, k) for k in range(3)], consent=False)
    assert r.status_code == 422 and 'confirm' in r.json()['error']['message']
    r = lock(client, p['id'], [photos(0, k) for k in range(2)])
    assert r.status_code == 422 and '3 to 5' in r.json()['error']['message']
    r = lock(client, p['id'], [photos(0, k) for k in range(5)] + [photos(0, 0)])
    assert r.status_code == 422
    assert profile(client, p['id'])['lock'] is None


def test_a_photo_that_cannot_be_used_is_pointed_out(client, photos):
    signed_in(client)
    p = add_profile(client)
    r = lock(client, p['id'], [photos(0, 0), photos.no_hand(), photos(0, 2)])
    assert r.status_code == 422
    body = r.json()['error']
    assert [x['index'] for x in body['photos']] == [1] and body['photos'][0]['message']
    assert profile(client, p['id'])['lock'] is None


def test_a_photo_of_someone_else_spoils_the_enrolment(client, photos):
    signed_in(client)
    p = add_profile(client)
    r = lock(client, p['id'], [photos(0, 0), photos(0, 2), photos(2, 0), photos(0, 3)])
    assert r.status_code == 422
    assert r.json()['error']['photos'][0]['index'] == 2
    assert profile(client, p['id'])['lock'] is None


def test_without_the_hand_model_the_palm_lock_says_so(settings, photos):
    client = TestClient(create_app(settings))  # the sample finder: no hand model
    signed_in(client)
    p = add_profile(client)
    r = lock(client, p['id'], [photos(0, k) for k in range(3)])
    assert r.status_code == 503 and r.json()['error']['code'] == 'unavailable'
    info = client.get('/v1/palm-lock').json()
    assert info['available'] is False and 'hand model' in info['note']


# ------------------------------------------------------------------ a locked profile shows nothing


def test_nothing_of_a_locked_profile_can_be_reached_until_it_is_unlocked(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    reading = sample_reading(client, p['id'])
    convo = add_conversation(client, reading['id'])
    other = add_profile(client, name='Mia')
    sample_reading(client, other['id'])

    client.post('/v1/profiles/close')
    listed = profile(client, p['id'])
    assert listed['locked'] is True and listed['open'] is False
    assert listed['readingCount'] == 0 and listed['lastReadingAt'] is None  # how much it holds is hidden too

    assert [r['profileId'] for r in client.get('/v1/readings').json()] == [other['id']]
    refused = [
        client.get(f'/v1/readings?profileId={p["id"]}'),
        client.get(f'/v1/readings/{reading["id"]}'),
        client.patch(f'/v1/readings/{reading["id"]}', json={'name': 'x'}),
        client.delete(f'/v1/readings/{reading["id"]}'),
        client.get(f'/v1/conversations?profileId={p["id"]}'),
        client.get(f'/v1/conversations?readingId={reading["id"]}'),
        client.post(f'/v1/readings/{reading["id"]}/conversations'),
        client.get(f'/v1/conversations/{convo["id"]}'),
        client.post(f'/v1/conversations/{convo["id"]}/messages', json={'text': 'Tell me about my heart line'}),
        client.delete(f'/v1/conversations/{convo["id"]}'),
        client.patch(f'/v1/profiles/{p["id"]}', json={'name': 'Renamed'}),
        client.post(f'/v1/profiles/{p["id"]}/open'),
        client.post('/v1/readings', data={'profileId': p['id'], 'leftSample': '1', 'rightSample': '1'}, files={'left': ('l.jpg', LEFT, 'image/jpeg'), 'right': ('r.jpg', RIGHT, 'image/jpeg')}),
    ]
    for r in refused:
        assert r.status_code == 423, (r.request.method, r.request.url, r.status_code)
        assert r.json()['error']['code'] == 'locked' and r.json()['error']['profileId'] == p['id']
    assert client.get('/v1/conversations').json() == []
    export = client.get('/v1/account/export').json()
    assert {r['profileId'] for r in export['readings']} == {other['id']} and export['conversations'] == []
    assert 'sealed' not in json.dumps(export)  # never the template
    # and none of it was changed
    client.post(f'/v1/profiles/{p["id"]}/unlock', files={'photo': ('p.jpg', photos(0, 3), 'image/jpeg')})
    assert profile(client, p['id'])['readingCount'] == 1 and client.get(f'/v1/conversations/{convo["id"]}').status_code == 200


# ------------------------------------------------------------------ unlocking: the three outcomes


def test_the_right_palm_unlocks_the_profile_step_by_step(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    client.post('/v1/profiles/close')
    status, events = attempt(client, p['id'], photos(0, 3))
    assert status == 200
    stages = [(n, d['stage'], d['state']) for n, d in events if n == 'stage']
    assert [s for _, s, st in stages if st == 'done'] == ['checks', 'roi', 'prep', 'features', 'match']
    assert all(d.get('preview', '').startswith('data:image/jpeg') for n, d in events if n == 'stage' and d['state'] == 'done' and d['stage'] != 'match')
    res = result_of(events)
    cal = load_calibration()
    assert res['outcome'] == 'success' and res['title'] == 'Authentication Successful' and res['opened'] is True
    assert res['score'] >= res['threshold'] == cal.threshold and set(res['methods']) == {'crease', 'compcode'} and 'lbp' in res['raw']
    assert res['durationMs'] > 0 and res['attemptId'].startswith('att_') and res['calibrated'] == cal.calibrated
    assert profile(client, p['id'])['open'] is True
    line = client.get('/v1/activity').json()[0]
    assert line['id'] == res['attemptId'] and line['kind'] == 'unlock' and line['outcome'] == 'success'
    assert line['score'] == res['score'] and line['threshold'] == res['threshold'] and line['durationMs'] == res['durationMs']
    assert line['methods'] == res['methods'] and line['hand'] == 'right' and line['engineVersion']


def test_someone_elses_palm_is_refused_and_logged(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    client.post('/v1/profiles/close')
    _, events = attempt(client, p['id'], photos(2, 0))
    res = result_of(events)
    assert res['outcome'] == 'failed' and res['title'] == 'Authentication Failed' and res['opened'] is False
    assert res['score'] < res['threshold']
    assert profile(client, p['id'])['locked'] is True
    line = client.get('/v1/activity').json()[0]
    assert line['outcome'] == 'failed' and line['profileName'] == 'Saji'


def test_a_photo_with_no_palm_is_an_invalid_image(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    client.post('/v1/profiles/close')
    _, events = attempt(client, p['id'], photos.no_hand())
    res = result_of(events)
    assert res['outcome'] == 'invalid_image' and res['title'] == 'Invalid Image'
    assert 'score' not in res and res['methods'] == {} and res['reason']
    assert any(n == 'stage' and d['stage'] == 'checks' and d['state'] == 'failed' and d.get('detail') for n, d in events)
    line = client.get('/v1/activity').json()[0]
    assert line['outcome'] == 'invalid_image' and 'score' not in line and line['problem']


def test_the_other_hand_is_an_invalid_image(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    client.post('/v1/profiles/close')
    _, events = attempt(client, p['id'], photos(0, 0, side='left'))
    res = result_of(events)
    assert res['outcome'] == 'invalid_image' and res['problem'] == 'wrong_hand'


def test_a_profile_without_a_lock_has_nothing_to_unlock(client, photos):
    signed_in(client)
    p = add_profile(client)
    status, body = attempt(client, p['id'], photos(0, 0))
    assert status == 422 and 'no palm lock' in body['error']['message']


# ------------------------------------------------------------------ lockout


def test_five_failures_lock_the_profile_out_but_invalid_images_do_not_count(client, photos, app):
    signed_in(client)
    p = locked_profile(client, photos)
    client.post('/v1/profiles/close')
    for _ in range(3):
        assert result_of(attempt(client, p['id'], photos.no_hand())[1])['outcome'] == 'invalid_image'
    results = [result_of(attempt(client, p['id'], photos(2 + i % 2, i % 3))[1]) for i in range(FAILURES)]
    assert all(r['outcome'] == 'failed' for r in results)
    assert all('lockedUntil' not in r for r in results[:-1]) and results[-1]['lockedUntil'] > 0
    status, body = attempt(client, p['id'], photos(0, 3))  # even the right palm must wait
    assert status == 429 and body['error']['code'] == 'locked_out' and body['error']['lockedUntil'] == results[-1]['lockedUntil']
    # when the time is up, the right palm opens it, and the count starts again
    lock_ = app.state.store.bucket_of_user(next(iter(app.state.store.accounts))).lock_of(p['id'])
    lock_.lockedUntil = 1
    assert result_of(attempt(client, p['id'], photos(0, 3))[1])['outcome'] == 'success'
    assert lock_.lockedUntil is None
    client.post('/v1/profiles/close')
    assert 'lockedUntil' not in result_of(attempt(client, p['id'], photos(2, 0))[1])


# ------------------------------------------------------------------ one open profile, idle re-lock, switching


def test_opening_another_profile_locks_the_first_again(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    mia = add_profile(client, name='Mia')
    r = client.post(f'/v1/profiles/{mia["id"]}/open')
    assert r.status_code == 200 and r.json()['open'] is True
    assert profile(client, p['id'])['locked'] is True and profile(client, mia['id'])['open'] is True


def test_an_open_profile_left_alone_locks_itself_again(client, photos, app):
    signed_in(client)
    p = locked_profile(client, photos)
    assert profile(client, p['id'])['open'] is True
    app.state.store.open_profiles[session_key(client)].last_seen -= app.state.palm.idle_ms + 1
    assert profile(client, p['id'])['locked'] is True


def test_another_browser_of_the_same_account_must_unlock_too(client, photos, app):
    signed_in(client)
    p = locked_profile(client, photos)
    other = TestClient(app)
    assert other.post('/v1/auth/signin', json={'email': 'saji@example.com', 'password': PASSWORD}).status_code == 200
    assert profile(other, p['id'])['locked'] is True and profile(client, p['id'])['open'] is True


def test_the_profile_cannot_be_switched_while_a_reading_is_being_made(client, photos, app):
    signed_in(client)
    p = locked_profile(client, photos)
    mia = add_profile(client, name='Mia')
    app.state.store.busy[session_key(client)] = 1
    assert client.post(f'/v1/profiles/{mia["id"]}/open').status_code == 409
    assert client.post('/v1/profiles/close').status_code == 409
    assert attempt(client, mia['id'], photos(0, 0))[0] in (409, 422)
    app.state.store.busy.pop(session_key(client))
    assert client.post(f'/v1/profiles/{mia["id"]}/open').status_code == 200
    assert profile(client, p['id'])['locked'] is True


def test_signing_out_locks_everything_again(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    client.post('/v1/auth/signout')
    client.post('/v1/auth/signin', json={'email': 'saji@example.com', 'password': PASSWORD})
    assert profile(client, p['id'])['locked'] is True


# ------------------------------------------------------------------ the password instead of the palm


def test_taking_the_lock_off(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    r = client.request('DELETE', f'/v1/profiles/{p["id"]}/lock')  # open: no password needed
    assert r.status_code == 200 and r.json()['lock'] is None
    p = locked_profile(client, photos, name='Mia', person=1)
    client.post('/v1/profiles/close')
    assert client.request('DELETE', f'/v1/profiles/{p["id"]}/lock').status_code == 403
    assert client.request('DELETE', f'/v1/profiles/{p["id"]}/lock', json={'password': 'wrong-password'}).status_code == 403
    r = client.request('DELETE', f'/v1/profiles/{p["id"]}/lock', json={'password': PASSWORD})
    assert r.status_code == 200 and r.json()['lock'] is None and r.json()['locked'] is False
    removed = [a for a in client.get('/v1/activity').json() if a['kind'] == 'lock_removed']
    assert [a['via'] for a in removed] == ['password', 'palm']


def test_a_locked_profile_is_deleted_only_with_its_palm_or_the_password(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    client.post('/v1/profiles/close')
    assert client.delete(f'/v1/profiles/{p["id"]}').status_code == 403
    assert client.request('DELETE', f'/v1/profiles/{p["id"]}', json={'password': PASSWORD}).status_code == 200
    assert client.get('/v1/profiles').json() == []
    line = client.get('/v1/activity').json()[0]
    assert line['kind'] == 'profile_deleted' and line['via'] == 'password'


def test_deleting_all_data_with_a_locked_profile_needs_the_password(client, photos):
    signed_in(client)
    locked_profile(client, photos)
    client.post('/v1/profiles/close')
    assert client.delete('/v1/account/data').status_code == 403
    r = client.request('DELETE', '/v1/account/data', json={'password': PASSWORD})
    assert r.status_code == 200 and r.json()['profiles'] == 1
    assert client.get('/v1/activity').json() == []


# ------------------------------------------------------------------ the Palm lab


def test_testing_a_verification_by_user_id(client, photos):
    signed_in(client)
    p = locked_profile(client, photos)
    plain = add_profile(client, name='Mia')
    client.post('/v1/profiles/close')
    status, body = attempt(client, 'prf_nobody', photos(0, 3), test=True)
    assert status == 404 and 'prf_nobody' in body['error']['message'] and 'nothing was compared' in body['error']['message']
    status, _ = attempt(client, plain['id'], photos(0, 3), test=True)
    assert status == 422
    _, events = attempt(client, p['id'], photos(0, 3), test=True)
    res = result_of(events)
    assert res['outcome'] == 'success' and res['opened'] is False
    assert profile(client, p['id'])['locked'] is True  # a test never opens anything
    assert client.get('/v1/activity').json()[0]['kind'] == 'test'


def test_a_user_id_from_another_account_is_unknown(client, photos, app):
    signed_in(client)
    p = locked_profile(client, photos)
    stranger = TestClient(app)
    sign_up(stranger, email='mia@example.com')
    status, _ = attempt(stranger, p['id'], photos(0, 3), test=True)
    assert status == 404


def test_the_palm_lab_shows_how_the_lock_decides(client):
    signed_in(client)
    info = client.get('/v1/palm-lock').json()
    cal = load_calibration()
    assert info['available'] is True and info['threshold'] == cal.threshold and info['calibrated'] == cal.calibrated
    assert [m['id'] for m in info['methods']] == ['crease', 'compcode', 'lbp']
    assert info['methods'][2]['weight'] == 0 and info['methods'][0]['weight'] > 0
    assert info['policy'] == {'failures': 5, 'windowMinutes': 10, 'lockoutMinutes': 5, 'idleMinutes': 15, 'enrolMin': 3, 'enrolMax': 5}


# ------------------------------------------------------------------ what is kept


def test_no_photo_and_no_readable_template_is_kept(client, photos, app):
    signed_in(client)
    p = locked_profile(client, photos)
    attempt(client, p['id'], photos(2, 0))
    bucket = app.state.store.bucket_of_user(next(iter(app.state.store.accounts)))
    kept = json.dumps([k.model_dump() for k in bucket.locks] + [a.model_dump() for a in bucket.attempts])
    assert 'data:image' not in kept and 'JFIF' not in kept and 'crease_map' not in kept
    assert bucket.locks[0].sealed.startswith('gAAAA')  # a Fernet token


def test_a_lock_is_saved_in_the_database_and_opens_after_a_restart(settings, photos):
    backend = FakeBackend()
    settings = settings.with_(palm_key=new_key())

    def start():
        app = create_app(settings, finder=photos.finder)  # type: ignore[arg-type]
        app.state.store = PersistentStore(settings.guest_minutes, settings.signin_days, backend)
        return TestClient(app)

    client = start()
    signed_in(client)
    p = locked_profile(client, photos)
    paths = [path for path in backend.docs if '/locks/' in path or '/attempts/' in path]
    assert len([x for x in paths if '/locks/' in x]) == 1 and len([x for x in paths if '/attempts/' in x]) == 1
    assert all('data:image' not in json.dumps(backend.docs[x]) for x in paths)

    again = start()
    assert again.post('/v1/auth/signin', json={'email': 'saji@example.com', 'password': PASSWORD}).status_code == 200
    assert profile(again, p['id'])['locked'] is True  # a restart locks everything
    assert result_of(attempt(again, p['id'], photos(0, 3))[1])['outcome'] == 'success'


def test_the_key_is_kept_in_the_secrets_folder_when_the_database_is_used(tmp_path):
    from app.locks import resolve_key

    settings = Settings(env='development', palm_key_file=tmp_path / 'secrets' / 'palm-template.key')
    first = resolve_key(settings, persistent=True)
    assert (tmp_path / 'secrets' / 'palm-template.key').read_text().strip() == first
    assert resolve_key(settings, persistent=True) == first
    assert resolve_key(settings, persistent=False) != first  # memory only: a fresh key, nothing written
    (tmp_path / 'secrets' / 'palm-template.key').write_text('not-a-key')
    with pytest.raises(RuntimeError):
        resolve_key(settings, persistent=True)
