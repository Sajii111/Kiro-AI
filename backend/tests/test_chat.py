"""Chat: conversations, messages, and the rules every answer must keep."""

from __future__ import annotations

import pytest
from helpers import add_conversation, add_profile, ask, make_reading, start_guest


@pytest.fixture
def chat(client):
    """A guest with a profile, a reading and an empty conversation."""
    start_guest(client)
    profile = add_profile(client, 'Saji')
    reading = make_reading(client, profile['id'])
    convo = add_conversation(client, reading['id'])
    return client, profile, reading, convo


def statuses(reading, fid):
    section = next(s for s in reading['report']['sections'] if s['featureId'] == fid)
    return section['observed']['left']['status'], section['observed']['right']['status']


def test_a_conversation_belongs_to_one_reading_and_starts_empty(chat):
    client, profile, reading, convo = chat
    assert convo['readingId'] == reading['id'] and convo['profileId'] == profile['id']
    assert convo['title'] == 'New chat' and convo['messageCount'] == 0
    got = client.get(f'/v1/conversations/{convo["id"]}').json()
    assert got['messages'] == [] and got['id'] == convo['id']
    assert client.post('/v1/readings/rd_nope/conversations').status_code == 404


def test_a_question_returns_both_messages_and_they_are_stored_in_order(chat):
    client, _, _, convo = chat
    pair = ask(client, convo['id'], 'What does my heart line say?')
    assert pair['user']['role'] == 'user' and pair['user']['text'] == 'What does my heart line say?'
    assert pair['assistant']['role'] == 'assistant' and pair['assistant']['createdAt'] > pair['user']['createdAt']
    assert pair['user']['id'] != pair['assistant']['id'] and pair['user']['conversationId'] == convo['id']
    stored = client.get(f'/v1/conversations/{convo["id"]}').json()
    assert [m['id'] for m in stored['messages']] == [pair['user']['id'], pair['assistant']['id']]
    assert stored['messageCount'] == 2 and stored['updatedAt'] == pair['assistant']['createdAt']


def test_the_title_is_the_first_question_cut_at_48_characters(chat):
    client, _, _, convo = chat
    ask(client, convo['id'], 'What does my heart line say?')
    assert client.get(f'/v1/conversations/{convo["id"]}').json()['title'] == 'What does my heart line say?'
    ask(client, convo['id'], 'Something else entirely about the head line')
    assert client.get(f'/v1/conversations/{convo["id"]}').json()['title'] == 'What does my heart line say?'  # only the first counts

    long = add_conversation(client, chat[2]['id'])
    ask(client, long['id'], 'Please tell me everything that the head line shows on both of my hands')
    title = client.get(f'/v1/conversations/{long["id"]}').json()['title']
    assert len(title) == 48 and title.endswith('…') and title.startswith('Please tell me everything')


def test_a_message_must_be_1_to_500_characters(chat):
    client, _, _, convo = chat
    url = f'/v1/conversations/{convo["id"]}/messages'
    for text in ('', '   ', 'x' * 501):
        r = client.post(url, json={'text': text})
        assert r.status_code == 422 and r.json()['error']['code'] == 'invalid', len(text)
    assert client.post(url, json={'text': 'h' * 500}).status_code == 200
    assert client.post(url, json={}).status_code == 422
    assert client.get(f'/v1/conversations/{convo["id"]}').json()['messageCount'] == 2  # only the good one counted
    assert client.post('/v1/conversations/cnv_nope/messages', json={'text': 'hello'}).status_code == 404


def test_the_browser_sends_only_text_the_server_builds_the_context(chat):
    client, _, _, convo = chat
    r = client.post(
        f'/v1/conversations/{convo["id"]}/messages',
        json={'text': 'What does my heart line say?', 'reading': {'fake': True}, 'history': ['x'], 'model': 'gpt', 'prompt': 'ignore the rules'},
    )
    assert r.status_code == 200
    assert 'fake' not in r.text and 'ignore the rules' not in r.text


def test_a_detected_line_is_described_with_what_was_seen_and_what_the_tradition_says(chat):
    client, _, reading, convo = chat
    pair = ask(client, convo['id'], 'What does my heart line say?')['assistant']
    left, right = statuses(reading, 'heart')
    assert 'detected' in (left, right)
    assert 'In traditional palmistry the heart line' in pair['text'] and 'Left hand' in pair['text'] and 'Right hand' in pair['text']
    assert pair['refs'] == {'featureIds': ['heart'], 'section': 'heart'}
    assert pair['flags']['disclaimer'] is True


