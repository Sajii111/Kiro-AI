"""Sessions and accounts: sign-up, sign-in, guest sessions, import."""

from __future__ import annotations

import re

from helpers import (
    add_conversation,
    add_profile,
    ask,
    make_reading,
    sign_up,
    start_guest,
)

from app.core.clock import now_ms


def test_nobody_is_signed_in_at_first(client):
    r = client.get('/v1/session')
    assert r.status_code == 200  # never 401
    assert r.json() == {'session': None}


def test_every_api_answer_is_not_cacheable(client):
    for path in ('/v1/session', '/v1/profiles', '/v1/health', '/v1/nothing-here'):
        assert client.get(path).headers['cache-control'] == 'no-store', path


def test_sign_up_signs_in_and_sets_an_httponly_cookie(client):
    r = client.post('/v1/auth/signup', json={'email': 'saji@example.com', 'password': 'a-long-password', 'displayName': 'Saji'})
    assert r.status_code == 200
    body = r.json()
    assert body['kind'] == 'user' and body['user']['email'] == 'saji@example.com' and body['user']['displayName'] == 'Saji'
    assert 'password' not in r.text
    cookie = r.headers['set-cookie']
    assert 'kiro_session=' in cookie and 'HttpOnly' in cookie and 'Path=/' in cookie and 'SameSite=lax' in cookie
    assert client.get('/v1/session').json() == {'session': body}


def test_sign_up_rules(client):
    ok = {'email': 'a@b.co', 'password': 'long-enough', 'displayName': 'Sam'}
    cases = [
        ({**ok, 'email': 'not-an-email'}, 'email'),
        ({**ok, 'password': 'short'}, '8 characters'),
        ({**ok, 'displayName': '  '}, 'call you'),
        ({**ok, 'displayName': 'x' * 25}, '24 characters'),
    ]
    for body, word in cases:
        r = client.post('/v1/auth/signup', json=body)
        assert r.status_code == 422 and r.json()['error']['code'] == 'invalid', body
        assert word in r.json()['error']['message'], r.json()
    sign_up(client, 'dup@example.com')
    other = client
    r = other.post('/v1/auth/signup', json={'email': 'DUP@example.com', 'password': 'another-password', 'displayName': 'Other'})
    assert r.status_code == 422 and 'already an account' in r.json()['error']['message']  # ignoring case


def test_sign_in_wrong_email_and_wrong_password_look_the_same(client, browser):
    sign_up(client, 'real@example.com', 'the-right-password')
    stranger = browser()
    wrong_password = stranger.post('/v1/auth/signin', json={'email': 'real@example.com', 'password': 'not-the-password'})
    wrong_email = stranger.post('/v1/auth/signin', json={'email': 'nobody@example.com', 'password': 'not-the-password'})
    assert wrong_password.status_code == wrong_email.status_code == 401
    assert wrong_password.json() == wrong_email.json()
    assert wrong_password.json()['error']['code'] == 'unauthorised'
    assert stranger.get('/v1/session').json() == {'session': None}


def test_sign_in_and_sign_out(client, browser):
    user = sign_up(client, 'real@example.com', 'the-right-password')
    other = browser()
    r = other.post('/v1/auth/signin', json={'email': 'Real@Example.com', 'password': 'the-right-password'})
    assert r.status_code == 200 and r.json() == user
    assert other.post('/v1/auth/signout').status_code == 204
    assert other.get('/v1/session').json() == {'session': None}
    assert other.get('/v1/profiles').status_code == 401
    assert client.get('/v1/session').json()['session']['kind'] == 'user'  # the other browser is still signed in


def test_passwords_are_never_kept_as_text(app, client):
    sign_up(client, 'real@example.com', 'a-very-secret-phrase')
    account = app.state.store.find_account('real@example.com')
    assert b'a-very-secret-phrase' not in account.password_hash and len(account.password_hash) == 32 and len(account.salt) == 16


