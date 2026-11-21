"""Accounts kept in the online database (store/persist.py, store/firestore.py, store/build.py).

The database is replaced by a dictionary (FakeBackend), so nothing here reaches Google. What is tested is what a person would
notice: an account, its sign-in and everything it owns are still there after the server restarts; deletes really delete;
guests are never saved; no photo, no password and no sign-in token is ever written; and a database that is down costs an
error message, never a half-made account.
"""

from __future__ import annotations

import json

import pytest
from fake_firebase import PROJECT, FakeBackend, private_key_text, write_key_file
from fastapi.testclient import TestClient
from helpers import (
    add_conversation,
    add_profile,
    ask,
    make_reading,
    sign_up,
    start_guest,
)

from app.core.clock import now_ms
from app.core.config import Settings, read_settings
from app.main import create_app
from app.store import firestore as fs
from app.store.build import StorageNotReady, build_store, check_key, storage_name
from app.store.memory import MemoryStore
from app.store.persist import PersistentStore, StorageUnavailable, email_key, token_key

PASSPHRASE = 'a-long-password'


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def server(settings, backend):
    """Starts a server on the same database, as many times as a test likes (each call is a restart)."""

    def start():
        app = create_app(settings)
        app.state.store = PersistentStore(settings.guest_minutes, settings.signin_days, backend)
        return app

    return start


def user_id_of(backend) -> str:
    users = [p for p in backend.docs if p.startswith('users/') and p.count('/') == 1]
    assert len(users) == 1, users
    return users[0].split('/')[1]


# ------------------------------------------------------------------ what survives a restart


def test_an_account_and_everything_it_owns_are_there_after_a_restart(server, backend):
    first = TestClient(server())
    sign_up(first)
    profile = add_profile(first, name='Saji')
    reading = make_reading(first, profile['id'])
    convo = add_conversation(first, reading['id'])
    ask(first, convo['id'], 'Summarise this reading')
    cookies = dict(first.cookies)

    again = TestClient(server(), cookies=cookies)  # the same browser, after the server restarted
    me = again.get('/v1/session').json()['session']
    assert me['user']['email'] == 'saji@example.com'
    profiles = again.get('/v1/profiles').json()
    assert [p['name'] for p in profiles] == ['Saji'] and profiles[0]['readingCount'] == 1
    stored = again.get(f'/v1/readings/{reading["id"]}').json()
    assert stored['report'] == reading['report'] and stored['hands'] == reading['hands']
    messages = again.get(f'/v1/conversations/{convo["id"]}').json()['messages']
    assert [m['role'] for m in messages] == ['user', 'assistant'] and messages[0]['text'] == 'Summarise this reading'


def test_every_message_is_a_document_of_its_own_and_comes_back_in_order(server, backend):
    first = TestClient(server())
    sign_up(first)
    reading = make_reading(first, add_profile(first)['id'])
    convo = add_conversation(first, reading['id'])
    for question in ('Summarise this reading', 'What does the heart line show?', 'What is the life line?'):
        ask(first, convo['id'], question)
    before = first.get(f'/v1/conversations/{convo["id"]}').json()['messages']
    uid = user_id_of(backend)
    chat = f'users/{uid}/conversations/{convo["id"]}'
    assert backend.docs[chat]['messageCount'] == 6 and 'messages' not in backend.docs[chat]
    stored = backend.under(f'{chat}/messages/')
    assert sorted(stored) == sorted(f'{chat}/messages/{m["id"]}' for m in before)
    assert {backend.docs[p]['role'] for p in stored} == {'user', 'assistant'} and all('createdAt' in backend.docs[p] for p in stored)
    after = TestClient(server(), cookies=dict(first.cookies)).get(f'/v1/conversations/{convo["id"]}').json()['messages']
    assert after == before