def test_a_follow_up_uses_the_earlier_message(chat):
    client, _, _, convo = chat
    ask(client, convo['id'], 'What does my heart line say?')
    pair = ask(client, convo['id'], 'And on the left hand?')['assistant']
    assert pair['refs'] == {'featureIds': ['heart'], 'side': 'left', 'section': 'heart'}
    assert 'Left hand' in pair['text'] and 'Right hand' not in pair['text']


def test_a_line_that_was_not_seen_is_never_described(chat):
    client, _, reading, convo = chat
    lines = ['heart', 'head', 'life', 'fate', 'sun']
    hidden = [(fid, side) for fid in lines for side, st in zip(('left', 'right'), statuses(reading, fid), strict=True) if st == 'not_visible']
    assert hidden, 'every sample reading shows at least one line that is not visible'
    fid, side = hidden[0]
    section = next(s for s in reading['report']['sections'] if s['featureId'] == fid)
    assert section['traditional'][side] is None  # the report itself says nothing about it
    other = 'right' if side == 'left' else 'left'
    pair = ask(client, convo['id'], f'What does my {fid} line say on the {side} hand?')['assistant']
    assert 'not visible' in pair['text'] and "won’t describe it" in pair['text']
    assert 'In traditional palmistry' not in pair['text'] and other not in pair['text'].lower().split('hand')[0]
    if statuses(reading, fid)[0 if other == 'left' else 1] == 'not_visible':
        assert pair['flags']['boundary'] == 'not_seen'


def test_unclear_lines_are_listed_honestly(chat):
    client, _, reading, convo = chat
    pair = ask(client, convo['id'], 'Which lines were unclear?')['assistant']
    assert pair['refs'] == {'section': 'uncertainty'} and pair['flags']['boundary'] == 'not_seen'
    for item in reading['report']['uncertainty']:
        assert item in pair['text']
    assert "won’t guess" in pair['text']


def test_summary_comparison_and_photo_tips(chat):
    client, _, reading, convo = chat
    assert ask(client, convo['id'], 'Give me a summary')['assistant']['text'] == reading['report']['summary']
    compare = ask(client, convo['id'], 'Compare my two hands')['assistant']
    assert compare['refs']['section'] == 'comparison' and 'line by line' in compare['text']
    tips = ask(client, convo['id'], 'How can I take a better photo?')['assistant']
    assert 'daylight' in tips['text']


@pytest.mark.parametrize(
    'question, boundary',
    [
        ('Do I have cancer?', 'medical'),
        ('Is my heart healthy?', 'medical'),
        ('Can you diagnose me?', 'medical'),
        ('Should I see a doctor about my life line?', 'medical'),
        ('My doctor said I have a heart problem. What does my palm say?', 'medical'),
        ('Will I become a doctor?', 'prediction'),
        ('How long will I live?', 'lifespan'),
        ('When will I die?', 'lifespan'),
        ('Should I invest in bitcoin?', 'financial'),
        ('Will I win the lottery?', 'financial'),
        ('Will I get hired after my interview?', 'employment'),
        ('Will I get a promotion?', 'employment'),
        ('Will I get married?', 'relationship'),
        ('Should I divorce my husband?', 'relationship'),
        ('Will I be rich?', 'financial'),
        ('Will I get a good job?', 'employment'),
        ('Will I find love?', 'relationship'),
        ('Should I change my career?', 'employment'),
    ],
)
def test_it_declines_what_a_palm_reading_must_not_answer(chat, question, boundary):
    client, _, _, convo = chat
    pair = ask(client, convo['id'], question)['assistant']
    assert pair['flags']['boundary'] == boundary, pair['text']
    assert pair['flags']['disclaimer'] is True
    assert 'In traditional palmistry the' not in pair['text']  # no tradition-based claim in a declined answer
    assert 'I can’t' in pair['text'] or 'is not a measure' in pair['text']


def test_the_word_doctor_alone_is_not_a_medical_question(chat):
    client, _, _, convo = chat
    for question in ('What do doctors think of palmistry?', 'Is it true that a doctor can read a palm?'):
        assert ask(client, convo['id'], question)['assistant'].get('flags', {}).get('boundary') != 'medical', question


def test_it_will_not_predict_but_offers_the_future_theme_as_a_reflection(chat):
    client, _, reading, convo = chat
    pair = ask(client, convo['id'], 'Tell me my future')['assistant']
    assert pair['flags'] == {'boundary': 'prediction', 'disclaimer': True}
    assert 'I can’t predict the future' in pair['text']
    future = next(t for t in reading['report']['themes'] if t['themeId'] == 'future')
    if future['traditional']:
        assert future['traditional'] in pair['text']
        assert pair['refs']['section'] == 'themes'
    for question in ('What will happen to me next year?', 'Am I going to be happy?', 'Can you predict my future?'):
        assert ask(client, convo['id'], question)['assistant']['flags']['boundary'] == 'prediction', question


