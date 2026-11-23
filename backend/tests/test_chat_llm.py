"""The language-model chat (app/llm/chat_llm.py), run against a fake Gemini that is made to behave well and badly. What matters:
questions the reading never answers do not reach the model, what the model says is checked before it is shown, and a question
always gets an answer."""

from __future__ import annotations

import json

import pytest
from fake_gemini import FakeModel, good, good_chat, service_for, unavailable
from test_report_writer import reading_for
from test_standin import hands_for

from app.llm import prompts
from app.llm.chat import ChatContext
from app.llm.chat import answer as rule_based
from app.llm.chat_llm import respond
from app.llm.report import STAND_IN_META
from app.schemas import HandProfile, Message

ME = HandProfile(id='prf_me', name='Saji', owner='self', consent=True, createdAt='2026-01-01T00:00:00.000Z', readingCount=1, lastReadingAt=None)
MIA = HandProfile(id='prf_mia', name='Mia', owner='other', consent=True, createdAt='2026-01-01T00:00:00.000Z', readingCount=1, lastReadingAt=None)

FIVE_QUESTIONS = [
    'What does my heart line traditionally represent?',
    'What differences are visible between my left and right palms?',
    'What does palmistry say about my career?',
    'Can you explain my life line in more detail?',
    'What are the traditional interpretations of my financial prospects?',
]


def context(seed='rd_0000000000000001', history=(), meta=None, others=(MIA,)):
    hands = hands_for(seed, 0.95, 0.95)
    reading = reading_for(hands, meta) if meta else reading_for(hands)
    return ChatContext(reading=reading, profile=ME, other_profiles=list(others), history=list(history))


def reply(**fields):
    base = {'intent': 'answer', 'answer': 'In traditional palmistry the heart line is linked with emotional style.', 'lines': ['heart'], 'side': 'none', 'section': 'none'}
    return {**base, **fields}


def model_saying(**fields):
    return FakeModel(lambda prompt: reply(**fields))


def message(role, text, n=0):
    return Message(id=f'msg_{n}', conversationId='cnv_1', role=role, text=text, createdAt='2026-01-01T00:00:00.000Z')


# ---------------------------------------------------------------- questions that never reach the model


@pytest.mark.parametrize(
    ('question', 'boundary'),
    [
        ('Is my heart healthy?', 'medical'),
        ('How long will I live?', 'lifespan'),
        ('Should I invest in crypto?', 'financial'),
        ('Should I quit my job?', 'employment'),
        ('Should I marry him?', 'relationship'),
        ('Will my boyfriend leave me?', 'relationship'),
        ('Will I have children?', 'medical'),
        ('Should I move to Canada?', 'off_topic'),
    ],
)
def test_a_question_the_reading_never_answers_is_declined_by_the_rules_and_never_sent(question, boundary):
    model = FakeModel()
    response = respond(question, context(), service_for(model))
    assert model.calls == 0 and response.model_calls == 0 and response.source is None and response.note is None
    assert response.answer.flags.boundary == boundary and response.answer.flags.disclaimer is True
    assert response.answer.text == rule_based(question, context()).text


@pytest.mark.parametrize('question', ['Will I find love soon?', 'Will I be rich?', 'Will I get married?', 'What will happen to me?', 'Will I get a good job?'])
def test_a_question_for_the_reader_to_foretell_is_sent_to_the_model(question):
    answer = 'Love will find you before long, and your heart line says you will give it back in full measure.'
    model = model_saying(answer=answer, section='themes')
    response = respond(question, context(), service_for(model))
    assert model.calls == 1 and response.source == 'gemini' and response.answer.text == answer and response.note is None
    assert response.answer.flags.boundary is None


def test_a_question_about_another_profile_asks_to_switch_and_is_never_sent():
    model = FakeModel()
    response = respond("What does Mia's heart line say?", context(), service_for(model))
    assert model.calls == 0 and response.answer.flags.switchProfileId == 'prf_mia'


@pytest.mark.parametrize('text', ['hello', 'Thanks!', 'thank you'])
def test_a_greeting_or_a_thank_you_is_answered_without_the_model(text):
    model = FakeModel()
    response = respond(text, context(), service_for(model))
    assert model.calls == 0 and response.source is None and response.answer.text == rule_based(text, context()).text


# ---------------------------------------------------------------- the model answers


@pytest.mark.parametrize('question', FIVE_QUESTIONS)
def test_the_five_questions_of_the_brief_are_answered_by_the_model_with_the_disclaimer_flag(question):
    model = FakeModel()
    response = respond(question, context(), service_for(model))
    assert model.calls == 1 and response.model_calls == 1 and response.source == 'gemini' and response.note is None
    assert response.answer.flags.disclaimer is True and response.answer.flags.boundary is None
    assert response.answer.text.strip()  # the model's own words, checked and shown


