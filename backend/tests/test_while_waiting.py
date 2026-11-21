"""What happens to the data while a slow answer is on its way.

A reading or a chat answer can take many seconds when Gemini is writing it, and the person is not frozen meanwhile: their guest
session may run out, they may delete the chat from another tab, or they may have the website open twice and ask two things at
once. The rule for all of it is the same one: a result is saved only if the place it belongs to is still there, and an error always
means that nothing was saved. Each test makes the world change in the middle of the wait (from inside the fake model, which runs
while the request is waiting) and then looks at what is in the store."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fake_gemini import FakeModel, good, service_for
from fastapi.testclient import TestClient
from helpers import (
    add_conversation,
    add_profile,
    ask,
    make_reading,
    parse_stream,
    photo_files,
    sign_up,
    start_guest,
)
from realapp import drawn_hands, real_client

from app.api import chat as chat_api

HEART = 'What does my heart line traditionally represent?'
HEAD = 'What does my head line traditionally represent?'


def another_tab(client: TestClient) -> TestClient:
    """A second tab of the same browser: its own connection, the same cookies."""
    tab = TestClient(client.app)
    tab.cookies.update(client.cookies)
    return tab


def the_guest(client: TestClient):
    """The one guest session on this server (the test has only made one)."""
    (guest,) = client.app.state.store.guests.values()
    return guest


def is_chat_prompt(prompt: str) -> bool:
    return prompt.startswith('READING')  # a report prompt starts with something else (see fake_gemini.good)


@pytest.fixture
def gemini_chat(settings):
    """A guest on a server with a fake Gemini, with a real reading and an empty chat. `box.during_chat` is called while a chat
    answer is being written (set it in the test); `box.model` is the fake model."""
    box = SimpleNamespace(during_chat=lambda: None)

    def respond(prompt):
        if is_chat_prompt(prompt):
            box.during_chat()
        return good(prompt)

    box.model = FakeModel(respond)
    box.client = real_client(settings, service_for(box.model))
    box.profile = add_profile(box.client, 'Saji')
    hands = drawn_hands()
    r = box.client.post('/v1/readings', data={'profileId': box.profile['id']}, files=photo_files(hands.left, hands.right))
    box.reading = parse_stream(r.text)[-1][1]
    box.convo = add_conversation(box.client, box.reading['id'])
    box.bucket = the_guest(box.client).bucket
    return box


# ------------------------------------------------------------------ a guest session that ends mid-answer


def test_a_guest_session_that_ends_while_gemini_answers_saves_nothing(gemini_chat):
    box = gemini_chat
    box.during_chat = lambda: setattr(the_guest(box.client), 'expires_at', 0)  # time runs out while the answer is being written
    r = box.client.post(f'/v1/conversations/{box.convo["id"]}/messages', json={'text': HEART})
    assert r.status_code == 410 and r.json()['error']['code'] == 'expired'
    assert 'nothing was saved' in r.json()['error']['message']
    assert 'In traditional palmistry' not in r.text  # the answer that was written does not leak into the error
    assert box.bucket.messages == [] and box.bucket.conversation(box.convo['id']).messageCount == 0
    assert box.bucket.model_replies == 1  # the model was asked, and that still counts against the allowance
    assert box.client.get(f'/v1/conversations/{box.convo["id"]}').status_code == 410  # and from now on the session is simply over


def test_the_same_without_gemini(client, monkeypatch):
    """The rule does not depend on Gemini: a guest on a server with no key is treated the same way."""
    start_guest(client)
    reading = make_reading(client, add_profile(client, 'Saji')['id'])
    convo = add_conversation(client, reading['id'])
    guest = the_guest(client)
    real = chat_api.respond

    def slow_then_expire(*args, **kwargs):
        answer = real(*args, **kwargs)
        guest.expires_at = 0
        return answer

    monkeypatch.setattr(chat_api, 'respond', slow_then_expire)
    r = client.post(f'/v1/conversations/{convo["id"]}/messages', json={'text': 'What does my heart line say?'})
    assert r.status_code == 410 and r.json()['error']['code'] == 'expired'
    assert guest.bucket.messages == []


def test_a_guest_who_signs_out_in_another_tab_ends_the_answer_too(gemini_chat):
    """Another way for a guest session to end: signing out. Everything of the guest's is deleted on the spot."""
    box = gemini_chat
    tab_b = another_tab(box.client)
    box.during_chat = lambda: tab_b.post('/v1/auth/signout')
    r = box.client.post(f'/v1/conversations/{box.convo["id"]}/messages', json={'text': HEART})
    assert r.status_code == 410 and r.json()['error']['code'] == 'expired'
    assert box.bucket.messages == []
    assert box.client.app.state.store.guests == {}


