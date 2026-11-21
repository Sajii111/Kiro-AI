"""THE RULE-BASED CHAT WRITER. Port of src/api/mock/chat.ts.

Answers a question about one reading from the reading itself, with fixed wording. It behaves the way the language-model chat
(llm/chat_llm.py) must, and it is what answers whenever the model does not:

  - it answers only from this reading's findings and report (never invents a line),
  - it uses earlier messages of the same conversation for follow-ups ("and the left hand?"),
  - it says plainly when a line was uncertain or not visible,
  - it says what the tradition says about a theme (personality, career, money, relationships, future), from the
    report's themes, always as a traditional reading and never as advice or a forecast,
  - it declines medical diagnosis, financial, employment and relationship advice, lifespan, and predictions,
  - it asks the person to switch profile when they ask about someone else.

The first part, `boundary_answer`, is deterministic and runs BEFORE the language model is ever asked: a question about
another person's profile, health, lifespan, money, jobs, relationships or the future is answered here, in this file's own
wording, and never reaches Gemini. The rest, `rule_answer`, is the fallback for everything else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.llm.copy import DISCLAIMER_SHORT, PHOTO_TIPS, STATUS_LABEL
from app.llm.knowledge import FEATURE_NAMES, FEATURE_ORDER, THEME_ORDER
from app.schemas import (
    BoundaryKind,
    HandProfile,
    Message,
    MessageFlags,
    MessageRefs,
    Reading,
    ThemeSection,
)


@dataclass
class ChatContext:
    reading: Reading
    profile: HandProfile
    other_profiles: list[HandProfile]
    #: earlier messages of this conversation, oldest first
    history: list[Message] = field(default_factory=list)


@dataclass
class ChatAnswer:
    text: str
    refs: MessageRefs | None = None
    flags: MessageFlags | None = None


def rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


FEATURE_PATTERNS = {
    'heart': rx(r'\bheart\b'),
    'head': rx(r'\bhead\b|\bintellect\b'),
    'life': rx(r'\blife\b|\bvitality\b|\benergy\b'),
    'fate': rx(r'\bfate\b|\bdestiny\b'),
    'sun': rx(r'\bsun\b|\bapollo\b'),
}

# Asking what WILL happen, or to be told the future.
PREDICT = rx(r"\b(will i|am i going to|is it going to|going to happen|what will happen|predict\w*|tell me my future|my future|forecast\w*|fortune ?tell\w*|what does the future)\b")
# Asking what to DO.
ADVICE = rx(r"\b(should i|what should i|is it (a good|the right)|can i trust|advice|advise|recommend\w*)\b")


def asks_to_decide(t: str) -> bool:
    return bool(PREDICT.search(t) or ADVICE.search(t))


# Questions a reading never answers, whatever the wording.
HARD_BOUNDARIES: list[tuple[BoundaryKind, re.Pattern[str], str]] = [
    (
        'medical',
        rx(r'\b(health|healthy|sick|illness|disease|cancer|diabetes|heart attack|heart disease|heart problem|(see|visit|consult|ask|call) (a|my|the) doctor|my doctor|doctors? (said|says|told)|diagnos\w*|symptom\w*|pregnan\w*|medicine|medication|surgery|mental health|depress\w*)\b'),
        'I can’t say anything about health or medical questions, and a palm can’t diagnose anything. Palmistry is a traditional practice for reflection, not a way to see the body, and it should never replace a doctor. If you are worried about your health, please speak to a medical professional.',
    ),
    (
        'lifespan',
        rx(r'\b(how long (will|do|am) i (live|last)|when (will|am) i (die|going to die)|lifespan|life expectancy|live to|die|death)\b'),
        'The life line is not a measure of how long anyone will live. That is a common myth. In the tradition it is read as a theme of energy and vitality, and I can tell you what was found about it in your photos if you like.',
    ),
    (
        'financial',
        rx(r'\b(invest\w*|stocks?|crypto\w*|bitcoin|lottery|gambl\w*|salary|debts?|loans?|tax(es)?)\b'),
        'I can’t give money or financial guidance, and your palms can’t tell you anything about it. This reading is for reflection and entertainment only. A qualified adviser is the right place for financial questions.',
    ),
    (
        'employment',
        rx(r'\b(hired|hiring|promotion|interview\w*|employer|employment|resign\w*)\b'),
        'I can’t advise on jobs or careers, and a palm reading shouldn’t be used to make decisions about work. The reading speaks only in general traditional themes, such as temperament, and I can explain any of those.',
    ),
    (
        'relationship',
        rx(r'\b(marry|marries|married|marriage|divorc\w*|soul ?mate|break ?up|cheat\w*|boyfriend|girlfriend|husband|wife|fianc\w*|spouse)\b'),
        'I can’t give relationship advice or say what will happen with another person. The heart line is traditionally read as a theme of emotional style, and I can tell you what was found on yours. Decisions about people are best made with people you trust.',
    ),
]

# Topics a reading CAN speak about as a traditional theme, but not as advice or a forecast. These only decline
# when the question asks what will happen or what to do.
SOFT_BOUNDARIES: list[tuple[BoundaryKind, re.Pattern[str], str]] = [
    (
        'financial',
        rx(r'\b(money|finance\w*|rich|wealth\w*|income|prosper\w*|fortune)\b'),
        'I can’t give money or financial guidance, and your palms can’t tell you how things will go with money. This reading is for reflection and entertainment only. A qualified adviser is the right place for financial questions.',
    ),
    (
        'employment',
        rx(r'\b(job|jobs|career|profession\w*|work|business|employed)\b'),
        'I can’t advise on jobs or careers, and a palm reading shouldn’t be used to make decisions about work or to say how a career will go. The reading speaks only in general traditional themes, such as temperament, and I can explain any of those.',
    ),
    (
        'relationship',
        rx(r'\b(partner|relationships?|love|dating|romance|romantic)\b'),
        'I can’t give relationship advice or say what will happen with another person. The heart line is traditionally read as a theme of emotional style, and I can tell you what was found on yours. Decisions about people are best made with people you trust.',
    ),
]

THEME_PATTERNS = {
    'personality': rx(r'\b(personality|character|temperament|traits?|what am i like|who am i|my nature)\b'),
    'career': rx(r'\b(career|careers|profession\w*|work|working|job|jobs|vocation|business|occupation)\b'),
    'financial': rx(r'\b(financ\w*|money|wealth\w*|prosper\w*|rich|riches|income|abundance)\b'),
    'relationships': rx(r'\b(relationships?|love|romance|romantic|emotion\w*|feelings?|partner|dating|family|friendships?)\b'),
    'future': rx(r'\b(future|outlook|direction|life direction)\b'),
}

SHAPE_PATTERN = rx(r'\b(hand shape|palm shape|shape of (my|the) (hand|palm|hands|palms)|my hand type|hand type|earth hand|air hand|water hand|fire hand|four elements|elements?)\b')

MORE = rx(r"\b(more|why|elaborate|explain|what do you mean|how so|go on|and (the )?(left|right)|other hand|what about)\b")

ASKS_UNCLEAR_A = rx(r"\b(uncertain|unclear|not visible|missing|couldn't|could not|not clear|which lines|what wasn't|what was not)\b")
ASKS_UNCLEAR_B = rx(r"\bwhy (wasn't|was not|isn't|is not|can't|couldn't|were|are)\b.*\b(lines?|shown|found|seen|visible)\b")
ASKS_PHOTO = rx(r'\b(photo|photos|picture|image|retake|lighting|focus|blurry|better)\b')
ASKS_SUMMARY = rx(r'\b(summary|summarise|summarize|overview|overall|findings|what did you find|tell me about (my|the) reading)\b')
ASKS_ACCURACY = rx(r'\b(accurate|accuracy|science|scientific|true|real|reliable)\b')
GREETS = rx(r'^(hello|hi|hey|good (morning|afternoon|evening))\b')
THANKS = rx(r'\b(thanks|thank you|cheers)\b')
WANT_BOTH = rx(r'\b(both|compare|comparison|difference|differ\w*|side by side|each hand|left and right)\b')
LEFT = rx(r'\bleft\b')
RIGHT = rx(r'\bright\b')


def side_name(side: str) -> str:
    return 'Left' if side == 'left' else 'Right'


def last_refs(history: list[Message]) -> MessageRefs | None:
    for m in reversed(history):
        if m.role == 'assistant' and m.refs and m.refs.featureIds:
            return m.refs
    return None


def explain_feature(reading: Reading, fid: str, sides: list[str]) -> ChatAnswer:
    section = next(s for s in reading.report.sections if s.featureId == fid)
    name = FEATURE_NAMES[fid].lower()
    parts: list[str] = []
    any_unseen = False
    any_claim = False
    for side in sides:
        o = getattr(section.observed, side)
        trad = getattr(section.traditional, side)
        if o.status == 'not_visible':
            any_unseen = True
            parts.append(f'{side_name(side)} hand: the {name} was not visible in this photo, so I won’t describe it or say what it means.')
        else:
            any_claim = True
            parts.append(f'{side_name(side)} hand ({STATUS_LABEL[o.status].lower()}): {o.text}{chr(10) + trad if trad else ""}')
    if len(sides) == 2 and section.comparison:
        parts.append(f'Side by side: {section.comparison}')
    return ChatAnswer(
        text='\n\n'.join(parts),
        refs=MessageRefs(featureIds=[fid], section=fid, side=sides[0] if len(sides) == 1 else None),  # type: ignore[arg-type,list-item]
        flags=MessageFlags(disclaimer=any_claim, boundary='not_seen' if any_unseen and not any_claim else None),
    )


def theme_of(reading: Reading, theme_id: str) -> ThemeSection | None:
    return next((x for x in reading.report.themes if x.themeId == theme_id), None)


def decline_prediction(reading: Reading) -> ChatAnswer:
    """Declines to predict, and offers the one thing the tradition does say: the future outlook theme, as a reflection."""
    base = 'I can’t predict the future. Palmistry here is a traditional practice for reflection and entertainment, and no line says what will happen to anyone.'
    theme = theme_of(reading, 'future')
    if not theme or not theme.traditional:
        return ChatAnswer(text=base, flags=MessageFlags(boundary='prediction', disclaimer=True))
    return ChatAnswer(
        text=f'{base}\n\nWhat the tradition does say, as a theme to reflect on:\n\n{theme.traditional}',
        refs=MessageRefs(featureIds=[x for x in theme.basedOn if x != 'shape'], section='themes'),  # type: ignore[misc]
        flags=MessageFlags(boundary='prediction', disclaimer=True),
    )


def explain_theme(reading: Reading, ids: list[str]) -> ChatAnswer:
    """What the tradition says about a theme, from the report's themes. Never about a line that was not seen."""
    parts: list[str] = []
    lines: set[str] = set()
    any_claim = False
    for theme_id in ids:
        th = theme_of(reading, theme_id)
        if not th:
            continue
        if th.traditional:
            any_claim = True
            parts.append(f'{th.title}, as the tradition reads it:\n{th.traditional}')
            lines.update(x for x in th.basedOn if x != 'shape')
        else:
            names = [('hand shape' if x == 'shape' else FEATURE_NAMES[x].lower()) for x in th.leftOut]
            parts.append(f'{th.title}: nothing is said, because the {", ".join(names)} {"was" if len(names) == 1 else "were"} not clearly seen in this reading.')
    return ChatAnswer(
        text='\n\n'.join(parts),
        refs=MessageRefs(featureIds=[x for x in FEATURE_ORDER if x in lines], section='themes'),  # type: ignore[misc]
        flags=MessageFlags(disclaimer=any_claim, boundary=None if any_claim else 'not_seen'),
    )


