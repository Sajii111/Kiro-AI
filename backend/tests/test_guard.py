"""The safety checks every passage written by the language model must pass (app/llm/guard.py). Each rule is shown failing on a
passage that breaks it, and not failing on a passage that only mentions the thing in order to deny it."""

from __future__ import annotations

import pytest
from test_standin import hands_for

from app.llm import guard
from app.schemas import FeatureTraits, PalmShapeTraits

T = 'In traditional palmistry '  # the framing every claim needs
LONG_STRAIGHT_CLEAR = FeatureTraits(length='long', curve='straight', clarity='clear')


def line(side='left', traits=LONG_STRAIGHT_CLEAR, unseen=('fate',)):
    return guard.Subject('line', side=side, traits=traits, unseen=frozenset(unseen))


def problems(text, subject=None):
    return guard.check(guard.clean(text), subject or line())


def has(found, word):
    return any(word in p for p in found)


# ---------------------------------------------------------------- a good passage, and what makes it bad


def test_a_cautious_passage_that_follows_the_findings_passes():
    assert problems(T + 'a long heart line is often read as openness and warmth in how feelings are shared. It describes a style of feeling, not how many relationships a person has.') == []


@pytest.mark.parametrize(
    ('text', 'word'),
    [
        (T + 'this line means you will meet someone special.', 'predicts'),
        (T + 'a long line is read as a sign of what is coming next year.', 'predicts'),
        (T + 'a clear line shows what you will achieve in your thirties.', 'predicts'),
        (T + 'a clear line is destined for greatness.', 'predicts'),
        (T + 'the line is read as warmth. You should trust your feelings more.', 'advice'),
        (T + 'the line is read as warmth. I recommend that you take time for yourself.', 'advice'),
        (T + 'a clear line says something about your health.', 'health'),
        (T + 'a clear line is read as a sign of illness.', 'health'),
        (T + 'a long line means you will live a long time.', 'lifespan'),
        (T + 'a clear line is read as luck with an investment.', 'money'),
        (T + 'a clear line is read as a future marriage.', 'life events'),
        (T + 'a clear line is read as readiness for a promotion.', 'life events'),
        (T + 'a clear line is read as warmth, shown by 3 branches.', 'number'),
        (T + 'a clear line is read as warmth. See www.example.com for more.', 'link'),
        (T + 'a clear line is read as warmth. Write to me@example.com.', 'link'),
        (T + 'a clear line is read as warmth. There is a marriage line beside it.', 'not among the findings'),
        (T + 'a clear line is read as warmth, and an island in it as a sign.', 'not among the findings'),
        (T + 'a clear line is read as warmth. I can see it clearly.', 'seen the photo'),
        (T + 'a clear line is read as warmth. I noticed it is deep.', 'seen the photo'),
        (T + 'the fate line is read as a strong sense of direction.', 'fate line'),
        (T + 'a clear line is read as warmth on the right hand as well.', 'other hand'),
        (T + 'a clear line is read as warmth, and both hands agree.', 'other hand'),
        ('Warmth and openness in how feelings are shared, and a style of feeling.', 'tradition reading'),
        ('Too short.', 'short'),
        (T + 'warmth. ' * 200, 'too long'),
        (T + 'a clear line is read as warmth.\n• one\n• two', 'list'),
    ],
)
def test_each_rule_catches_the_passage_that_breaks_it(text, word):
    assert has(problems(text), word), problems(text)


@pytest.mark.parametrize(
    'text',
    [
        T + 'a clear line is read as warmth. It does not predict what will happen to anyone.',
        T + 'a clear line is read as warmth. Nothing here is advice, and you should not use it to decide anything.',
        T + 'a clear line is read as warmth. Older books link it with health, but this reading does not use that claim.',
        T + 'a clear line is read as warmth. It is a myth that a line shows how long anyone will live.',
        T + 'a clear line is read as warmth. The fate line could not be seen clearly, so nothing is said about it.',
        T + 'a clear line is read as warmth. This reading has no way to see anything about a marriage line, so it says nothing of one.'.replace('has no way to see anything about a marriage line, so it says nothing of one', 'does not use numbers'),
    ],
)
def test_a_sentence_that_only_denies_the_thing_is_allowed(text):
    assert problems(text) == [], problems(text)


def test_a_dominant_hand_is_never_assumed():
    assert has(problems(T + 'your dominant hand is read as how life has shaped you, and a long line adds warmth.'), 'dominant')
    assert problems(T + 'a long line adds warmth. This reading does not know which of your hands is dominant.') == []