def test_a_signed_in_person_is_not_affected(settings):
    """Only guest sessions end by themselves: an account has nothing to check after the answer arrives."""
    client = real_client(settings, service_for(FakeModel()))
    client.post('/v1/auth/signout')  # the guest session the helper started is not wanted here
    sign_up(client)
    profile = add_profile(client, 'Saji')
    hands = drawn_hands()
    reading = parse_stream(client.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(hands.left, hands.right)).text)[-1][1]
    convo = add_conversation(client, reading['id'])
    assert ask(client, convo['id'], HEART)['assistant']['source'] == 'gemini'
    assert client.get(f'/v1/conversations/{convo["id"]}').json()['messageCount'] == 2


# ------------------------------------------------------------------ deleted in another tab while the answer is on its way


@pytest.mark.parametrize('what', ['chat', 'reading', 'profile'])
def test_a_chat_deleted_in_another_tab_while_gemini_answers_gets_no_answer_saved(gemini_chat, what):
    """Deleting a reading or a profile takes its chats with it, so all three leave the answer with nowhere to go."""
    box = gemini_chat
    tab_b = another_tab(box.client)
    url = {'chat': f'/v1/conversations/{box.convo["id"]}', 'reading': f'/v1/readings/{box.reading["id"]}', 'profile': f'/v1/profiles/{box.profile["id"]}'}[what]
    deleted = []
    box.during_chat = lambda: deleted.append(tab_b.delete(url).status_code)
    r = box.client.post(f'/v1/conversations/{box.convo["id"]}/messages', json={'text': HEART})
    assert deleted == [200]
    assert r.status_code == 404 and r.json()['error']['code'] == 'not_found' and 'deleted' in r.json()['error']['message']
    assert box.bucket.messages == [] and box.bucket.conversations == []  # not even a message with no chat to belong to
    assert box.bucket.counts().messages == 0


def test_all_data_deleted_in_another_tab_while_gemini_answers_leaves_nothing_behind(gemini_chat):
    box = gemini_chat
    tab_b = another_tab(box.client)
    box.during_chat = lambda: tab_b.delete('/v1/account/data')
    r = box.client.post(f'/v1/conversations/{box.convo["id"]}/messages', json={'text': HEART})
    assert r.status_code == 404
    assert box.bucket.counts().model_dump() == {'profiles': 0, 'readings': 0, 'conversations': 0, 'messages': 0}


def test_a_reading_still_ends_with_nothing_saved_when_the_guest_signs_out_in_another_tab(settings):
    """The same for a reading, with the second tab ending the session through the website's own sign-out."""
    box = SimpleNamespace()

    def respond(prompt):
        if not is_chat_prompt(prompt):  # the report is being written
            box.tab_b.post('/v1/auth/signout')
        return good(prompt)

    client = real_client(settings, service_for(FakeModel(respond)))
    box.tab_b = another_tab(client)
    profile = add_profile(client, 'Saji')
    hands = drawn_hands()
    bucket = the_guest(client).bucket
    r = client.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(hands.left, hands.right))
    events = parse_stream(r.text)
    assert events[-1][0] == 'error' and events[-1][1]['code'] == 'expired'
    assert 'reading' not in [name for name, _ in events] and bucket.readings == []
    assert box.tab_b.get('/v1/session').json() == {'session': None}


# ------------------------------------------------------------------ two tabs of the same session, working at once


def run_together(*jobs):
    """Runs the jobs at the same time, each in its own thread, and returns what each one returned."""
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(job) for job in jobs]
        return [f.result(timeout=60) for f in futures]