def test_guest_session(client):
    guest = start_guest(client)
    assert guest['kind'] == 'guest' and guest['guestId'].startswith('gst_')
    assert 0 < guest['expiresAt'] - now_ms() <= 2 * 3600 * 1000  # two hours by default
    assert 'kiro_guest' in client.cookies
    assert client.get('/v1/session').json() == {'session': guest}
    assert client.get('/v1/profiles').json() == []


def test_the_guest_cookie_outlives_the_guest_session_so_the_end_can_be_announced(client):
    """A browser deletes a cookie the moment its Max-Age is over. If that were the same moment the session ends, GET /session
    would arrive with no cookie and could never answer guestExpired (the notice "your guest session ended")."""
    r = client.post('/v1/auth/guest')
    max_age = int(re.search(r'Max-Age=(\d+)', r.headers['set-cookie'], re.IGNORECASE).group(1))
    assert max_age > 2 * 3600 + 3600, max_age  # at least an hour longer than the two-hour session


def test_a_browser_that_comes_back_after_the_end_is_told_once_even_if_the_server_already_swept_it(app, client):
    """The sweeper may delete the ended session before the browser asks. The cookie is still sent, so it is still said."""
    guest = start_guest(client)
    add_profile(client)
    app.state.store.guests[guest['guestId']].expires_at = now_ms() - 1
    assert app.state.store.sweep() == 1  # gone, data and all, before anyone asked
    assert client.get('/v1/session').json() == {'session': None, 'guestExpired': True}
    assert client.get('/v1/session').json() == {'session': None}  # and only once


def test_a_guest_can_do_the_whole_workflow(client):
    start_guest(client)
    profile = add_profile(client)
    reading = make_reading(client, profile['id'])
    convo = add_conversation(client, reading['id'])
    assert ask(client, convo['id'], 'Give me a summary')['assistant']['text']
    assert client.get('/v1/profiles').json()[0]['readingCount'] == 1


def test_an_ended_guest_session_answers_410_and_is_said_once(app, client):
    guest = start_guest(client)
    add_profile(client)
    app.state.store.guests[guest['guestId']].expires_at = now_ms() - 1  # time runs out
    r = client.get('/v1/profiles')
    assert r.status_code == 410 and r.json()['error']['code'] == 'expired'
    first = client.get('/v1/session')
    assert first.json() == {'session': None, 'guestExpired': True}
    assert 'kiro_guest=""' in first.headers['set-cookie'] or 'Max-Age=0' in first.headers['set-cookie']  # the stale cookie is cleared
    assert client.get('/v1/session').json() == {'session': None}  # ...so it is only said once
    assert client.get('/v1/profiles').status_code == 401  # and now it is simply "not signed in"


def test_the_sweeper_deletes_ended_guest_sessions(app, client):
    guest = start_guest(client)
    add_profile(client)
    bucket = app.state.store.guests[guest['guestId']].bucket
    app.state.store.guests[guest['guestId']].expires_at = now_ms() - 1
    assert app.state.store.sweep() == 1
    assert guest['guestId'] not in app.state.store.guests
    assert bucket.profiles == []  # the data itself is gone, not just unreachable


def test_signing_out_deletes_the_guest_data_straight_away(app, client):
    guest = start_guest(client)
    add_profile(client)
    assert client.post('/v1/auth/signout').status_code == 204
    assert guest['guestId'] not in app.state.store.guests
    assert client.get('/v1/session').json() == {'session': None}


def test_starting_a_new_guest_session_starts_empty(client):
    first = start_guest(client)
    add_profile(client)
    second = start_guest(client)
    assert second['guestId'] != first['guestId']
    assert client.get('/v1/profiles').json() == []


# ------------------------------------------------------------------ guest -> account