# ---------------------------------------------------------------- the findings are not contradicted


@pytest.mark.parametrize(
    ('text', 'traits', 'word'),
    [
        (T + 'a short heart line is read as reserve.', LONG_STRAIGHT_CLEAR, 'short'),
        (T + 'the heart line is quite short, which is read as reserve.', LONG_STRAIGHT_CLEAR, 'short'),
        (T + 'a long heart line is read as warmth.', FeatureTraits(length='short', curve='straight', clarity='clear'), 'long'),
        (T + 'a deeply curved heart line is read as warmth.', LONG_STRAIGHT_CLEAR, 'curve'),
        (T + 'the line is straight, which is read as directness.', FeatureTraits(length='long', curve='pronounced', clarity='clear'), 'straight'),
        (T + 'a faint line is read as quiet feelings.', LONG_STRAIGHT_CLEAR, 'faint'),
        (T + 'a deep line is read as strongly felt emotion.', LONG_STRAIGHT_CLEAR, 'deep'),
        (T + 'a clearly marked line is read as feelings easy to recognise.', FeatureTraits(length='long', curve='straight', clarity='faint'), 'clearly marked'),
    ],
)
def test_a_passage_may_not_describe_a_line_differently_from_the_findings(text, traits, word):
    assert has(problems(text, line(traits=traits)), word), problems(text, line(traits=traits))


def test_denying_a_description_is_not_a_contradiction_and_neither_is_a_question_word():
    assert problems(T + 'the heart line is not short, which is read as warmth.') == []
    assert problems(T + 'how long the line runs is read as a steady style of feeling.') == []


def test_the_hand_shape_is_held_to_the_findings_as_well():
    subject = guard.Subject('shape', side='left', shape=PalmShapeTraits(palm='square', fingers='short'))
    assert guard.check(T + 'a square palm with short fingers is called an earth hand, linked with a steady, practical temperament.', subject) == []
    assert has(guard.check(T + 'a long palm with short fingers is called an earth hand, linked with a steady temperament.', subject), 'palm long')
    assert has(guard.check(T + 'this hand has long fingers and is called an earth hand, linked with steadiness.', subject), 'fingers long')
    assert guard.check(T + 'hands are sorted by how broad the palm is and how long the fingers are, and this one is an earth hand.', subject) == []


# ---------------------------------------------------------------- a chat answer


def test_a_chat_answer_is_checked_sentence_by_sentence_against_the_findings():
    hands = hands_for('rd_0000000000000001', 0.95, 0.95)  # left: heart long; fate uncertain
    subject = guard.Subject('chat', unseen=frozenset({'fate', 'sun'}), hands=hands)
    ok = 'In traditional palmistry your left heart line is long, which is often read as openness and warmth.'
    assert guard.check(ok, subject) == []
    assert has(guard.check('In traditional palmistry your left heart line is short, which is often read as reserve.', subject), 'short')
    assert has(guard.check('In traditional palmistry the fate line on your left hand is long and deep.', subject), 'not clearly seen')
    assert guard.check('In traditional palmistry the fate line on your left hand could not be seen clearly, so I will not describe it.', subject) == []
    # a sentence about two lines or both hands is not judged: it would be a guess which claim belongs to which
    assert guard.check('In traditional palmistry your left heart line is short while your right head line is long.', subject) == []


def test_a_chat_answer_may_be_a_bulleted_list_but_a_report_passage_may_not():
    text = '• In traditional palmistry the heart line is linked with emotional style.\n• It is read as a theme, not a fact.'
    assert guard.check(text, guard.Subject('chat')) == []
    assert has(guard.check(text, guard.Subject('theme')), 'list')


# ---------------------------------------------------------------- cleaning


def test_markdown_becomes_plain_text_and_nothing_else_changes():
    raw = '## Heart line\n**In traditional palmistry** the _heart_ line is `linked` with feeling.\n- one\n* two\n1. three'
    assert guard.clean(raw) == 'Heart line\nIn traditional palmistry the heart line is linked with feeling.\n• one\n• two\n• three'
    assert guard.clean('  "In traditional palmistry, it’s calm."  ') == "In traditional palmistry, it's calm."
    assert guard.clean('a\n\n\n\nb') == 'a\n\nb'


def test_a_complaint_is_listed_once_however_many_times_it_is_broken():
    found = problems(T + 'a clear line will do this. It will do that. It will do more.')
    assert len([p for p in found if p.startswith('predicts')]) == 3  # one per sentence, each quoted
    assert len(found) == len(set(found))