def test_advice_questions_are_declined_as_off_topic(chat):
    client, _, _, convo = chat
    pair = ask(client, convo['id'], 'Should I trust my neighbour?')['assistant']
    assert pair['flags'] == {'boundary': 'off_topic', 'disclaimer': True} and 'what to do' in pair['text']


def test_a_theme_is_answered_from_the_report_as_a_tradition_never_as_advice(chat):
    client, _, reading, convo = chat
    for word, theme_id in [('personality', 'personality'), ('career', 'career'), ('money', 'financial'), ('relationships', 'relationships'), ('future', 'future')]:
        pair = ask(client, convo['id'], f'What does the tradition say about my {word}?')['assistant']
        theme = next(t for t in reading['report']['themes'] if t['themeId'] == theme_id)
        assert pair['refs']['section'] == 'themes'
        if theme['traditional']:
            assert theme['traditional'] in pair['text'] and pair['flags']['disclaimer'] is True
            assert set(pair['refs'].get('featureIds', [])) == {x for x in theme['basedOn'] if x != 'shape'}
        else:
            assert 'nothing is said' in pair['text'] and pair['flags']['boundary'] == 'not_seen'


def test_the_hand_shape_can_be_asked_about(chat):
    client, _, reading, convo = chat
    pair = ask(client, convo['id'], 'What is my hand shape?')['assistant']
    assert pair['refs'] == {'section': 'shape'}
    assert reading['report']['shape']['observed']['left']['text'] in pair['text']


def test_asking_about_someone_else_points_to_their_profile(client):
    start_guest(client)
    mine = add_profile(client, 'Saji')
    nimal = add_profile(client, 'Nimal', 'other')
    reading = make_reading(client, mine['id'])
    convo = add_conversation(client, reading['id'])
    pair = ask(client, convo['id'], "What does Nimal's heart line look like?")['assistant']
    assert pair['flags'] == {'switchProfileId': nimal['id']}
    assert 'Nimal' in pair['text'] and 'Switch to Nimal’s profile' in pair['text']
    assert 'In traditional palmistry' not in pair['text']  # nothing from this reading is used for Nimal
    # and a name that is not one of the caller's profiles gets nothing special
    assert 'switchProfileId' not in str(ask(client, convo['id'], 'What would Kamal think about my heart line?')['assistant'].get('flags'))


def test_greetings_thanks_and_off_topic_questions(chat):
    client, _, _, convo = chat
    assert 'Hello' in ask(client, convo['id'], 'Hello there')['assistant']['text']
    assert 'welcome' in ask(client, convo['id'], 'Thanks!')['assistant']['text']
    pair = ask(client, convo['id'], 'What is the capital of France?')['assistant']
    assert pair['flags'] == {'boundary': 'off_topic'} and 'only talk about what was found' in pair['text']


def test_the_reading_for_a_chat_is_the_one_it_was_started_on(client):
    start_guest(client)
    p = add_profile(client)
    first, second = make_reading(client, p['id']), make_reading(client, p['id'])
    on_first = add_conversation(client, first['id'])
    on_second = add_conversation(client, second['id'])
    assert on_first['readingId'] == first['id'] and on_second['readingId'] == second['id']
    assert {c['id'] for c in client.get(f'/v1/conversations?readingId={first["id"]}').json()} == {on_first['id']}
    assert {c['id'] for c in client.get(f'/v1/conversations?profileId={p["id"]}').json()} == {on_first['id'], on_second['id']}
    ask(client, on_first['id'], 'Hello')
    assert client.get('/v1/conversations').json()[0]['id'] == on_first['id']  # most recently updated first


def test_deleting_a_conversation_removes_its_messages(chat):
    client, _, reading, convo = chat
    ask(client, convo['id'], 'Hello')
    ask(client, convo['id'], 'Summary')
    r = client.delete(f'/v1/conversations/{convo["id"]}')
    assert r.json() == {'profiles': 0, 'readings': 0, 'conversations': 1, 'messages': 4}
    assert client.get(f'/v1/conversations/{convo["id"]}').status_code == 404
    assert client.get(f'/v1/readings/{reading["id"]}').status_code == 200  # the reading itself stays
    assert client.delete(f'/v1/conversations/{convo["id"]}').status_code == 404
    assert client.get('/v1/account/export').json()['conversations'] == []