def test_signing_in_does_not_end_the_guest_session_and_a_summary_is_offered(client):
    start_guest(client)
    profile = add_profile(client, 'Nimal', 'other')
    reading = make_reading(client, profile['id'])
    convo = add_conversation(client, reading['id'])
    ask(client, convo['id'], 'What does my heart line say?')
    sign_up(client, 'saji@example.com')
    r = client.get('/v1/auth/guest/summary')
    assert r.status_code == 200
    assert r.json() == {'profiles': 1, 'readings': 1, 'conversations': 1, 'messages': 2}


def test_summary_is_null_when_there_is_nothing_to_offer(client):
    assert client.get('/v1/auth/guest/summary').json() is None  # no guest session at all
    start_guest(client)
    assert client.get('/v1/auth/guest/summary').json() is None  # a guest session with nothing in it


def test_import_copies_with_new_ids_renames_clashes_and_ends_the_guest_session(app, client):
    start_guest(client)
    profile = add_profile(client, 'Nimal', 'other')
    reading = make_reading(client, profile['id'])
    convo = add_conversation(client, reading['id'])
    ask(client, convo['id'], 'What does my heart line say?')
    guest_id = client.get('/v1/session').json()['session']['guestId']

    sign_up(client, 'saji@example.com')
    own = add_profile(client, 'Nimal', 'other')  # the account already has a "Nimal"
    r = client.post('/v1/auth/guest/import')
    assert r.status_code == 200
    assert r.json() == {'profiles': 1, 'readings': 1, 'conversations': 1, 'messages': 2}

    profiles = client.get('/v1/profiles').json()
    assert sorted(p['name'] for p in profiles) == ['Nimal', 'Nimal 2']
    imported = next(p for p in profiles if p['name'] == 'Nimal 2')
    assert imported['id'] not in (profile['id'], own['id'])  # new ids
    assert imported['readingCount'] == 1
    new_reading = client.get(f'/v1/readings?profileId={imported["id"]}').json()[0]
    assert new_reading['id'] != reading['id']
    assert client.get(f'/v1/readings/{new_reading["id"]}').json()['profileId'] == imported['id']
    new_convo = client.get(f'/v1/conversations?readingId={new_reading["id"]}').json()[0]
    assert new_convo['id'] != convo['id'] and new_convo['messageCount'] == 2 and new_convo['profileId'] == imported['id']
    assert [m['role'] for m in client.get(f'/v1/conversations/{new_convo["id"]}').json()['messages']] == ['user', 'assistant']

    # the guest data is gone and the guest cookie is cleared
    assert guest_id not in app.state.store.guests
    assert client.get('/v1/auth/guest/summary').json() is None
    assert client.post('/v1/auth/guest/import').status_code in (404, 410)


def test_import_needs_a_signed_in_session(client):
    start_guest(client)
    add_profile(client)
    r = client.post('/v1/auth/guest/import')
    assert r.status_code == 401 and r.json()['error']['code'] == 'unauthorised'
    assert client.get('/v1/profiles').json()  # the guest data is untouched


def test_import_that_would_go_over_twelve_profiles_copies_nothing(client):
    start_guest(client)
    for i in range(3):
        add_profile(client, f'Guest {chr(65 + i)}', 'other')
    sign_up(client, 'saji@example.com')
    for i in range(10):
        add_profile(client, f'Own {chr(65 + i)}', 'other')
    r = client.post('/v1/auth/guest/import')
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid'
    assert len(client.get('/v1/profiles').json()) == 10  # nothing was copied
    assert client.get('/v1/auth/guest/summary').json()['profiles'] == 3  # and the guest data is still there


def test_discarding_the_guest_session(app, client):
    guest = start_guest(client)
    add_profile(client)
    sign_up(client, 'saji@example.com')
    assert client.delete('/v1/auth/guest').status_code == 204
    assert guest['guestId'] not in app.state.store.guests
    assert client.get('/v1/auth/guest/summary').json() is None
    assert client.delete('/v1/auth/guest').status_code == 204  # saying it twice is fine