def test_a_long_chat_never_makes_a_document_too_big_for_firestore(settings, backend):
    import asyncio

    from app.schemas import Conversation, Message

    store = PersistentStore(settings.guest_minutes, settings.signin_days, backend)
    account = store.add_account('a@example.com', 'A', b'salt', b'hash')
    bucket = store.bucket_of_user(account.id)
    longest = 'අ' * 5000  # the longest question the chat takes, in a script that needs 3 bytes a letter
    bucket.conversations.append(Conversation(id='cnv_1', readingId='rdg_1', profileId='prf_1', title='Long', createdAt='2026-11-21T00:00:00.000Z',
                                             updatedAt='2026-11-21T00:00:00.000Z', messageCount=200))
    bucket.messages = [Message(id=f'msg_{i:03d}', conversationId='cnv_1', role='user' if i % 2 == 0 else 'assistant', text=longest,
                               createdAt=f'2026-11-21T00:00:{i // 10:02d}.{i % 10:03d}Z') for i in range(200)]  # about 3 MB of chat
    assert asyncio.run(store.flush()), 'a long chat could not be saved'
    assert len(backend.under(f'users/{account.id}/conversations/cnv_1/messages/')) == 200 and backend.biggest < 100_000
    again = PersistentStore(settings.guest_minutes, settings.signin_days, backend)
    assert [m.id for m in again.bucket_of_user(account.id).messages] == [f'msg_{i:03d}' for i in range(200)]


def test_signing_in_after_a_restart_finds_the_account_by_its_e_mail(server):
    sign_up(TestClient(server()), email='Saji@Example.com')
    fresh = TestClient(server())
    r = fresh.post('/v1/auth/signin', json={'email': 'saji@example.com', 'password': PASSPHRASE})
    assert r.status_code == 200, r.text
    wrong = TestClient(server()).post('/v1/auth/signin', json={'email': 'saji@example.com', 'password': 'not-the-password'})
    assert wrong.status_code == 401


def test_the_same_e_mail_cannot_sign_up_twice_even_after_a_restart(server):
    sign_up(TestClient(server()))
    r = TestClient(server()).post('/v1/auth/signup', json={'email': 'saji@example.com', 'password': PASSPHRASE, 'displayName': 'Other'})
    assert r.status_code == 422 and 'already an account' in r.json()['error']['message']


def test_the_chat_answer_count_is_kept_too(settings, backend):
    store = PersistentStore(settings.guest_minutes, settings.signin_days, backend)
    account = store.add_account('a@example.com', 'A', b'salt', b'hash')
    store.bucket_of_user(account.id).model_replies = 7
    import asyncio

    assert asyncio.run(store.flush())
    assert backend.docs[f'users/{account.id}']['modelReplies'] == 7
    again = PersistentStore(settings.guest_minutes, settings.signin_days, backend)
    assert again.bucket_of_user(account.id).model_replies == 7


# ------------------------------------------------------------------ what is written, and what never is


def test_no_password_token_or_photo_is_ever_written(server, backend):
    client = TestClient(server())
    sign_up(client, password=PASSPHRASE)
    profile = add_profile(client)
    make_reading(client, profile['id'])
    token = client.cookies.get('kiro_session')
    everything = json.dumps(backend.docs)
    assert PASSPHRASE not in everything
    assert token and token not in everything and f'sessions/{token_key(token)}' in backend.docs
    for marker in ('data:image', '/9j/', 'iVBORw0KGgo'):  # a data URL, the start of a JPEG and of a PNG in base64
        assert marker not in everything
    user = backend.docs[f'users/{user_id_of(backend)}']
    assert set(user) == {'email', 'emailLower', 'displayName', 'salt', 'passwordHash', 'createdAt', 'modelReplies'}
    assert backend.docs[f'emails/{email_key("saji@example.com")}']['userId'] == user_id_of(backend)


def test_each_document_has_plain_fields_to_read_in_the_console(server, backend):
    client = TestClient(server())
    sign_up(client)
    profile = add_profile(client, name='Ama')
    reading = make_reading(client, profile['id'])
    uid = user_id_of(backend)
    assert backend.docs[f'users/{uid}/profiles/{profile["id"]}']['name'] == 'Ama'
    doc = backend.docs[f'users/{uid}/readings/{reading["id"]}']
    assert doc['profileId'] == profile['id'] and doc['createdAt'] == reading['createdAt'] and json.loads(doc['data'])['id'] == reading['id']