def test_the_model_is_told_what_it_needs_and_nothing_else():
    model = FakeModel()
    service = service_for(model, timeout_s=40)
    respond('What does my heart line traditionally represent?', context(history=[message('user', 'hi', 1), message('assistant', 'Hello.', 2)]), service)
    request = model.requests[0]
    assert request.system == prompts.CHAT_SYSTEM and request.schema == prompts.CHAT_SCHEMA
    assert request.temperature == 0.3 and request.timeout_s == 20 and request.max_tokens == 2048
    parts = [p.split(':', 1)[0] for p in request.prompt.split('\n') if p.split(':', 1)[0] in ('READING (measured from the two photos by a computer-vision program; these are the only facts you have about the hands)', 'REPORT (what the person can read on screen, written from the READING)', 'KNOWLEDGE (curated notes on what each line and hand shape is said to foretell; stay close to their meaning)', 'CONVERSATION so far (oldest first)', 'QUESTION')]
    assert [p.split(' ')[0] for p in parts] == ['READING', 'REPORT', 'KNOWLEDGE', 'CONVERSATION', 'QUESTION']
    assert '[heart.general]' in request.prompt and 'Person: hi' in request.prompt and 'Kiro: Hello.' in request.prompt
    assert request.prompt.rstrip().endswith('QUESTION: What does my heart line traditionally represent?')
    assert 'SUMMARY:' in request.prompt and 'WHAT WAS UNCLEAR OR MISSING' in request.prompt  # the report the person reads, as they read it


@pytest.mark.parametrize(('report_wait', 'chat_wait'), [(150, 45), (100, 45), (60, 30), (30, 15), (10, 10), (4, 10)])
def test_a_chat_answer_waits_half_as_long_as_a_report_but_not_more_than_45_seconds_and_not_less_than_10(report_wait, chat_wait):
    model = FakeModel()
    respond('What does my heart line traditionally represent?', context(), service_for(model, timeout_s=report_wait))
    assert model.requests[0].timeout_s == chat_wait


def test_a_chat_answer_is_asked_again_twice_when_google_is_busy_before_the_fixed_wording_answers():
    failures = iter([unavailable('overloaded', 'busy'), unavailable('overloaded', 'busy')])

    def answer(prompt):
        failure = next(failures, None)
        return failure if failure is not None else good(prompt)

    model = FakeModel(answer)
    response = respond('What does my heart line traditionally represent?', context(), service_for(model))
    assert model.calls == 3 and response.source == 'gemini' and response.note is None
    always = FakeModel(lambda prompt: unavailable('overloaded', 'busy'))
    response = respond('What does my heart line traditionally represent?', context(), service_for(always))
    assert always.calls == 3 and response.source == 'knowledge-base' and 'very busy' in response.note


def test_a_chat_reply_with_a_sentence_before_its_fence_is_read_too():
    from app.llm.chat_llm import parse_reply

    text = 'Here is my answer:\n```json\n' + json.dumps(reply(answer='A long life line is read as steady energy.')) + '\n```'
    assert parse_reply(text)['answer'] == 'A long life line is read as steady energy.'


def test_only_the_last_few_messages_are_shown_and_each_is_shortened():
    history = [message('user' if n % 2 == 0 else 'assistant', f'message {n} ' + 'x' * 900, n) for n in range(10)]
    model = FakeModel()
    respond('and the left hand?', context(history=history), service_for(model))
    prompt = model.requests[0].prompt
    assert 'message 3 ' not in prompt and 'message 4 ' in prompt and 'message 9 ' in prompt  # the last six
    assert max(len(line) for line in prompt.split('CONVERSATION so far')[1].split('QUESTION')[0].splitlines()) < 520


def test_what_the_model_names_as_the_topic_becomes_the_chips_but_only_for_lines_that_were_found():
    # fate and sun are not detected on either hand of this reading
    hands = hands_for('rd_000000000000000a', 0.95, 0.95)
    assert all(next(f for f in h.features if f.id == 'fate').status != 'detected' for h in hands.values())
    response = respond('Compare the two', context('rd_000000000000000a'), service_for(model_saying(lines=['fate', 'heart', 'nonsense'], side='left', section='comparison')))
    refs = response.answer.refs
    assert refs.featureIds == ['heart'] and refs.side == 'left' and refs.section == 'comparison'
    assert respond('x', context('rd_000000000000000a'), service_for(model_saying(lines=['life']))).answer.refs.section == 'life'  # one line: its section
    assert respond('x', context('rd_000000000000000a'), service_for(model_saying(lines=[], side='left', section='none'))).answer.refs.side == 'left'
    for side in ('both', 'none'):  # "both hands" and "no hand" are not chips
        assert respond('x', context('rd_000000000000000a'), service_for(model_saying(lines=[], side=side, section='none'))).answer.refs is None


def test_markdown_in_an_answer_is_turned_into_plain_text():
    response = respond('x', context(), service_for(model_saying(answer='**In traditional palmistry** the heart line is linked with feeling:\n- warmth\n- openness')))
    assert response.answer.text == 'In traditional palmistry the heart line is linked with feeling:\n• warmth\n• openness'


# ---------------------------------------------------------------- a boundary the rules missed, caught by the model


