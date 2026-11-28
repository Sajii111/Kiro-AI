"""Readings and chat answers in Sinhala or Tamil (app/llm/translate.py): written and checked in English, then translated.

The fake model (fake_gemini.py) "translates" by turning every Latin letter into a Sinhala or Tamil letter, so a test can see
that a text was translated, that it is in the right script, and which English text it came from."""

from __future__ import annotations

import json

import pytest
from fake_gemini import FakeModel, fake_translate, service_for, unavailable
from fastapi.testclient import TestClient
from helpers import (
    add_conversation,
    add_profile,
    make_reading,
    parse_stream,
    photo_files,
    start_guest,
)
from realapp import drawn_hands, real_client, real_reading

from app.llm import translate
from app.llm.translate import SCRIPT, problems, translate_answer, translate_texts
from app.main import create_app
from app.schemas import Report

SINHALA = SCRIPT['si']
TAMIL = SCRIPT['ta']


def in_script(text: str, script) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if script.match(c)) >= 0.5 * len(letters)


def translations(model: FakeModel) -> list:
    return [r for r in model.requests if r.prompt.startswith('TRANSLATE')]


def sent_texts(model: FakeModel) -> list[str]:
    out = []
    for r in translations(model):
        out.extend(json.loads(r.prompt.split('\n', 1)[1]).values())
    return out


# ---------------------------------------------------------------- the checks on one translation


def test_a_good_translation_passes():
    source = 'Your heart line is long. Love comes to you easily.'
    assert problems(source, fake_translate(source, 'Sinhala'), 'si') == []
    assert problems(source, fake_translate(source, 'Tamil'), 'ta') == []


@pytest.mark.parametrize(
    ('text', 'why'),
    [
        ('Your heart line is long.', 'is not written in Sinhala'),  # left in English
        (fake_translate('Your heart line is long.', 'Tamil'), 'is not written in Sinhala'),  # the wrong language
        (fake_translate('Your heart line is long.', 'Sinhala') + ' 2027', 'adds a number'),
        (fake_translate('Your heart line is long.', 'Sinhala') + ' www.example.com', 'adds a link'),
        (fake_translate('Your heart line is long.', 'Sinhala') * 9, 'far longer'),
        ('', 'is empty'),
    ],
)
def test_a_bad_translation_is_refused(text, why):
    found = problems('Your heart line is long.', text, 'si')
    assert any(why in p for p in found), found


# ---------------------------------------------------------------- translate_texts


def test_texts_are_translated_and_the_same_text_is_asked_for_once():
    model = FakeModel()
    texts = {'a': 'Heart line', 'b': 'You will travel soon.', 'c': 'Heart line'}
    result = translate_texts(texts, 'ta', service_for(model), wait=30)
    assert result.failed == {}
    assert set(result.done) == {'a', 'b', 'c'}
    assert result.done['a'] == result.done['c'] == fake_translate('Heart line', 'Tamil')
    assert all(in_script(v, TAMIL) for v in result.done.values())
    assert sorted(sent_texts(model)) == ['Heart line', 'You will travel soon.']
    assert 'into Tamil' in translations(model)[0].system


def test_a_text_that_fails_a_check_is_asked_for_again_then_kept_in_english():
    calls = []

    def sloppy(system, prompt):
        texts = json.loads(prompt.split('\n', 1)[1])
        calls.append(list(texts.values()))
        return {k: (v if 'money' in v else fake_translate(v, 'Sinhala')) for k, v in texts.items()}  # leaves one in English

    model = FakeModel(translate=sloppy)
    result = translate_texts({'a': 'Your work will grow.', 'b': 'Talk about money later.'}, 'si', service_for(model), wait=30)
    assert set(result.done) == {'a'} and set(result.failed) == {'b'}
    assert calls == [['Your work will grow.', 'Talk about money later.'], ['Talk about money later.']]  # only the failed one again


def test_a_busy_gemini_leaves_the_english_and_says_why():
    model = FakeModel(translate=lambda s, p: unavailable('overloaded'))
    result = translate_texts({'a': 'Your work will grow.'}, 'si', service_for(model, retry_wait=0), wait=30)
    assert result.done == {} and 'a' in result.failed
    assert result.error is not None and result.error.kind == 'overloaded'


