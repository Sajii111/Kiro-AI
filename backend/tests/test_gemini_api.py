"""Gemini through the API: a real reading and a chat on a server that has a (fake) language model, a server that has none, and
a server whose model fails. These check the parts the unit tests cannot: what the stream says, what is stored, what the
person is told, and that nothing blocks."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fake_gemini import FakeModel, good_answer, service_for, unavailable
from helpers import add_conversation, ask
from realapp import real_client, real_reading

from app.core.config import Settings

QUESTION = 'What does my heart line traditionally represent?'


def stage_details(events):
    return {d['stage']: d.get('detail') for n, d in events if n == 'stage' and d['state'] == 'done'}


# ---------------------------------------------------------------- a reading


def test_with_a_model_the_report_is_written_by_gemini_and_the_last_step_says_so(settings):
    model = FakeModel()
    client = real_client(settings, service_for(model))
    _profile, reading, events = real_reading(client)
    assert stage_details(events)['reading'] == 'Report written by Gemini from the findings, every passage checked'
    assert reading['meta']['provider'] == 'gemini' and reading['meta']['model'] == 'fake-gemini' and reading['meta']['mock'] is False
    assert reading['meta']['note'].startswith('Gemini wrote all ')
    assert model.calls == 1
    assert client.get(f'/v1/readings/{reading["id"]}').json() == reading  # what was stored is what was sent
    assert 'In traditional palmistry' in reading['report']['sections'][0]['traditional']['left']


def test_the_last_step_of_the_stream_waits_for_gemini_and_the_stream_keeps_alive(settings, monkeypatch):
    from app.api import readings as readings_api

    monkeypatch.setattr(readings_api, 'PING_SECONDS', 0.05)

    def slow(prompt):
        time.sleep(0.4)
        return good_answer(prompt)

    client = real_client(settings, service_for(FakeModel(slow)))
    response = client.post('/v1/readings', data={'profileId': _profile(client)['id']}, files=_photos())
    assert ': ping' in response.text  # the connection was kept open while the model was thinking
    assert response.text.rstrip().endswith('}') and 'event: reading' in response.text


def _profile(client):
    from helpers import add_profile

    return add_profile(client)


def _photos():
    from helpers import photo_files
    from realapp import drawn_hands

    return photo_files(drawn_hands().left, drawn_hands().right)


def test_without_a_key_the_reading_is_written_from_the_knowledge_base_and_says_nothing_about_gemini(settings):
    client = real_client(settings)
    _, reading, events = real_reading(client)
    assert stage_details(events)['reading'] == 'Report written from the findings'
    assert (reading['meta']['provider'], reading['meta']['model']) == ('knowledge-base', 'rule-based-writer') and 'note' not in reading['meta']
    health = client.get('/v1/health').json()
    assert health['writer'] == 'knowledge-base' and 'writerModel' not in health


def test_when_gemini_fails_the_reading_still_finishes_and_says_why(settings):
    client = real_client(settings, service_for(FakeModel(lambda prompt: unavailable('rate_limited', 'Quota exceeded'))))
    _, reading, events = real_reading(client)
    assert events[-1][0] == 'reading' and stage_details(events)['reading'] == 'Report written from the findings'
    assert (reading['meta']['provider'], reading['meta']['mock']) == ('knowledge-base', False)
    assert reading['meta']['note'] == 'Gemini was not used for this reading because Gemini’s free allowance is used up for now, so the words come from the knowledge base.'
    assert 'In traditional palmistry' in reading['report']['sections'][0]['traditional']['left']  # the fixed wording is still there


def test_a_sample_reading_never_goes_to_gemini(settings):
    from fastapi.testclient import TestClient
    from helpers import add_profile, make_reading, start_guest

    from app.main import create_app

    model = FakeModel()
    client = TestClient(create_app(settings, llm=service_for(model)))  # no hand finder: every reading is a labelled sample
    start_guest(client)
    reading = make_reading(client, add_profile(client)['id'])
    assert reading['meta']['mock'] is True and reading['meta']['provider'] == 'sample' and model.calls == 0
    conversation = add_conversation(client, reading['id'])
    answer = ask(client, conversation['id'], QUESTION)['assistant']
    assert model.calls == 0 and 'source' not in answer


def test_the_health_check_says_who_writes_the_words(settings):
    client = real_client(settings, service_for(FakeModel()))
    assert client.get('/v1/health').json() == {'ok': True, 'service': 'kiro-ai', 'version': '0.1.0', 'analysis': 'real', 'writer': 'gemini', 'writerModel': 'fake-gemini', 'storage': 'memory'}


def test_the_key_is_in_neither_the_health_check_nor_the_settings_text(tmp_path):
    key = 'AIzaSyD-this-is-not-a-real-key-0123456789'
    settings = Settings(env='test', site_dir=tmp_path, gemini_api_key=key)
    assert key not in repr(settings) and key not in str(settings)


# ---------------------------------------------------------------- a chat


@pytest.fixture
def chat(settings):
    model = FakeModel()
    client = real_client(settings, service_for(model, chat_limit=3))
    _, reading, _events = real_reading(client)
    conversation = add_conversation(client, reading['id'])
    model.requests.clear()  # the report's request is not what these tests are about
    return client, conversation, model


def test_a_chat_answer_from_gemini_is_labelled_and_checked(chat):
    client, conversation, model = chat
    answer = ask(client, conversation['id'], QUESTION)['assistant']
    assert model.calls == 1 and answer['source'] == 'gemini' and 'note' not in answer
    assert answer['flags'] == {'disclaimer': True} and answer['refs']['featureIds'] == ['heart']
    stored = client.get(f'/v1/conversations/{conversation["id"]}').json()['messages']
    assert stored[-1] == answer and stored[0]['role'] == 'user' and 'source' not in stored[0]


def test_a_declined_question_is_labelled_by_its_boundary_and_never_reaches_gemini(chat):
    client, conversation, model = chat
    answer = ask(client, conversation['id'], 'Will I be rich?')['assistant']
    assert model.calls == 0 and answer['flags']['boundary'] == 'financial' and 'source' not in answer


def test_a_chat_has_a_limited_number_of_gemini_answers_and_then_the_rules_answer(chat):
    client, conversation, model = chat
    sources = [ask(client, conversation['id'], QUESTION)['assistant'].get('source') for _ in range(5)]
    assert sources == ['gemini', 'gemini', 'gemini', 'knowledge-base', 'knowledge-base'] and model.calls == 3
    last = ask(client, conversation['id'], QUESTION)['assistant']
    assert 'used its share' in last['note'] and last['text']


def test_a_failing_gemini_never_leaves_a_question_unanswered(settings):
    client = real_client(settings, service_for(FakeModel(lambda prompt: unavailable('timeout') if prompt.startswith('READING') else good_answer(prompt))))
    _, reading, _events = real_reading(client)
    answer = ask(client, add_conversation(client, reading['id'])['id'], QUESTION)['assistant']
    assert answer['source'] == 'knowledge-base' and answer['note'].startswith('Gemini was not used for this answer because ') and 'heart line' in answer['text'].lower()


def test_the_server_keeps_answering_other_people_while_gemini_thinks(settings):
    gate = threading.Event()

    def slow(prompt):
        if prompt.startswith('READING'):
            gate.wait(5)
        return good_answer(prompt) if not prompt.startswith('READING') else json.dumps({'intent': 'answer', 'answer': 'In traditional palmistry the heart line is linked with emotional style.', 'lines': ['heart'], 'side': 'none', 'section': 'none'})

    client = real_client(settings, service_for(FakeModel(slow)))
    _, reading, _events = real_reading(client)
    conversation = add_conversation(client, reading['id'])
    done = []
    worker = threading.Thread(target=lambda: done.append(ask(client, conversation['id'], QUESTION)))
    worker.start()
    time.sleep(0.3)
    started = time.monotonic()
    assert client.get('/v1/health').status_code == 200  # answered at once, while the chat answer is still being written
    assert time.monotonic() - started < 1.0 and not done
    gate.set()
    worker.join(10)
    assert done and done[0]['assistant']['source'] == 'gemini'


def test_the_count_of_gemini_answers_is_not_part_of_what_a_person_can_export_or_delete(chat):
    client, conversation, _model = chat
    ask(client, conversation['id'], QUESTION)
    assert 'model_replies' not in json.dumps(client.get('/v1/account/export').json()) and 'modelReplies' not in json.dumps(client.get('/v1/account/export').json())
    bucket = next(iter(client.app.state.store.guests.values())).bucket
    assert bucket.model_replies == 1
    client.delete('/v1/account/data')
    assert bucket.model_replies == 1  # clearing someone's data does not give them a fresh share of answers