def explain_shape(reading: Reading, sides: list[str]) -> ChatAnswer:
    sh = reading.report.shape
    parts: list[str] = []
    any_claim = False
    for side in sides:
        o = getattr(sh.observed, side)
        trad = getattr(sh.traditional, side)
        if o.status == 'not_visible':
            parts.append(f'{side_name(side)} hand: the shape of the hand could not be measured in this photo, so I won’t describe it.')
        else:
            any_claim = True
            parts.append(f'{side_name(side)} hand ({STATUS_LABEL[o.status].lower()}): {o.text}{chr(10) + trad if trad else ""}')
    if len(sides) == 2 and sh.comparison:
        parts.append(f'Side by side: {sh.comparison}')
    return ChatAnswer(
        text='\n\n'.join(parts),
        refs=MessageRefs(section='shape'),
        flags=MessageFlags(disclaimer=any_claim, boundary=None if any_claim else 'not_seen'),
    )


def normalise(raw: str) -> str:
    return raw.lower().replace('’', "'")


def decline_advice() -> ChatAnswer:
    return ChatAnswer(
        text=(
            'I can’t tell you what to do or whether something is a good idea. Palmistry here is a traditional practice for '
            'reflection and entertainment. I can describe what was found in your photos and what the tradition says about each line.'
        ),
        flags=MessageFlags(boundary='off_topic', disclaimer=True),
    )