def test_guest_sessions_are_never_written(server, backend):
    client = TestClient(server())
    start_guest(client)
    profile = add_profile(client)
    reading = make_reading(client, profile['id'])
    ask(client, add_conversation(client, reading['id'])['id'], 'Summarise this reading')
    assert backend.docs == {}


def test_a_guest_who_signs_up_and_copies_their_readings_has_them_saved(server, backend):
    client = TestClient(server())
    start_guest(client)
    profile = add_profile(client)
    make_reading(client, profile['id'])
    sign_up(client)
    r = client.post('/v1/auth/guest/import')
    assert r.status_code == 200, r.text
    uid = user_id_of(backend)
    assert len(backend.under(f'users/{uid}/profiles/')) == 1 and len(backend.under(f'users/{uid}/readings/')) == 1


# ------------------------------------------------------------------ deletes really delete


def test_deleting_a_profile_deletes_its_readings_and_chats_from_the_database(server, backend):
    client = TestClient(server())
    sign_up(client)
    keep = add_profile(client, name='Keep')
    gone = add_profile(client, name='Gone')
    make_reading(client, keep['id'])
    reading = make_reading(client, gone['id'])
    add_conversation(client, reading['id'])
    uid = user_id_of(backend)
    assert len(backend.under(f'users/{uid}/conversations/')) == 1
    assert client.delete(f'/v1/profiles/{gone["id"]}').status_code == 200
    assert backend.under(f'users/{uid}/profiles/') == [f'users/{uid}/profiles/{keep["id"]}']
    assert len(backend.under(f'users/{uid}/readings/')) == 1 and backend.under(f'users/{uid}/conversations/') == []


def test_deleting_a_chat_deletes_its_messages_first(server, backend):
    client = TestClient(server())
    sign_up(client)
    reading = make_reading(client, add_profile(client)['id'])
    convo = add_conversation(client, reading['id'])
    ask(client, convo['id'], 'Summarise this reading')
    uid = user_id_of(backend)
    order = []
    commit = backend.commit
    backend.commit = lambda writes: (order.extend(p for kind, p, _ in writes if kind == 'delete'), commit(writes))
    assert client.delete(f'/v1/conversations/{convo["id"]}').status_code in (200, 204)
    assert backend.under(f'users/{uid}/conversations/') == []
    assert len(order) == 3 and order[-1] == f'users/{uid}/conversations/{convo["id"]}'  # two messages, then the chat


def test_deleting_all_data_empties_the_account_but_keeps_the_account(server, backend):
    client = TestClient(server())
    sign_up(client)
    make_reading(client, add_profile(client)['id'])
    uid = user_id_of(backend)
    assert client.delete('/v1/account/data').status_code == 200
    assert backend.under(f'users/{uid}/') == []
    assert f'users/{uid}' in backend.docs


def test_signing_out_deletes_the_sign_in(server, backend):
    client = TestClient(server())
    sign_up(client)
    assert any(p.startswith('sessions/') for p in backend.docs)
    client.post('/v1/auth/signout')
    assert not any(p.startswith('sessions/') for p in backend.docs)


def test_a_sign_in_that_has_run_out_is_refused_and_removed(settings, backend):
    store = PersistentStore(settings.guest_minutes, settings.signin_days, backend)
    account = store.add_account('a@example.com', 'A', b'salt', b'hash')
    token = store.start_sign_in(account.id)
    backend.docs[f'sessions/{token_key(token)}']['expiresAt'] = now_ms() - 1
    later = PersistentStore(settings.guest_minutes, settings.signin_days, backend)
    assert later.account_for(token) is None
    assert f'sessions/{token_key(token)}' not in backend.docs


# ------------------------------------------------------------------ when the database is down