def test_long_lists_are_sent_in_parts():
    model = FakeModel()
    texts = {f'k{i}': f'Passage number {"x" * 400} {i} of the reading.' for i in range(20)}
    result = translate_texts(texts, 'si', service_for(model), wait=30)
    assert len(result.done) == 20
    assert len(translations(model)) >= 3
    assert all(len(r.prompt) < translate.CHUNK_CHARS * 2 for r in translations(model))


def test_english_asks_for_nothing():
    model = FakeModel()
    assert translate_texts({'a': 'Hello'}, 'en', service_for(model), wait=30).done == {}
    assert model.calls == 0


# ---------------------------------------------------------------- a reading in Sinhala or Tamil, through the API


def sinhala_reading(settings, model: FakeModel, language: str = 'si', reading_name: str | None = None):
    client = real_client(settings, llm=service_for(model))
    profile = add_profile(client, name='Saji Kumar')
    hands = drawn_hands()
    data = {'profileId': profile['id'], 'language': language}
    if reading_name:
        data['name'] = reading_name
    r = client.post('/v1/readings', data=data, files=photo_files(hands.left, hands.right))
    assert r.status_code == 200, r.text
    events = parse_stream(r.text)
    assert events[-1][0] == 'reading', events[-1]
    return client, profile, events[-1][1]


@pytest.mark.parametrize(('language', 'script'), [('si', SINHALA), ('ta', TAMIL)])
def test_a_reading_is_written_in_english_then_translated(settings, language, script):
    model = FakeModel()
    _client, _profile, reading = sinhala_reading(settings, model, language)
    assert reading['meta']['language'] == language
    assert reading['meta']['provider'] == 'gemini'
    report = reading['report']
    assert in_script(report['summary'], script)
    assert in_script(report['disclaimer'], script)
    for section in report['sections']:
        assert in_script(section['title'], script)
        assert in_script(section['observed']['left']['text'], script)
    assert all(in_script(t['title'], script) for t in report['themes'])
    # the report was asked for (and checked) in English first; the translation came after
    kinds = ['translate' if r.prompt.startswith('TRANSLATE') else 'write' for r in model.requests]
    assert kinds[0] == 'write' and kinds[-1] == 'translate'
    assert 'translate' not in kinds[: kinds.index('translate')]
    assert all(not r.prompt.startswith('TRANSLATE') or translate.system_for(language) == r.system for r in model.requests)


def test_the_translation_gets_the_checked_english_and_no_name(settings):
    model = FakeModel()
    sinhala_reading(settings, model, reading_name='Before my trip')
    sent = sent_texts(model)
    joined = ' '.join(sent)
    assert 'Saji' not in joined and 'Kumar' not in joined and 'Before my trip' not in joined
    # every text the translator was given is a text of the same reading in English, as checked: nothing else goes
    client = real_client(settings, llm=service_for(FakeModel()))
    _p, english, _e = real_reading(client)
    assert set(sent) <= set(translate.report_texts(Report(**english['report'])).values())


def test_a_reading_stays_in_english_with_a_note_when_gemini_cannot_translate(settings):
    def busy(system, prompt):
        return unavailable('overloaded')

    model = FakeModel(translate=busy)
    _client, _profile, reading = sinhala_reading(settings, model)
    assert 'language' not in reading['meta']
    assert reading['meta']['provider'] == 'gemini'  # the English reading is still Gemini's
    assert 'could not be translated into Sinhala' in reading['meta']['note']
    assert not in_script(reading['report']['summary'], SINHALA)


def test_without_a_key_the_reading_says_it_stays_in_english(settings):
    client = real_client(settings, llm=service_for(None))
    profile = add_profile(client)
    hands = drawn_hands()
    r = client.post('/v1/readings', data={'profileId': profile['id'], 'language': 'ta'}, files=photo_files(hands.left, hands.right))
    reading = parse_stream(r.text)[-1][1]
    assert 'language' not in reading['meta']
    assert 'shown in English instead of Tamil' in reading['meta']['note']