def test_two_tabs_can_each_make_a_reading_at_the_same_moment(settings):
    """Both readings are inside Gemini at the same time (the fake model makes each wait for the other), and both are kept."""
    both_inside = threading.Barrier(2, timeout=20)

    def respond(prompt):
        if not is_chat_prompt(prompt):
            both_inside.wait()  # only returns when the other tab's report is being written as well
        return good(prompt)

    client = real_client(settings, service_for(FakeModel(respond)))
    tab_b = another_tab(client)
    saji, nimali = add_profile(client, 'Saji'), add_profile(client, 'Nimali')
    hands = drawn_hands()

    def reading(tab, profile):
        return lambda: parse_stream(tab.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(hands.left, hands.right)).text)

    first, second = run_together(reading(client, saji), reading(tab_b, nimali))
    assert first[-1][0] == 'reading' and second[-1][0] == 'reading'
    one, two = first[-1][1], second[-1][1]
    assert one['id'] != two['id'] and {one['profileId'], two['profileId']} == {saji['id'], nimali['id']}
    assert one['meta']['provider'] == 'gemini' and two['meta']['provider'] == 'gemini'  # neither fell back: both really were in Gemini together
    listed = client.get('/v1/readings').json()
    assert {r['id'] for r in listed} == {one['id'], two['id']} and {r['id'] for r in tab_b.get('/v1/readings').json()} == {one['id'], two['id']}
    assert {p['name']: p['readingCount'] for p in tab_b.get('/v1/profiles').json()} == {'Saji': 1, 'Nimali': 1}


def test_two_tabs_asking_in_the_same_chat_at_once_each_get_their_own_answer_and_the_pairs_stay_together(settings):
    both_inside = threading.Barrier(2, timeout=20)

    def respond(prompt):
        if is_chat_prompt(prompt):
            both_inside.wait()
        return good(prompt)

    client = real_client(settings, service_for(FakeModel(respond)))
    tab_b = another_tab(client)
    profile = add_profile(client, 'Saji')
    hands = drawn_hands()
    reading = parse_stream(client.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(hands.left, hands.right)).text)[-1][1]
    convo = add_conversation(client, reading['id'])

    first, second = run_together(lambda: ask(client, convo['id'], HEART), lambda: ask(tab_b, convo['id'], HEAD))
    assert first['assistant']['refs']['featureIds'] == ['heart'] and second['assistant']['refs']['featureIds'] == ['head']  # each answer is about its own question
    assert first['assistant']['source'] == 'gemini' and second['assistant']['source'] == 'gemini'

    stored = client.get(f'/v1/conversations/{convo["id"]}').json()
    ids = [m['id'] for m in stored['messages']]
    pairs = [[first['user']['id'], first['assistant']['id']], [second['user']['id'], second['assistant']['id']]]
    assert ids in (pairs[0] + pairs[1], pairs[1] + pairs[0])  # a question is always followed by its own answer, never by the other tab's
    assert stored['messageCount'] == 4 and [m['role'] for m in stored['messages']] == ['user', 'assistant', 'user', 'assistant']
    assert the_guest(client).bucket.model_replies == 2


def test_a_second_tab_can_ask_about_a_reading_the_first_tab_has_just_made(settings):
    client = real_client(settings, service_for(FakeModel()))
    tab_b = another_tab(client)
    profile = add_profile(client, 'Saji')
    assert tab_b.get('/v1/readings').json() == []  # nothing yet
    hands = drawn_hands()
    reading = parse_stream(client.post('/v1/readings', data={'profileId': profile['id']}, files=photo_files(hands.left, hands.right)).text)[-1][1]
    assert [r['id'] for r in tab_b.get('/v1/readings').json()] == [reading['id']]  # the other tab sees it as soon as it is saved
    convo = add_conversation(tab_b, reading['id'])
    assert ask(tab_b, convo['id'], HEART)['assistant']['refs']['featureIds'] == ['heart']
    assert client.get(f'/v1/conversations/{convo["id"]}').json()['messageCount'] == 2


def test_two_tabs_do_not_share_a_session_with_a_third_person(settings):
    """Tabs share a session only through the cookie: someone else's browser still sees nothing of it."""
    client = real_client(settings, service_for(FakeModel()))
    tab_b = another_tab(client)
    add_profile(client, 'Saji')
    stranger = TestClient(client.app)
    start_guest(stranger)
    assert [p['name'] for p in tab_b.get('/v1/profiles').json()] == ['Saji']
    assert stranger.get('/v1/profiles').json() == []