def boundary_answer(raw: str, ctx: ChatContext) -> ChatAnswer | None:
    """The answer to a question this reading never answers, or None when the question is one it may answer. Another
    profile's name, health, lifespan, money, jobs, relationships, and "will I ..." or "should I ...": each has fixed
    wording. This is checked first, in plain rules, so such a question is declined whatever a language model would say."""
    t = normalise(raw)
    reading, profile = ctx.reading, ctx.profile

    # 1. Someone else's name: this chat belongs to one profile
    for other in ctx.other_profiles:
        name = other.name.lower()
        if len(other.name.strip()) >= 2 and name != profile.name.lower() and re.search(rf'\b{re.escape(name)}\b', t):
            return ChatAnswer(
                text=(
                    f'That sounds like a question about {other.name}. Each chat here belongs to one hand profile and one reading, '
                    f'so I can’t use {other.name}’s findings in {profile.name}’s chat. Switch to {other.name}’s profile and ask there, '
                    'and nothing will get mixed up.'
                ),
                flags=MessageFlags(switchProfileId=other.id),
            )

    # 2. Things this reading never does, whatever the wording
    for kind, pattern, reply in HARD_BOUNDARIES:
        if pattern.search(t):
            return ChatAnswer(text=reply, flags=MessageFlags(boundary=kind, disclaimer=True))
    # 2b. A theme the tradition does speak about, but asked as "will I..." or "should I...": decline the forecast or the advice
    if asks_to_decide(t):
        for kind, pattern, reply in SOFT_BOUNDARIES:
            if pattern.search(t):
                return ChatAnswer(text=reply, flags=MessageFlags(boundary=kind, disclaimer=True))
        if PREDICT.search(t):
            return decline_prediction(reading)
        return decline_advice()
    return None


