"""Hand profiles."""

from __future__ import annotations

import pytest
from helpers import add_conversation, add_profile, ask, make_reading, start_guest


@pytest.fixture
def guest(client):
    start_guest(client)
    return client


def test_a_profile_is_created_listed_renamed_and_deleted(guest):
    p = add_profile(guest, '  Saji  ')
    assert p['name'] == 'Saji' and p['owner'] == 'self' and p['consent'] is True
    assert p['readingCount'] == 0 and p['lastReadingAt'] is None and p['id'].startswith('prf_')
    assert guest.get('/v1/profiles').json() == [p]

    r = guest.patch(f'/v1/profiles/{p["id"]}', json={'name': 'Saji K'})
    assert r.status_code == 200 and r.json()['name'] == 'Saji K' and r.json()['id'] == p['id']

    r = guest.delete(f'/v1/profiles/{p["id"]}')
    assert r.status_code == 200 and r.json() == {'profiles': 1, 'readings': 0, 'conversations': 0, 'messages': 0}
    assert guest.get('/v1/profiles').json() == []


def test_profiles_are_listed_oldest_first(guest):
    for name in ('Charlie', 'Alice', 'Bob'):
        add_profile(guest, name, 'other')
    assert [p['name'] for p in guest.get('/v1/profiles').json()] == ['Charlie', 'Alice', 'Bob']


@pytest.mark.parametrize(
    'name, word',
    [
        ('', 'name'),
        ('   ', 'name'),
        ('x' * 25, '24 characters'),
        ('saji@example.com', 'symbols'),
        ('Saji <b>', 'symbols'),
        ('0771234567', 'phone number'),
        ('Nimal 12345', 'phone number'),
    ],
)
def test_bad_names_are_refused_with_a_sentence(guest, name, word):
    r = guest.post('/v1/profiles', json={'name': name, 'owner': 'self', 'consent': True})
    assert r.status_code == 422
    assert r.json()['error']['code'] == 'invalid' and word in r.json()['error']['message']


@pytest.mark.parametrize('name', ['Saji', 'Nimal Perera', "O'Neil", 'Mary-Ann', 'J. Silva', 'Zoë', 'Ṣaji'])
def test_ordinary_names_are_accepted(guest, name):
    r = guest.post('/v1/profiles', json={'name': name, 'owner': 'other', 'consent': True})
    assert r.status_code == 201, r.text


def test_names_are_unique_ignoring_case_and_spaces_at_the_edges(guest):
    add_profile(guest, 'Nimal', 'other')
    r = guest.post('/v1/profiles', json={'name': ' NIMAL ', 'owner': 'other', 'consent': True})
    assert r.status_code == 422 and 'already have a profile' in r.json()['error']['message']
    other = add_profile(guest, 'Kamal', 'other')
    r = guest.patch(f'/v1/profiles/{other["id"]}', json={'name': 'nimal'})
    assert r.status_code == 422
    r = guest.patch(f'/v1/profiles/{other["id"]}', json={'name': 'KAMAL'})  # renaming to itself in another case is fine
    assert r.status_code == 200


def test_someone_else_needs_to_have_agreed(guest):
    r = guest.post('/v1/profiles', json={'name': 'Nimal', 'owner': 'other', 'consent': False})
    assert r.status_code == 422 and 'agreed' in r.json()['error']['message']
    r = guest.post('/v1/profiles', json={'name': 'Nimal', 'owner': 'other'})
    assert r.status_code == 422
    r = guest.post('/v1/profiles', json={'name': 'Me', 'owner': 'self', 'consent': False})
    assert r.status_code == 201 and r.json()['consent'] is True  # your own hands: stored as consented


def test_at_most_twelve_profiles(guest):
    for i in range(12):
        add_profile(guest, f'Person {chr(65 + i)}', 'other')
    r = guest.post('/v1/profiles', json={'name': 'One more', 'owner': 'other', 'consent': True})
    assert r.status_code == 422 and '12' in r.json()['error']['message']


def test_a_wrong_body_is_a_422_with_a_sentence(guest):
    for body in ({}, {'name': 'X'}, {'name': 'X', 'owner': 'robot'}, {'name': 5, 'owner': 'self'}):
        r = guest.post('/v1/profiles', json=body)
        assert r.status_code == 422 and r.json()['error']['code'] == 'invalid' and r.json()['error']['message'], body


def test_unknown_profile_is_404(guest):
    assert guest.patch('/v1/profiles/prf_nope', json={'name': 'X'}).status_code == 404
    assert guest.delete('/v1/profiles/prf_nope').status_code == 404


def test_deleting_a_profile_cascades_and_counts_what_went(guest):
    keep = add_profile(guest, 'Keep', 'other')
    drop = add_profile(guest, 'Drop', 'other')
    keep_reading = make_reading(guest, keep['id'])
    r1, r2 = make_reading(guest, drop['id']), make_reading(guest, drop['id'])
    c1 = add_conversation(guest, r1['id'])
    ask(guest, c1['id'], 'Summary please')
    ask(guest, c1['id'], 'What about the heart line?')
    add_conversation(guest, r2['id'])
    kept_convo = add_conversation(guest, keep_reading['id'])
    ask(guest, kept_convo['id'], 'Hello')

    assert guest.get('/v1/profiles').json()[1]['readingCount'] == 2
    r = guest.delete(f'/v1/profiles/{drop["id"]}')
    assert r.json() == {'profiles': 1, 'readings': 2, 'conversations': 2, 'messages': 4}
    for gone in (r1['id'], r2['id']):
        assert guest.get(f'/v1/readings/{gone}').status_code == 404
    assert guest.get(f'/v1/conversations/{c1["id"]}').status_code == 404
    # what belongs to the other profile is untouched
    assert guest.get(f'/v1/readings/{keep_reading["id"]}').status_code == 200
    assert guest.get(f'/v1/conversations/{kept_convo["id"]}').json()['messageCount'] == 2
    export = guest.get('/v1/account/export').json()
    assert len(export['profiles']) == 1 and len(export['readings']) == 1 and len(export['conversations']) == 1


def test_profile_counts_follow_the_readings(guest):
    p = add_profile(guest)
    first = make_reading(guest, p['id'])
    second = make_reading(guest, p['id'])
    listed = guest.get('/v1/profiles').json()[0]
    assert listed['readingCount'] == 2
    assert listed['lastReadingAt'] == max(first['createdAt'], second['createdAt'])
