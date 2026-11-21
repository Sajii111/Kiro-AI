"""What leaves the server for Gemini, and what is taken out of it first (app/llm/privacy.py, app/llm/prompts.findings_payload).
The rule is that a photo, a name, a file name or a contact detail never goes: these tests read what the model is actually sent."""

from __future__ import annotations

import json
import re

import pytest
from fake_gemini import FakeModel, service_for
from helpers import add_conversation, ask
from realapp import drawn_hands, real_client, real_reading
from test_standin import hands_for

from app.llm import prompts
from app.llm.privacy import name_parts, scrub
from app.schemas import Reading

ALLOWED_VALUES = {
    'status': {'detected', 'uncertain', 'not_visible'},
    'length': {'short', 'medium', 'long'},
    'curve': {'straight', 'gentle', 'pronounced'},
    'clarity': {'clear', 'deep'},  # a faint line is sent without its clarity
    'palm': {'square', 'long'},
    'fingers': {'short', 'long'},
    'element': {'earth', 'air', 'water', 'fire'},
}


# ---------------------------------------------------------------- the scrubber


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('write to saji.k@example.co.uk about it', 'write to [email removed] about it'),
        ('see https://example.com/a?b=1 and www.example.org', 'see [link removed] and [link removed]'),
        ('call +94 77 123 4567 now', 'call [number removed] now'),
        ('my number is (011) 234-5678.', 'my number is [number removed].'),
        ('born in 1990', 'born in 1990'),  # four digits are not a phone number
        ('What does my heart line say?', 'What does my heart line say?'),
    ],
)
def test_contact_details_are_replaced(text, expected):
    assert scrub(text) == expected


def test_names_are_replaced_whole_and_in_part_whatever_the_case():
    names = ['Saji Kumar', 'Mia']
    assert scrub("Is saji's heart line like Mia's?", names) == "Is [name]'s heart line like [name]'s?"
    assert scrub('Kumar asked', names) == '[name] asked'
    assert scrub('The Miami line', names) == 'The Miami line'  # only whole words
    assert name_parts(['A', 'Saji Kumar']) == ['Saji Kumar', 'Kumar', 'Saji']  # one letter is not a name, short words are not parts


# ---------------------------------------------------------------- the findings sent for a report


def test_the_findings_are_words_from_short_lists_and_nothing_else():
    hands = hands_for('rd_0000000000000001', 0.95, 0.95)
    payload = prompts.findings_payload(hands)
    assert set(payload) == {'left', 'right'}
    for side in payload.values():
        assert set(side) == {'lines', 'handShape'}
        assert list(side['lines']) == ['heart', 'head', 'life', 'fate', 'sun']
        for entry in [*side['lines'].values(), side['handShape']]:
            for key, value in entry.items():
                assert value in ALLOWED_VALUES[key], (key, value)
    text = json.dumps(payload)
    assert not re.search(r'\d', text) and 'photo' not in text.lower() and 'data:' not in text  # no number, no photo, no picture


def test_a_faint_line_is_sent_without_how_clear_it_is():
    hands = hands_for('rd_0000000000000001', 0.95, 0.95)
    heart = next(f for f in hands['left'].features if f.id == 'heart')
    heart.traits.clarity = 'faint'
    assert 'clarity' not in prompts.findings_payload(hands)['left']['lines']['heart']


# ---------------------------------------------------------------- what a whole reading and chat send


@pytest.fixture
def run(settings):
    """A real reading and some chat, with every request the model received."""
    model = FakeModel()
    client = real_client(settings, service_for(model))
    profile, reading, _events = real_reading(client, name='Saji Kumar')
    conversation = add_conversation(client, reading['id'])
    ask(client, conversation['id'], 'What does my heart line say? Mail me at saji.kumar@example.com or call 077 123 4567, I am Saji.')
    ask(client, conversation['id'], 'and what about the head line, Kumar?')
    return model, profile, reading


def test_no_photo_name_file_name_or_contact_detail_is_ever_sent(run):
    model, profile, _reading = run
    assert model.calls == 3  # one report and two chat answers
    hands = drawn_hands()
    for request in model.requests:
        everything = request.system + request.prompt + json.dumps(request.schema)
        for secret in ('Saji', 'Kumar', 'example.com', '077 123', '4567', 'left.jpg', 'right.jpg', 'image/jpeg', 'base64', 'data:image', profile['id']):
            assert secret not in everything, secret
        assert hands.left[:64].hex() not in everything.encode().hex() and 'JFIF' not in everything


def test_the_chat_question_arrives_scrubbed_and_the_name_in_the_history_too(run):
    model, _profile, _reading = run
    first, second = model.requests[1].prompt, model.requests[2].prompt
    assert 'QUESTION: What does my heart line say? Mail me at [email removed] or call [number removed], I am [name].' in first
    assert 'Person: What does my heart line say? Mail me at [email removed] or call [number removed], I am [name].' in second
    assert 'QUESTION: and what about the head line, [name]?' in second


def test_the_report_request_carries_only_the_findings_the_knowledge_and_the_passages_to_write(run):
    model, _profile, reading = run
    prompt = model.requests[0].prompt
    assert prompt.splitlines()[0].startswith('FINDINGS') and 'KNOWLEDGE' in prompt and 'WRITE these passages' in prompt
    findings = json.loads(prompt.split('\n', 1)[1].split('\n\nKNOWLEDGE', 1)[0])
    shown = Reading.model_validate(reading)
    assert findings == prompts.findings_payload({'left': shown.hands.left, 'right': shown.hands.right})