def off_topic_answer(reading: Reading) -> ChatAnswer:
    """What is said to a question that has nothing to do with the reading: where the person can start instead."""
    rows: list[str] = []
    for fid in FEATURE_ORDER:
        s = next(x for x in reading.report.sections if x.featureId == fid)
        bits = [f'{side} {STATUS_LABEL[getattr(s.observed, side).status].lower()}' for side in ('right', 'left')]
        rows.append(f'• {s.title}: {", ".join(bits)}')
    return ChatAnswer(
        text='I can only talk about what was found in this reading. Try asking about one of the lines, or ask me to compare your hands.\n\n' + '\n'.join(rows),
        flags=MessageFlags(boundary='off_topic'),
    )


def answer(raw: str, ctx: ChatContext) -> ChatAnswer:
    """The whole rule-based answer: the boundaries first, then the reading."""
    return boundary_answer(raw, ctx) or rule_answer(raw, ctx)


def rule_answer(raw: str, ctx: ChatContext) -> ChatAnswer:
    """The answer to a question that passed `boundary_answer`, from the reading and the conversation, in fixed wording."""
    t = normalise(raw)
    reading, profile = ctx.reading, ctx.profile

    # 3. Which lines and which hands are being asked about
    ids = [fid for fid in FEATURE_ORDER if FEATURE_PATTERNS[fid].search(t)]
    want_left = bool(LEFT.search(t))
    want_right = bool(RIGHT.search(t))
    want_both = bool(WANT_BOTH.search(t)) or (want_left and want_right)
    sides = ['left', 'right'] if want_both or (not want_left and not want_right) else ['left'] if want_left else ['right']

    asks_unclear = bool(ASKS_UNCLEAR_A.search(t) or ASKS_UNCLEAR_B.search(t))
    asks_photo = bool(ASKS_PHOTO.search(t))
    asks_summary = bool(ASKS_SUMMARY.search(t)) or len(t.strip()) == 0
    asks_accuracy = bool(ASKS_ACCURACY.search(t))
    greets = bool(GREETS.search(t.strip()))
    thanks = bool(THANKS.search(t))
    whole_reading = asks_unclear or asks_photo or asks_summary or asks_accuracy or greets or thanks or (want_both and not ids)

    # 4. A follow-up with no line named: use what the last answer was about
    prev = last_refs(ctx.history)
    if not ids and prev and not whole_reading and (MORE.search(t) or want_left or want_right):
        ids = list(prev.featureIds or [])

    # 5. Questions about one or more lines
    if len(ids) == 1:
        return explain_feature(reading, ids[0], sides)
    if len(ids) > 1:
        results = [explain_feature(reading, fid, sides) for fid in ids]
        return ChatAnswer(
            text='\n\n'.join(r.text for r in results),
            refs=MessageRefs(featureIds=ids, side=sides[0] if len(sides) == 1 else None),  # type: ignore[arg-type]
            flags=MessageFlags(disclaimer=any(bool(r.flags and r.flags.disclaimer) for r in results)),
        )

    # 5b. Questions about the shape of the hand, and about a theme such as personality, career or relationships
    if SHAPE_PATTERN.search(t) and not asks_unclear:
        return explain_shape(reading, sides)
    themes = [theme_id for theme_id in THEME_ORDER if THEME_PATTERNS[theme_id].search(t)]
    if themes and not asks_unclear:
        return explain_theme(reading, themes)

    # 6. Questions about the reading as a whole
    if asks_unclear:
        items = reading.report.uncertainty
        if items:
            bullets = '\n'.join(f'• {i}' for i in items)
            text = f'Here is what was unclear or missing in this reading:\n\n{bullets}\n\nI won’t guess at any of these. A clearer photo (daylight, palm flat, in focus) usually helps.'
        else:
            text = 'Every principal line was found clearly on both hands, so there is nothing unclear to report.'
        return ChatAnswer(text=text, refs=MessageRefs(section='uncertainty'), flags=MessageFlags(boundary='not_seen') if items else None)
    if want_both:
        lines = '\n'.join(f'• {s.title}: {s.comparison or "not compared, because it was not seen clearly enough."}' for s in reading.report.sections)
        return ChatAnswer(
            text=f'Here is how your two hands compare, line by line:\n\n{lines}',
            refs=MessageRefs(section='comparison', featureIds=list(FEATURE_ORDER)),  # type: ignore[arg-type]
            flags=MessageFlags(disclaimer=True),
        )
    if asks_photo:
        tips = '\n'.join(f'• {x}' for x in PHOTO_TIPS)
        return ChatAnswer(text=f'A good photo makes the biggest difference. Try this:\n\n{tips}')
    if asks_summary:
        return ChatAnswer(
            text=reading.report.summary,
            refs=MessageRefs(section='summary', featureIds=list(FEATURE_ORDER)),  # type: ignore[arg-type]
            flags=MessageFlags(disclaimer=True),
        )
    if asks_accuracy:
        return ChatAnswer(
            text=(
                f'{DISCLAIMER_SHORT} Finding lines in a photo is also genuinely hard, which is why every line is marked '
                'detected, uncertain or not visible, and why I only talk about what was found.'
            ),
            flags=MessageFlags(disclaimer=True),
        )
    if greets:
        return ChatAnswer(text=f'Hello. This chat is about {profile.name}’s reading. Ask about any line, ask for a summary, or ask me to compare the two hands.')
    if thanks:
        return ChatAnswer(text='You’re welcome. Ask about any line, or ask me to compare your hands.')

    # 7. Anything else
    return off_topic_answer(reading)