def test_a_database_that_is_down_makes_sign_up_fail_cleanly_and_leaves_no_half_made_account(server, backend):
    app = server()
    client = TestClient(app)
    backend.down = True
    r = client.post('/v1/auth/signup', json={'email': 'saji@example.com', 'password': PASSPHRASE, 'displayName': 'Saji'})
    assert r.status_code == 503
    assert r.json()['error']['message'] == 'The account database could not be reached just now. Please try again in a moment.'
    backend.down = False
    sign_up(client)  # the same e-mail works once the database is back


def test_an_account_that_cannot_be_read_after_a_restart_gets_the_same_plain_error(server, backend):
    first = TestClient(server())
    sign_up(first)
    backend.down = True
    again = TestClient(server(), cookies=dict(first.cookies))
    r = again.get('/v1/profiles')
    assert r.status_code == 503 and r.json()['error']['message'].startswith('The account database could not be reached')
    backend.down = False
    assert again.get('/v1/profiles').status_code == 200  # nothing was lost: the same cookie works once the database is back


def test_a_change_that_could_not_be_saved_is_saved_on_the_next_request(server, backend):
    app = server()
    client = TestClient(app)
    sign_up(client)
    uid = user_id_of(backend)
    backend.down = True
    profile = add_profile(client, name='Later')  # answered from memory as usual
    assert app.state.store.failed_flushes == 1 and backend.under(f'users/{uid}/profiles/') == []
    backend.down = False
    add_profile(client, name='Next')
    names = sorted(backend.docs[p]['name'] for p in backend.under(f'users/{uid}/profiles/'))
    assert names == ['Later', 'Next'] and profile['name'] == 'Later'


def test_one_account_whose_changes_are_refused_never_holds_up_another(server, backend):
    app = server()
    ama, ben = TestClient(app), TestClient(app)
    sign_up(ama, email='ama@example.com')
    ama_id = user_id_of(backend)
    sign_up(ben, email='ben@example.com')
    backend.refuse.add(f'users/{ama_id}/')
    add_profile(ama, name='Refused')
    add_profile(ben, name='Saved')  # this request's save tries Ama's batch again, and saves Ben's all the same
    ben_id = next(p.split('/')[1] for p in backend.docs if p.startswith('users/') and p.count('/') == 1 and p != f'users/{ama_id}')
    assert [backend.docs[p]['name'] for p in backend.under(f'users/{ben_id}/profiles/')] == ['Saved']
    assert backend.under(f'users/{ama_id}/profiles/') == [] and app.state.store.failed_flushes >= 2
    backend.refuse.clear()
    add_profile(ben, name='Again')
    assert [backend.docs[p]['name'] for p in backend.under(f'users/{ama_id}/profiles/')] == ['Refused']


def test_the_health_check_says_where_accounts_are_kept(server, client):
    assert TestClient(server()).get('/v1/health').json()['storage'] == 'firestore'
    assert client.get('/v1/health').json()['storage'] == 'memory'


# ------------------------------------------------------------------ choosing the store


def test_storage_is_memory_unless_a_key_is_there(tmp_path, monkeypatch):
    monkeypatch.setenv('STORAGE', 'auto')
    monkeypatch.setenv('FIREBASE_KEY', str(tmp_path / 'missing.json'))
    settings = read_settings()
    assert settings.storage == 'auto'
    assert storage_name(build_store(settings)) == 'memory'
    assert Settings().storage == 'memory'  # what every other test uses


def test_an_unusable_key_falls_back_to_memory_in_auto_and_stops_the_server_when_firestore_is_asked_for(tmp_path):
    bad = tmp_path / 'firebase-service-account.json'
    bad.write_text('{"type": "authorized_user"}')
    assert isinstance(build_store(Settings(storage='auto', firebase_key=bad)), MemoryStore)
    with pytest.raises(StorageNotReady, match='not a service account key'):
        build_store(Settings(storage='firestore', firebase_key=bad))
    with pytest.raises(StorageNotReady, match='there is no key file'):
        build_store(Settings(storage='firestore', firebase_key=tmp_path / 'nope.json'))


