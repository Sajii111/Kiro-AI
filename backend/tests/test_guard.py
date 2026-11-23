"""The safety checks every passage written by the language model must pass (app/llm/guard.py). The reading speaks like a fortune
teller, so a confident prediction passes; what the rules guard is what the voice may be used for. Each rule is shown failing on a
passage that breaks it, and not failing on a passage that only mentions the thing in order to deny it."""

from __future__ import annotations

import pytest
from test_standin import hands_for

from app.llm import guard
from app.schemas import FeatureTraits, PalmShapeTraits

T = 'Your palm says that '  # a passage is about the palm: it names the palm, a line or a hand
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
    'text',
    [
        'Your heart line is long and clearly marked: love will find you easily, and you will give it back in full measure.',
        'Soon a road you have not walked opens before you, and recognition follows in time. Your life line says so.',
        'I see a generous heart in your left hand, and a mind that moves quickly.',
        'Prosperity will gather around you, one day, and your sun line promises recognition for the work of your hands.',
        'Love will find you before long, and someone may marry into your story: the heart line is the road of it.',
        'Travel calls to you in the seasons ahead, and your life line sweeps wide to meet it.',
        'You are destined for a creative life, your palm says, and in the years to come it will be known.',
        'Many years from now your palm will tell the same story, and for years you will carry this line with pride.',
    ],
)
def test_a_confident_fortune_teller_prediction_passes(text):
    assert problems(text) == [], problems(text)


@pytest.mark.parametrize(
    ('text', 'word'),
    [
        (T + 'this line means you will meet someone special within six months.', 'a time'),
        (T + 'a long line is read as a sign of what is coming next year.', 'a time'),
        (T + 'a clear line shows what you will achieve in your thirties.', 'a time'),
        (T + 'a clear line says you will find success at the age of thirty.', 'a time'),
        (T + 'a clear line says you will marry in November.', 'a time'),
        (T + 'a clear line says that in a few months your life will change.', 'a time'),
        (T + 'a clear line says that after three years love arrives.', 'a time'),
        (T + 'the line is read as warmth. You should trust your feelings more.', 'advice'),
        (T + 'the line is read as warmth. I recommend that you take time for yourself.', 'advice'),
        (T + 'a clear line says something about your health.', 'health'),
        (T + 'a clear line is read as a sign of illness.', 'health'),
        (T + 'a clear line says you will have two children.', 'health'),
        (T + 'a clear line is read as a sign of a pregnancy.', 'health'),
        (T + 'a long line means you will live a long time.', 'lifespan'),
        (T + 'a clear line is read as luck with an investment.', 'money'),
        (T + 'a clear line is read as a coming betrayal.', 'misfortune'),
        (T + 'a clear line is read as a divorce.', 'misfortune'),
        (T + 'a clear line is read as an accident on the road.', 'misfortune'),
        (T + 'a clear line is read as a curse.', 'misfortune'),
        (T + 'a clear line is read as warmth, and it is guaranteed.', 'proof'),
        (T + 'a clear line is read as warmth, and this is scientifically proven.', 'proof'),
        (T + 'a clear line is read as warmth. Be sure to follow your heart.', 'advice'),
        (T + 'a clear line is read as warmth, shown by 3 branches.', 'number'),
        (T + 'a clear line is read as warmth. See www.example.com for more.', 'link'),
        (T + 'a clear line is read as warmth. Write to me@example.com.', 'link'),
        (T + 'a clear line is read as warmth. There is a marriage line beside it.', 'not among the findings'),
        (T + 'a clear line is read as warmth, and an island in it as a sign.', 'not among the findings'),
        (T + 'a clear line is read as warmth. I have examined your photo closely.', 'looked at the photos'),
        (T + 'a clear line is read as warmth. My analysis of the picture says so.', 'looked at the photos'),
        (T + 'a clear line is read as warmth. Your photo shows it clearly.', 'looked at the photos'),
        (T + 'the fate line is read as a strong sense of direction.', 'fate line'),
        (T + 'a clear line is read as warmth on the right hand as well.', 'other hand'),
        (T + 'a clear line is read as warmth, and both hands agree.', 'other hand'),
        ('Warmth and openness in how feelings are shared, and a style of feeling.', 'not about the palm'),
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
        T + 'a clear line is read as warmth. It names no date, and it does not say within six months.',
        T + 'a clear line is read as warmth. Nothing here is advice, and you should not use it to decide anything.',
        T + 'a clear line is read as warmth. Older books link it with health, but this reading does not use that claim.',
        T + 'a clear line is read as warmth. It is a myth that a line shows how long anyone will live.',
        T + 'a clear line is read as warmth. No line foretells a betrayal, and none is promised proof.',
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
    assert guard.check(T + 'a square palm with short fingers is called an earth hand, linked with a steady, practical personality.', subject) == []
    assert has(guard.check(T + 'a long palm with short fingers is called an earth hand, linked with a steady personality.', subject), 'palm long')
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
    found = problems(T + 'a clear line will do this next year. It will do that next year. It will do more next year.')
    assert len([p for p in found if p.startswith('gives a time')]) == 3  # one per sentence, each quoted
    assert len(found) == len(set(found))


def test_a_chat_answer_about_the_reading_does_not_need_to_name_a_line():
    assert guard.check('Both photos were used, and the findings were clear on every line that was read.', guard.Subject('chat')) == []


# ---------------------------------------------------------------- plain words


@pytest.mark.parametrize(
    'word',
    [
        'tapestry', 'embraces', 'resonates', 'navigate', 'vibrant', 'resilient', 'resilience', 'intuitive', 'temperament', 'harmony',
        'abundance', 'fulfilment', 'vital energy', 'inner strength', 'energies', 'transformation', 'authentic', 'life force',
    ],
)
def test_a_fancy_or_technical_word_sends_a_report_passage_back(word):
    found = problems(T + f'your heart line is long, and {word} will follow you.')
    assert has(found, 'plain everyday words') and has(found, word), found


def test_the_complaint_names_each_fancy_word_once_so_the_model_knows_what_to_change():
    found = problems(T + 'your heart line is a tapestry, a tapestry of vibrant, intuitive love.')
    complaint = next(p for p in found if 'plain everyday words' in p)
    assert complaint.count('tapestry') == 1 and 'vibrant' in complaint and 'intuitive' in complaint


@pytest.mark.parametrize(
    'text',
    [
        'Your heart line is long, so you love openly. Love will come to you easily, and you will give plenty back.',
        'You bounce back fast, you trust your gut, and you get along with people. Your life line says so.',
        'Your head line shows a quick mind: you decide fast, and your ideas will take you far.',
        'Your sun line rises toward your ring finger. Your gifts come naturally, and other people will notice them.',
    ],
)
def test_plain_everyday_words_pass(text):
    assert problems(text) == [], problems(text)


def test_a_chat_answer_is_not_held_to_the_word_list_because_it_has_no_second_try():
    found = guard.check('Your heart line is long, and a tapestry of love will embrace you.', guard.Subject('chat'))
    assert not has(found, 'plain everyday words'), found


def test_the_guard_version_says_the_plain_words_rule_is_in():
    assert guard.GUARD_VERSION == 'guard 2.1'
