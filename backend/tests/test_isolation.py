"""One account never sees another's data.

Alice owns a profile, a reading, a chat and its messages. Everyone else (another account, a guest, a stranger with no
session) is tried against every address that takes an id. The answer is always "no such thing" (404), the very same
answer as for an id that never existed, so nobody can even tell whether an id is real.
"""

from __future__ import annotations

import pytest
from helpers import (
    add_conversation,
    add_profile,
    ask,
    make_reading,
    photo_files,
    sign_up,
    start_guest,
)


@pytest.fixture
def alice(client):
    sign_up(client, 'alice@example.com', 'alice-password', 'Alice')
    profile = add_profile(client, 'Alice')
    reading = make_reading(client, profile['id'])
    convo = add_conversation(client, reading['id'])
    ask(client, convo['id'], 'What does my heart line say?')
    return {'client': client, 'profile': profile, 'reading': reading, 'convo': convo}


@pytest.fixture
def bob(browser):
    c = browser()
    sign_up(c, 'bob@example.com', 'bob-password', 'Bob')
    add_profile(c, 'Bob')
    return c


@pytest.fixture
def guest(browser):
    c = browser()
    start_guest(c)
    add_profile(c, 'Guest')
    return c


def probes(a):
    """Every request that names one of Alice's ids, with what an id that does not exist gets."""
    p, r, c = a['profile']['id'], a['reading']['id'], a['convo']['id']
    return [
        ('GET', f'/v1/readings/{r}', None, '/v1/readings/rd_0000000000000000'),
        ('DELETE', f'/v1/readings/{r}', None, '/v1/readings/rd_0000000000000000'),
        ('POST', f'/v1/readings/{r}/conversations', None, '/v1/readings/rd_0000000000000000/conversations'),
        ('GET', f'/v1/conversations/{c}', None, '/v1/conversations/cnv_0000000000000000'),
        ('POST', f'/v1/conversations/{c}/messages', {'text': 'What does my heart line say?'}, '/v1/conversations/cnv_0000000000000000/messages'),
        ('DELETE', f'/v1/conversations/{c}', None, '/v1/conversations/cnv_0000000000000000'),
        ('PATCH', f'/v1/profiles/{p}', {'name': 'Hacked'}, '/v1/profiles/prf_0000000000000000'),
        ('DELETE', f'/v1/profiles/{p}', None, '/v1/profiles/prf_0000000000000000'),
    ]


@pytest.mark.parametrize('who', ['bob', 'guest'])
def test_someone_elses_ids_are_not_found_and_look_exactly_like_ids_that_do_not_exist(alice, request, who):
    other = request.getfixturevalue(who)
    for method, url, body, missing in probes(alice):
        mine = other.request(method, url, json=body)
        never = other.request(method, missing, json=body)
        assert mine.status_code == 404, (method, url, mine.status_code)
        assert mine.status_code == never.status_code and mine.json() == never.json(), (method, url)  # nothing tells them apart
        assert mine.json()['error']['code'] == 'not_found'


@pytest.mark.parametrize('who', ['bob', 'guest'])
def test_lists_and_filters_only_ever_show_your_own_data(alice, request, who):
    other = request.getfixturevalue(who)
    p, r = alice['profile']['id'], alice['reading']['id']
    assert [x['name'] for x in other.get('/v1/profiles').json()] == ['Bob' if who == 'bob' else 'Guest']
    assert other.get('/v1/readings').json() == []
    assert other.get(f'/v1/readings?profileId={p}').json() == []  # asking for her profile by id shows nothing
    assert other.get('/v1/conversations').json() == []
    assert other.get(f'/v1/conversations?readingId={r}').json() == []
    assert other.get(f'/v1/conversations?profileId={p}').json() == []
    export = other.get('/v1/account/export').json()
    assert len(export['profiles']) == 1 and export['readings'] == [] and export['conversations'] == []
    assert 'Alice' not in other.get('/v1/account/export').text


@pytest.mark.parametrize('who', ['bob', 'guest'])
def test_you_cannot_make_a_reading_for_someone_elses_profile(alice, request, who):
    other = request.getfixturevalue(who)
    r = other.post('/v1/readings', data={'profileId': alice['profile']['id']}, files=photo_files())
    assert r.status_code == 404 and r.json()['error']['code'] == 'not_found'
    assert alice['client'].get('/v1/readings').json()[0]['id'] == alice['reading']['id']  # and Alice's side is unchanged


@pytest.mark.parametrize('who', ['bob', 'guest'])
def test_deleting_all_your_data_deletes_only_your_data(alice, request, who):
    other = request.getfixturevalue(who)
    assert other.delete('/v1/account/data').json() == {'profiles': 1, 'readings': 0, 'conversations': 0, 'messages': 0}
    c = alice['client']
    assert len(c.get('/v1/profiles').json()) == 1 and len(c.get('/v1/readings').json()) == 1
    assert c.get(f'/v1/conversations/{alice["convo"]["id"]}').json()['messageCount'] == 2


def test_nothing_works_without_a_session(alice, client_without_session):
    stranger = client_without_session
    for method, url, body, _ in probes(alice):
        r = stranger.request(method, url, json=body)
        assert r.status_code == 401 and r.json()['error']['code'] == 'unauthorised', (method, url)
    for url in ('/v1/profiles', '/v1/readings', '/v1/conversations', '/v1/account/export'):
        assert stranger.get(url).status_code == 401, url
    assert stranger.delete('/v1/account/data').status_code == 401
    assert stranger.post('/v1/profiles', json={'name': 'X', 'owner': 'self'}).status_code == 401


@pytest.fixture
def client_without_session(browser):
    return browser()


def test_the_same_person_on_another_device_sees_their_data(alice, browser):
    again = browser()
    again.post('/v1/auth/signin', json={'email': 'alice@example.com', 'password': 'alice-password'})
    assert [p['name'] for p in again.get('/v1/profiles').json()] == ['Alice']
    assert again.get(f'/v1/readings/{alice["reading"]["id"]}').json() == alice['reading']  # a positive control for the tests above


def test_signing_out_ends_access_and_a_copied_cookie_stops_working(alice, app, browser):
    token = alice['client'].cookies.get('kiro_session')
    assert token
    thief = browser()
    thief.cookies.set('kiro_session', token)
    assert thief.get('/v1/profiles').status_code == 200  # while the session lives, the cookie is the key...
    alice['client'].post('/v1/auth/signout')
    assert thief.get('/v1/profiles').status_code == 401  # ...and signing out kills it on the server, not just in the browser


def test_signing_in_to_a_second_account_in_one_browser_switches_data(client):
    sign_up(client, 'one@example.com', 'password-one', 'One')
    add_profile(client, 'Only for one')
    client.post('/v1/auth/signout')
    sign_up(client, 'two@example.com', 'password-two', 'Two')
    assert client.get('/v1/profiles').json() == []
    client.post('/v1/auth/signout')
    client.post('/v1/auth/signin', json={'email': 'one@example.com', 'password': 'password-one'})
    assert [p['name'] for p in client.get('/v1/profiles').json()] == ['Only for one']


def test_a_guest_session_is_not_visible_to_a_signed_in_account_except_by_import(alice, browser):
    g = browser()
    start_guest(g)
    add_profile(g, 'Guest only')
    c = alice['client']
    assert [p['name'] for p in c.get('/v1/profiles').json()] == ['Alice']
    assert c.get('/v1/auth/guest/summary').json() is None  # Alice's browser has no guest cookie, so nothing is offered