def test_a_usable_key_makes_the_server_keep_accounts_in_that_project(tmp_path, monkeypatch):
    key = write_key_file(tmp_path / 'firebase-service-account.json')
    store = build_store(Settings(storage='auto', firebase_key=key))
    assert storage_name(store) == 'firestore'
    assert store.backend.project_id == PROJECT and store.backend.root == f'projects/{PROJECT}/databases/(default)/documents'
    named = build_store(Settings(storage='firestore', firebase_key=key, firestore_database='kiro-db'))
    assert named.backend.root == f'projects/{PROJECT}/databases/kiro-db/documents'  # nothing has been sent: no request was made
    monkeypatch.setenv('FIRESTORE_DATABASE', 'kiro-db')
    assert read_settings().firestore_database == 'kiro-db'
    monkeypatch.delenv('FIRESTORE_DATABASE')
    assert read_settings().firestore_database == '(default)'


def test_a_key_whose_private_key_cannot_be_read_is_never_used(tmp_path):
    key = write_key_file(tmp_path / 'firebase-service-account.json', private_key='cut short')
    assert storage_name(build_store(Settings(storage='auto', firebase_key=key))) == 'memory'
    with pytest.raises(StorageNotReady, match='holds a key that cannot be read'):
        build_store(Settings(storage='firestore', firebase_key=key))
    write_key_file(key, token_uri=None)  # a part Google's library needs is missing
    assert check_key(Settings(firebase_key=key)) == ('', 'firebase-service-account.json holds a key that cannot be read (was the file edited or cut short?)')


def test_the_key_check_names_the_project_or_the_problem_and_never_the_key(tmp_path):
    key = write_key_file(tmp_path / 'firebase-service-account.json')
    assert check_key(Settings(firebase_key=key)) == (PROJECT, '')
    project, problem = check_key(Settings(firebase_key=tmp_path / 'missing.json'))
    assert project == '' and problem.startswith('there is no key file at')
    key.write_text('{"type": "authorized_user"}')
    assert 'not a service account key' in check_key(Settings(firebase_key=key))[1]
    for text in (project, problem):
        assert private_key_text() not in text and 'PRIVATE KEY' not in text


def test_the_tests_themselves_never_use_a_real_database():
    assert read_settings().storage == 'memory'


# ------------------------------------------------------------------ the Firestore REST calls


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body


