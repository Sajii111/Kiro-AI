"""THE RULE-BASED CHAT WRITER. Port of src/api/mock/chat.ts.

Answers a question about one reading from the reading itself, with fixed wording, in the reader's voice (plain, direct words). It behaves the way the
language-model chat (llm/chat_llm.py) must, and it is what answers whenever the model does not:

  - it answers only from this reading's findings and report (never invents a line),
  - it uses earlier messages of the same conversation for follow-ups ("and the left hand?"),
  - it says plainly when a line was uncertain or not visible,
  - it foretells: "will I ...?" about love, work, success or what lies ahead is answered from the report's themes, which are
    written as predictions in soft time (never an age, a date or a count of months),
  - it declines, in the reader's voice, what a palm never tells: health, pregnancy and children, how long anyone will live,
    sums and investments, other people's hearts, and misfortune; it gives no orders or advice ("should I ...?"),
  - it asks the person to switch profile when they ask about someone else.

The first part, `boundary_answer`, is deterministic and runs BEFORE the language model is ever asked: a question about
another person's profile, health, lifespan, money, a job offer, another person's heart or a decision is answered here, in this
file's own wording, and never reaches Gemini. The rest, `rule_answer`, is the fallback for everything else.
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

# Asking what WILL happen, or to be told the future: the reading's own business, answered from the report's themes.
PREDICT = rx(r"\b(will i|am i going to|is it going to|going to happen|what will happen|predict\w*|tell me my future|my future|forecast\w*|fortune ?tell\w*|what does the future|what lies ahead|what is coming|what's coming)\b")
# Asking what to DO: a reader foretells, and does not decide for anyone.
ADVICE = rx(r"\b(should i|what should i|is it (a good|the right)|can i trust|advice|advise|recommend\w*)\b")


# Questions a reading never answers, whatever the wording. Each reply is the reader declining in her own voice, and pointing to
# what she does read.
HARD_BOUNDARIES: list[tuple[BoundaryKind, re.Pattern[str], str]] = [
    (
        'medical',
        rx(r'\b(health|healthy|sick|illness|disease|cancer|diabetes|heart attack|heart disease|heart problem|(see|visit|consult|ask|call) (a|my|the) doctor|my doctor|doctors? (said|says|told)|diagnos\w*|symptom\w*|pregnan\w*|fertil\w*|babies|baby|children|kids|have a child|medicine|medication|surgery|mental health|depress\w*)\b'),
        "I don't read health, pregnancy or children. A palm can't tell you anything about your body, and I'm no substitute for a doctor. If something is worrying you, please talk to a doctor. Ask me about love, work, creativity or what lies ahead instead, and I'll tell you what your lines say.",
    ),
    (
        'lifespan',
        rx(r'\b(how long (will|do|am) i (live|last)|when (will|am) i (die|going to die)|lifespan|life expectancy|live to|die|death)\b'),
        "The life line is not a clock. It shows your energy and how you handle change, not how long you will live, and nobody can read that from a palm. Ask me what your life line says about your energy and I'll tell you.",
    ),
    (
        'financial',
        rx(r'\b(invest\w*|stocks?|crypto\w*|bitcoin|lottery|gambl\w*|salary|debts?|loans?|tax(es)?)\b'),
        "I don't read sums, stocks or lotteries, and a palm can't say how much money you will have. For money questions, ask a qualified adviser. Ask me about doing well in general and I'll tell you what your lines say.",
    ),
    (
        'employment',
        rx(r'\b(hired|hiring|interview\w*|employer|employment|resign\w*|quit my|fired|laid off)\b'),
        "Who will hire you, or when, isn't written in a palm, and I won't pretend it is. What your lines do show is your drive and the recognition you will get. Ask me about your work in general and I'll tell you.",
    ),
    (
        'relationship',
        rx(r'\b(divorc\w*|break ?up|cheat\w*|unfaithful|affair|boyfriend|girlfriend|husband|wife|fianc\w*|spouse|my ex)\b'),
        "I read your hands, not another person's heart, so I can't say what will happen between you and someone else, least of all break-ups or divorce. Your heart line shows how you love. Ask me about it and I'll tell you what it says.",
    ),
]

# Topics a reading CAN foretell, but not decide: these decline only when the question asks what to DO ("should I ...?").
SOFT_BOUNDARIES: list[tuple[BoundaryKind, re.Pattern[str], str]] = [
    (
        'financial',
        rx(r'\b(money|finance\w*|rich|wealth\w*|income|prosper\w*|fortune)\b'),
        "What to do with your money isn't for a palm to decide, so ask a qualified adviser. What I can tell you is what your lines say about doing well in general. Ask me and I'll tell you.",
    ),
    (
        'employment',
        rx(r'\b(job|jobs|career|profession\w*|work|business|employed)\b'),
        "Whether to take a job or leave one is your choice, not a palm's. What I can tell you is what your lines say about your drive and the recognition you will get. Ask me about your work and I'll tell you.",
    ),
    (
        'relationship',
        rx(r'\b(partner|relationships?|love|dating|romance|romantic|marry|marries|married|marriage|wedding|soul ?mate)\b'),
        "Whether to stay or go, to trust or part, is your choice, not a palm's. What I can tell you is what your heart line says about how you love. Ask me about it and I'll tell you.",
    ),
]

THEME_PATTERNS = {
    'personality': rx(r'\b(personality|character|temperament|traits?|what am i like|who am i|my nature)\b'),
    'career': rx(r'\b(career|careers|profession\w*|work|working|job|jobs|vocation|business|occupation)\b'),
    'financial': rx(r'\b(financ\w*|money|wealth\w*|prosper\w*|rich|riches|income|abundance)\b'),
    'relationships': rx(r'\b(relationships?|love|romance|romantic|emotion\w*|feelings?|partner|dating|family|friendships?|marry|marries|married|marriage|wedding|soul ?mate)\b'),
    'future': rx(r'\b(future|outlook|direction|life direction|road ahead|what lies ahead|what is coming|what\'s coming)\b'),
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
            parts.append(f'{side_name(side)} hand: your {name} was not clear enough in this photo, so I will not read it.')
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
            parts.append(f'{th.title}, as your lines tell it:\n{th.traditional}')
            lines.update(x for x in th.basedOn if x != 'shape')
        else:
            names = [('hand shape' if x == 'shape' else FEATURE_NAMES[x].lower()) for x in th.leftOut]
            parts.append(f'{th.title}: I will say nothing about this, because the {", ".join(names)} could not be seen clearly in your photos.')
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
            parts.append(f'{side_name(side)} hand: the shape of the hand was not clear enough in this photo, so I will not read it.')
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
            "I don't give orders or advice. What you choose is up to you: I tell you what your lines say. "
            'Ask me about any line, or about love, work, creativity or what lies ahead.'
        ),
        flags=MessageFlags(boundary='off_topic', disclaimer=True),
    )


def boundary_answer(raw: str, ctx: ChatContext) -> ChatAnswer | None:
    """The answer to a question this reading never answers, or None when the question is one it may answer. Another
    profile's name, health, lifespan, sums of money, a job offer, another person's heart, and "should I ...": each has fixed
    wording, in the reader's voice. This is checked first, in plain rules, so such a question is declined whatever a language
    model would say. "Will I ...?" about love, work, prosperity or the road ahead is not declined: it is what a reading is for."""
    t = normalise(raw)
    profile = ctx.profile

    # 1. Someone else's name: this chat belongs to one profile
    for other in ctx.other_profiles:
        name = other.name.lower()
        if len(other.name.strip()) >= 2 and name != profile.name.lower() and re.search(rf'\b{re.escape(name)}\b', t):
            return ChatAnswer(
                text=(
                    f'That sounds like a question about {other.name}. Each chat here belongs to one hand profile and one reading, '
                    f'so I can’t use {other.name}’s reading in {profile.name}’s chat. Switch to {other.name}’s profile and ask there, '
                    'and nothing will get mixed up.'
                ),
                flags=MessageFlags(switchProfileId=other.id),
            )

    # 2. Things this reading never does, whatever the wording
    for kind, pattern, reply in HARD_BOUNDARIES:
        if pattern.search(t):
            return ChatAnswer(text=reply, flags=MessageFlags(boundary=kind, disclaimer=True))
    # 2b. A choice to make ("should I ...?"): a reader foretells and does not decide. A topic she does read gets words of its own
    if ADVICE.search(t):
        for kind, pattern, reply in SOFT_BOUNDARIES:
            if pattern.search(t):
                return ChatAnswer(text=reply, flags=MessageFlags(boundary=kind, disclaimer=True))
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
        text="I only read palms, so I can't help with that. Ask about one of your lines, about love, work or what lies ahead, or ask me to compare your hands.\n\n" + '\n'.join(rows),
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
    if not themes and PREDICT.search(t):
        themes = ['future']  # "will I ...?" with no topic named is a question about the road ahead
    if themes and not asks_unclear:
        return explain_theme(reading, themes)

    # 6. Questions about the reading as a whole
    if asks_unclear:
        items = reading.report.uncertainty
        if items:
            bullets = '\n'.join(f'• {i}' for i in items)
            text = f'Here is what could not be seen clearly:\n\n{bullets}\n\nI will not guess at what I cannot see. A clearer photo (daylight, palm flat, in focus) will help.'
        else:
            text = 'Every main line was clear on both hands, so nothing is missing.'
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
                'detected, uncertain or not visible, and why I speak only of what was found.'
            ),
            flags=MessageFlags(disclaimer=True),
        )
    if greets:
        return ChatAnswer(text=f'Welcome. Let us read {profile.name}’s hands. Ask about any line, about love, work or what lies ahead, or ask me to compare the two hands.')
    if thanks:
        return ChatAnswer(text='You are welcome. Ask about any line, about what lies ahead, or ask me to compare your hands.')

    # 7. Anything else
    return off_topic_answer(reading)