def test_a_sample_reading_is_never_sent_to_be_translated(settings):
    model = FakeModel()
    c = TestClient(create_app(settings, llm=service_for(model)))
    start_guest(c)
    profile = add_profile(c)
    r = c.post('/v1/readings', data={'profileId': profile['id'], 'language': 'si'}, files=photo_files())
    reading = parse_stream(r.text)[-1][1]
    assert reading['meta']['mock'] is True
    assert 'language' not in reading['meta']
    assert model.calls == 0


def test_an_unknown_language_is_refused_before_any_photo_is_looked_at(settings):
    model = FakeModel()
    client = real_client(settings, llm=service_for(model))
    profile = add_profile(client)
    hands = drawn_hands()
    r = client.post('/v1/readings', data={'profileId': profile['id'], 'language': 'fr'}, files=photo_files(hands.left, hands.right))
    assert r.status_code == 422
    assert r.json()['error']['message'] == 'A reading can be written in English, Sinhala or Tamil.'
    assert model.calls == 0


def test_english_is_still_the_default(settings):
    model = FakeModel()
    client = real_client(settings, llm=service_for(model))
    _p, reading, _e = real_reading(client)
    assert 'language' not in reading['meta']
    assert translations(model) == []


# ---------------------------------------------------------------- chat answers


def test_a_chat_answer_is_checked_in_english_then_translated(settings):
    model = FakeModel()
    client = real_client(settings, llm=service_for(model))
    _p, reading, _e = real_reading(client)
    convo = add_conversation(client, reading['id'])
    r = client.post(f'/v1/conversations/{convo["id"]}/messages', json={'text': 'What does my heart line say?', 'language': 'si'})
    assert r.status_code == 200, r.text
    answer = r.json()['assistant']
    assert answer['source'] == 'gemini'
    assert in_script(answer['text'], SINHALA)
    assert model.requests[-1].prompt.startswith('TRANSLATE')
    assert model.requests[-2].prompt.startswith('READING')  # the English answer came first


def test_a_fixed_chat_answer_is_translated_without_the_profile_name(settings):
    model = FakeModel()
    client = real_client(settings, llm=service_for(model))
    _p, reading, _e = real_reading(client, name='Saji')
    convo = add_conversation(client, reading['id'])
    r = client.post(f'/v1/conversations/{convo["id"]}/messages', json={'text': 'hello', 'language': 'ta'})
    answer = r.json()['assistant']
    assert in_script(answer['text'], TAMIL)
    assert all('Saji' not in t for t in sent_texts(model))


def test_names_are_swapped_out_and_back():
    model = FakeModel()
    text, note = translate_answer('Saji, your heart line is long.', 'si', service_for(model), ['Saji Kumar'])
    assert note is None
    assert text.startswith('Saji,') and in_script(text, SINHALA)
    assert 'Saji' not in ' '.join(sent_texts(model))


def test_a_chat_answer_that_cannot_be_translated_stays_in_english_with_a_note(settings):
    model = FakeModel(translate=lambda s, p: 'not json at all')
    client = real_client(settings, llm=service_for(model))
    _p, reading, _e = real_reading(client)
    convo = add_conversation(client, reading['id'])
    r = client.post(f'/v1/conversations/{convo["id"]}/messages', json={'text': 'What does my heart line say?', 'language': 'si'})
    answer = r.json()['assistant']
    assert not in_script(answer['text'], SINHALA)
    assert answer['note'] == 'This answer could not be translated into Sinhala, so it is shown in English.'


def test_a_chat_without_a_language_is_english(settings):
    model = FakeModel()
    client = real_client(settings, llm=service_for(model))
    _p, reading, _e = real_reading(client)
    convo = add_conversation(client, reading['id'])
    r = client.post(f'/v1/conversations/{convo["id"]}/messages', json={'text': 'What does my heart line say?'})
    assert r.status_code == 200
    assert translations(model) == []


def test_make_reading_helper_still_works(client):
    start_guest(client)
    profile = add_profile(client)
    assert make_reading(client, profile['id'])['meta']['mock'] is True