class Session:
    """Records every request and answers from a list."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.sent = []

    def request(self, method, url, json=None, timeout=None):
        self.sent.append((method, url, json, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


ROOT = 'projects/p1/databases/(default)/documents'


def test_values_go_to_firestore_and_back_unchanged():
    doc = {'name': 'Ama', 'count': 3, 'ok': True, 'none': None, 'ratio': 0.5, 'text': 'é ✓'}
    assert fs.from_fields(fs.to_fields(doc)) == doc
    assert fs.to_fields({'count': 3})['count'] == {'integerValue': '3'}
    with pytest.raises(TypeError):
        fs.encode([1, 2])


def test_get_reads_one_document_and_says_none_when_there_is_none():
    session = Session([Response(200, {'fields': {'userId': {'stringValue': 'usr_1'}}}), Response(404)])
    db = fs.FirestoreBackend('p1', session)
    assert db.get('emails/abc') == {'userId': 'usr_1'}
    assert db.get('emails/missing') is None
    assert session.sent[0][:2] == ('GET', f'{fs.API}/{ROOT}/emails/abc') and session.sent[0][3] == fs.TIMEOUT_S


def test_list_follows_every_page():
    page1 = {'documents': [{'name': f'{ROOT}/users/u/profiles/a', 'fields': {'name': {'stringValue': 'A'}}}], 'nextPageToken': 't2'}
    page2 = {'documents': [{'name': f'{ROOT}/users/u/profiles/b', 'fields': {'name': {'stringValue': 'B'}}}]}
    session = Session([Response(200, page1), Response(200, page2)])
    assert fs.FirestoreBackend('p1', session).list('users/u/profiles') == [('a', {'name': 'A'}), ('b', {'name': 'B'})]
    assert session.sent[1][1].endswith('&pageToken=t2')


def test_a_commit_too_big_for_one_request_is_sent_in_several():
    session = Session([Response(200)] * 4)
    big = 'x' * 900_000
    fs.FirestoreBackend('p1', session).commit([('set', f'users/u/readings/{i}', {'data': big}) for i in range(10)])
    sizes = [len(sent[2]['writes']) for sent in session.sent]
    assert sum(sizes) == 10 and len(sizes) == 3 and max(sizes) == 4  # about 4 MB a request, well under Firestore's 10 MiB


def test_commit_sends_whole_documents_and_deletes_in_pages_of_500():
    session = Session([Response(200), Response(200)])
    writes = [('set', f'users/u/profiles/{i}', {'name': f'P{i}'}) for i in range(500)] + [('delete', 'sessions/x', None)]
    fs.FirestoreBackend('p1', session).commit(writes)
    first, second = session.sent[0][2]['writes'], session.sent[1][2]['writes']
    assert len(first) == 500 and first[0] == {'update': {'name': f'{ROOT}/users/u/profiles/0', 'fields': {'name': {'stringValue': 'P0'}}}}
    assert second == [{'delete': f'{ROOT}/sessions/x'}]
    assert session.sent[0][1] == f'{fs.API}/{ROOT}:commit'


def test_a_database_that_does_not_exist_is_an_error_not_an_empty_answer():
    missing = {'error': {'code': 404, 'status': 'NOT_FOUND', 'message': 'The database (default) does not exist for project p1'}}
    with pytest.raises(StorageUnavailable, match='HTTP 404 NOT_FOUND: The database .default. does not exist'):
        fs.FirestoreBackend('p1', Session([Response(404, missing)])).get('emails/abc')
    with pytest.raises(StorageUnavailable, match='does not exist'):
        fs.FirestoreBackend('p1', Session([Response(404, missing)])).list('users')
    no_document = {'error': {'code': 404, 'status': 'NOT_FOUND', 'message': f'Document "{ROOT}/emails/abc" not found.'}}
    assert fs.FirestoreBackend('p1', Session([Response(404, no_document)])).get('emails/abc') is None


def test_a_key_google_refuses_is_said_to_be_refused():
    from google.auth import exceptions as auth_errors

    refused = Session([auth_errors.RefreshError('invalid_grant: Invalid JWT Signature.', {'error': 'invalid_grant'})])
    with pytest.raises(StorageUnavailable, match=r'Google refused the key \(RefreshError: invalid_grant: Invalid JWT Signature.\)'):
        fs.FirestoreBackend('p1', refused).get('users/u')
    offline = Session([auth_errors.TransportError('no route to host')])
    with pytest.raises(StorageUnavailable, match=r'could not be reached \(TransportError\)'):
        fs.FirestoreBackend('p1', offline).get('users/u')


def test_a_refusal_or_no_network_becomes_storage_unavailable_with_a_plain_reason():
    import requests

    refused = Session([Response(403, {'error': {'status': 'PERMISSION_DENIED', 'message': 'Missing or insufficient permissions.'}})])
    with pytest.raises(StorageUnavailable, match='HTTP 403 PERMISSION_DENIED'):
        fs.FirestoreBackend('p1', refused).get('users/u')
    offline = Session([requests.ConnectionError('no route to host')])
    with pytest.raises(StorageUnavailable, match=r'could not be reached \(ConnectionError\)'):
        fs.FirestoreBackend('p1', offline).commit([('delete', 'sessions/x', None)])


def test_the_key_file_is_checked_before_anything_is_sent(tmp_path):
    path = tmp_path / 'key.json'
    path.write_text('not json')
    with pytest.raises(ValueError, match='not a readable JSON key file'):
        fs.read_key_file(path)
    path.write_text(json.dumps({'type': 'service_account', 'project_id': 'p1', 'client_email': 'x@p1.iam.gserviceaccount.com'}))
    with pytest.raises(ValueError, match='has no private_key'):
        fs.read_key_file(path)