@pytest.mark.parametrize(
    ('intent', 'boundary'),
    [
        ('medical', 'medical'),
        ('lifespan', 'lifespan'),
        ('financial_advice', 'financial'),
        ('employment_advice', 'employment'),
        ('relationship_advice', 'relationship'),
        ('advice', 'off_topic'),
        ('off_topic', 'off_topic'),
    ],
)
def test_when_the_model_recognises_a_boundary_the_apps_own_wording_is_shown_and_the_models_is_dropped(intent, boundary):
    model = model_saying(intent=intent, answer='You will certainly be fine, trust me.')
    response = respond('Does my startup have a bright outlook?', context(), service_for(model))
    assert model.calls == 1 and response.model_calls == 1
    assert 'trust me' not in response.answer.text and response.answer.flags.boundary == boundary and response.source is None


# ---------------------------------------------------------------- an answer that does not pass


@pytest.mark.parametrize(
    'text',
    [
        'In traditional palmistry your heart line means you will find love next year.',
        'In traditional palmistry your heart line is warm, so you should call your family.',
        'In traditional palmistry your heart line says something about the health of your heart.',
        'In traditional palmistry your fate line is long and deep.',
        'Your heart line means you are a warm person, and your life is guaranteed to be long.',
        'In traditional palmistry your left heart line is short, read as reserve.',
        'In traditional palmistry your dominant hand shows what you built.',
        'I can see a mount of Venus on your palm, which in traditional palmistry is read as warmth.',
        'In traditional palmistry your heart line is read as warmth, shown by 3 branches.',
    ],
)
def test_an_answer_that_breaks_a_rule_is_replaced_by_the_rule_based_answer_with_a_note(text):
    question = 'What does my heart line traditionally represent?'
    response = respond(question, context('rd_000000000000000a'), service_for(model_saying(answer=text)))
    assert response.source == 'knowledge-base' and response.model_calls == 1
    assert response.note == 'Gemini’s answer did not pass the app’s safety checks, so the app answered from its own notes.'
    assert response.answer.text == rule_based(question, context('rd_000000000000000a')).text


def test_a_reply_that_cannot_be_read_is_replaced_the_same_way():
    for text in ('I would love to help!', '[]', json.dumps({'answer': 'no intent'}), json.dumps({'intent': 'dance', 'answer': 'x'})):
        response = respond('What does my heart line mean?', context(), service_for(FakeModel(lambda prompt, t=text: t)))
        assert response.source == 'knowledge-base' and 'not in the form' in response.note and response.model_calls == 1


@pytest.mark.parametrize('kind', ['rate_limited', 'busy', 'timeout', 'error', 'bad_key', 'bad_model', 'blocked', 'cut_off', 'empty'])
def test_when_the_model_cannot_answer_the_rule_based_answer_is_shown_with_the_reason(kind):
    question = 'What does my heart line mean?'
    model = FakeModel(lambda prompt: unavailable(kind, 'detail'))
    response = respond(question, context(), service_for(model))
    assert response.source == 'knowledge-base' and response.answer.text == rule_based(question, context()).text
    assert response.note.startswith('Gemini was not used for this answer because ') and response.note.endswith('so the app answered from its own notes.')
    assert response.model_calls == 0  # nothing was answered, so nothing is counted against the chat


def test_a_chat_that_has_used_its_share_of_answers_gets_the_rule_based_answer_without_asking():
    model = FakeModel()
    response = respond('What does my heart line mean?', context(), service_for(model, chat_limit=3), replies_so_far=3)
    assert model.calls == 0 and response.source == 'knowledge-base' and 'used its share' in response.note
    assert respond('What does my heart line mean?', context(), service_for(model, chat_limit=3), replies_so_far=2).source == 'gemini'


def test_with_no_key_the_chat_is_exactly_the_rule_based_chat_and_says_nothing_about_gemini():
    question = 'What does my heart line mean?'
    response = respond(question, context(), service_for(None))
    assert response.source is None and response.note is None and response.model_calls == 0
    assert response.answer.text == rule_based(question, context()).text


def test_a_sample_reading_is_never_sent_to_the_model():
    model = FakeModel()
    response = respond('What does my heart line mean?', context(meta=STAND_IN_META), service_for(model))
    assert model.calls == 0 and response.source is None


def test_the_chat_never_raises_even_if_the_chat_code_itself_fails(monkeypatch):
    from app.llm import chat_llm

    monkeypatch.setattr(chat_llm, 'ask_model', lambda *a, **k: 1 / 0)
    response = respond('What does my heart line mean?', context(), service_for(FakeModel()))
    assert response.source == 'knowledge-base' and 'unexpected problem' in response.note and response.answer.text


def test_the_fake_models_default_answers_match_the_prompt_they_are_given():
    assert 'intent' in good('READING ...\nKNOWLEDGE\n[heart.general] In traditional palmistry the heart line.\nCONVERSATION so far')
    assert good_chat('READING\nKNOWLEDGE\nCONVERSATION')['intent'] == 'answer'
