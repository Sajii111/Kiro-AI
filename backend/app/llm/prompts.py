"""What the language model is told, and what it is allowed to see.

This file is the specialization strategy of the report writer, in one place (docs/LLM_DESIGN.md explains it in prose):

  * a general-purpose model (Gemini), made into a palmistry writer by RETRIEVAL-AUGMENTED GENERATION: it is handed the
    curated knowledge-base entries that fit the findings, and told to stay close to them;
  * INPUT: the structured findings only, built by `findings_payload`. Every value in it comes from a short fixed list
    (a line's status, length, curve and clarity, the hand shape). It cannot carry a photo, a name, a file name or anything
    typed by a person, and tests/test_privacy.py checks that;
  * OUTPUT: one JSON object with a key for every passage asked for, in a schema the model must follow (`schema_for`);
  * SAFEGUARDS: the rules in the system prompt, then llm/guard.py checks every passage that comes back.

The report is written as many small passages (one per line per hand, one per comparison, one per theme, one overview)
rather than one long text, so each passage can be checked on its own and replaced on its own. The model writes only what
the tradition says. What the photos show (which lines were found, how the two hands differ, what was unclear) is measured,
so the server writes it itself and the model cannot get it wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.llm import kb
from app.llm.guard import Subject
from app.llm.knowledge import (
    FEATURE_NAMES,
    FEATURE_ORDER,
    THEMES,
    element_of,
    list_words,
)
from app.llm.retrieval import feature, line_entries, shape_entries
from app.schemas import HandAnalysis, Report

REPORT_PROMPT_VERSION = 'report-prompt 1.0'
CHAT_PROMPT_VERSION = 'chat-prompt 1.0'

SIDES = ('left', 'right')

REPORT_SYSTEM = """You are the report writer for Kiro AI, a palm-reading app made for reflection and entertainment. You write short passages about what traditional palmistry says. You never see the photos. A computer-vision program measured two palm photos, and its results are given to you as FINDINGS. KNOWLEDGE is a list of curated notes about what the palmistry tradition says: stay close to their wording and meaning.

Rules. Every passage must follow all of them.
1. Use only the FINDINGS and the KNOWLEDGE. Do not add lines, marks, signs, mounts or any feature that is not in the FINDINGS. Never say that you see, noticed or looked at anything.
2. Write about a line or about the hand shape only when the FINDINGS say it was detected. Never write about a line that was uncertain or not visible, except in the summary, where you say plainly that it could not be seen clearly.
3. Put everything as the tradition's reading ("In traditional palmistry ...", "is often read as ...", "is traditionally linked with ..."). Never state it as a fact about the person. Describe general temperament and themes only.
4. Never predict. Do not say what will happen, and give no ages, dates or timing. Never give advice and never tell the reader what to do or not to do. Say nothing about health, illness, how long anyone will live, money decisions, jobs or other people.
5. When the findings for the two hands differ, say so plainly. Do not make the hands match.
6. Plain text only: no lists, no markdown, no headings, no emoji. Write numbers as words. Keep each passage within the length asked for.
7. Write in calm, warm, plain English. Say "your left hand" or "your right hand" when you describe a finding.

Reply with one JSON object whose keys are exactly the keys you are asked for, each holding one passage of text."""

CHAT_SYSTEM = """You are Kiro, the assistant inside a palm-reading app made for reflection and entertainment. You talk with one person about their own reading. You never see the photos: a computer-vision program measured them, and its results (READING) and the report written from them (REPORT) are all you know about the person's hands. KNOWLEDGE holds curated notes about what traditional palmistry says.

Rules.
1. Answer only from READING, REPORT and KNOWLEDGE. Never add a line, mark or sign that is not in READING. Never say that you see, noticed or looked at anything.
2. A line that was not clearly detected (not_visible or uncertain on both hands) must not be described, and its meaning must not be given. If asked about it, say it could not be seen clearly enough in the photos and offer to explain a line that was found.
3. Put everything as the tradition's reading, never as a fact about the person or a promise: "In traditional palmistry ...", "is often read as ...". Palmistry is for reflection and entertainment and is not a science; say so briefly when asked how accurate or scientific it is.
4. Never predict what will happen, never give advice, and never say anything about health, illness, lifespan, money decisions, jobs or other people. Set `intent` to the matching value instead; the app then shows its own wording.
5. A question that has nothing to do with this reading or with palmistry gets the intent "off_topic".
6. Use the CONVERSATION to understand follow-ups such as "and the left hand?" or "why?".
7. Be clear and brief: two to six sentences, or a few short lines that each start with "• ". Plain text, no markdown, no emoji. Write numbers as words.

Reply with one JSON object with the keys: intent, answer, lines (the lines the answer is about), side (left, right, both or none), section (summary, comparison, uncertainty, themes, shape or none)."""

INTENTS = ['answer', 'medical', 'lifespan', 'financial_advice', 'employment_advice', 'relationship_advice', 'prediction', 'advice', 'off_topic']


# ------------------------------------------------------------------ what the model is told about the hands


def findings_payload(hands: dict[str, HandAnalysis]) -> dict:
    """The findings, as the model gets them. Only words from short fixed lists: no photo, no name, no file name, no
    coordinates, no scores, no photo quality. This is the whole of what leaves the server about a person's hands.

    A line that is only faintly marked is given without its clarity: the tradition has nothing to say about faintness (the
    knowledge base has no entry for it), so the model is not handed it to improvise on. The server's own text says it."""
    out: dict[str, dict] = {}
    for side in SIDES:
        hand = hands[side]
        lines: dict[str, dict] = {}
        for fid in FEATURE_ORDER:
            f = feature(hand, fid)
            entry: dict[str, str] = {'status': f.status}
            if f.status == 'detected':
                for trait in ('length', 'curve', 'clarity'):
                    value = getattr(f.traits, trait)
                    if value and not (trait == 'clarity' and value == 'faint'):
                        entry[trait] = value
            lines[fid] = entry
        shape: dict[str, str] = {'status': hand.palmShape.status}
        if hand.palmShape.status == 'detected':
            element = element_of(hand.palmShape.traits)
            for trait in ('palm', 'fingers'):
                value = getattr(hand.palmShape.traits, trait)
                if value:
                    shape[trait] = value
            if element:
                shape['element'] = element
        out[side] = {'lines': lines, 'handShape': shape}
    return out


# ------------------------------------------------------------------ the passages of a report


@dataclass(frozen=True)
class Field:
    """One passage the model is asked to write."""

    key: str
    #: summary | line | compare | shape | theme
    kind: str
    ask: str
    side: str | None = None
    line: str | None = None
    theme: str | None = None
    #: the knowledge-base entries this passage should draw on
    uses: tuple[str, ...] = ()


def detected_on(hands: dict[str, HandAnalysis], line: str) -> list[str]:
    return [side for side in SIDES if feature(hands[side], line).status == 'detected']


def shape_element(hands: dict[str, HandAnalysis], side: str) -> str | None:
    shape = hands[side].palmShape
    return element_of(shape.traits) if shape.status == 'detected' else None


def unseen_lines(hands: dict[str, HandAnalysis]) -> frozenset[str]:
    """Lines that were not detected on either hand: the model may mention them only to say they were not clearly seen."""
    return frozenset(fid for fid in FEATURE_ORDER if not detected_on(hands, fid))


def hands_match(hands: dict[str, HandAnalysis], line: str) -> bool:
    left, right = feature(hands['left'], line).traits, feature(hands['right'], line).traits
    return (left.length, left.curve) == (right.length, right.curve)


def theme_sources(hands: dict[str, HandAnalysis], theme) -> list[str]:
    """What a theme can rest on: its sources that were detected on at least one hand, in the tradition's order."""
    seen = []
    for src in theme.sources:
        if src == 'shape':
            if any(shape_element(hands, s) for s in SIDES):
                seen.append(src)
        elif detected_on(hands, src):
            seen.append(src)
    return seen


def plan_fields(hands: dict[str, HandAnalysis]) -> list[Field]:
    """The passages the model is asked to write for these findings: only where something was clearly seen. Everything else
    (a line that was not seen, the observed text, the list of what was unclear, the disclaimer) is written by the server."""
    fields: list[Field] = []
    seen_general = [f'{fid}.general' for fid in FEATURE_ORDER if detected_on(hands, fid)]
    if any(shape_element(hands, side) for side in SIDES):
        seen_general.append('shape.general')
    fields.append(
        Field(
            key='summary',
            kind='summary',
            ask=(
                'Two or three sentences, at most about 70 words: an overview of what the tradition reads from the lines (and hand shape) that '
                'were detected, naming one or two of them. Do not say which lines were or were not found and do not compare the hands: the '
                'app says that itself. End by saying plainly that palmistry is a traditional practice for reflection and entertainment and is not a science.'
            ),
            uses=('limits.not_science', *seen_general),
        )
    )
    for fid in FEATURE_ORDER:
        name = FEATURE_NAMES[fid].lower()
        for side in SIDES:
            f = feature(hands[side], fid)
            if f.status == 'detected':
                fields.append(
                    Field(
                        key=f'{fid}_{side}',
                        kind='line',
                        side=side,
                        line=fid,
                        ask=(
                            f'Two or three sentences, at most about 70 words, about the {side} hand\'s {name} only: what the tradition links '
                            f'the line with, then what it reads from the length, curve and clarity given in FINDINGS for the {side} hand. '
                            f'Do not mention the other hand.'
                        ),
                        uses=tuple(e.id for e in line_entries(fid, f.traits)),
                    )
                )
        if len(detected_on(hands, fid)) == 2:
            match = hands_match(hands, fid)
            fields.append(
                Field(
                    key=f'compare_{fid}',
                    kind='compare',
                    line=fid,
                    ask=(
                        f'One or two sentences, at most about 50 words: what the tradition reads from hands whose {name} '
                        f'{"matches" if match else "differs"}. The app has already said how the two {name}s look, so do not describe or compare them again. '
                        f'Say that this reading does not know which hand is dominant.'
                    ),
                    uses=('compare.general', 'compare.same' if match else 'compare.differ'),
                )
            )
    for side in SIDES:
        element = shape_element(hands, side)
        if element:
            fields.append(
                Field(
                    key=f'shape_{side}',
                    kind='shape',
                    side=side,
                    ask=f'Two sentences, at most about 50 words, about the shape of the {side} hand only: name its traditional element and what the tradition links it with.',
                    uses=tuple(e.id for e in shape_entries(hands[side].palmShape.traits)),
                )
            )
    for theme in THEMES:
        used = theme_sources(hands, theme)
        if not used:
            continue
        names = [('the hand shape' if s == 'shape' else FEATURE_NAMES[s].lower()) for s in used]
        entries: dict[str, None] = {kb.theme_entry(theme.id).id: None}
        for src in used:
            if src == 'shape':
                for side in SIDES:
                    element = shape_element(hands, side)
                    if element:
                        for e in shape_entries(hands[side].palmShape.traits):
                            entries[e.id] = None
            else:
                for side in detected_on(hands, src):
                    for e in line_entries(src, feature(hands[side], src).traits):
                        entries[e.id] = None
        fields.append(
            Field(
                key=f'theme_{theme.id}',
                kind='theme',
                theme=theme.id,
                ask=(
                    f'Three to five sentences, at most about 110 words, on the traditional "{theme.title}" theme, built only from these findings that '
                    f'were detected: {", ".join(names)}. Start with what the tradition reads this theme from, then what each of these adds, '
                    f'putting it as the tradition\'s reading. Do not mention any other line. Give no advice and no predictions. '
                    f'{"Put it as themes to reflect on, never as events. " if theme.id == "future" else ""}'
                    f'The app adds its own closing reminder, so do not add one.'
                ),
                uses=tuple(entries),
            )
        )
    return fields


def subject_for(field: Field, hands: dict[str, HandAnalysis]) -> Subject:
    """What the guard needs to know about a passage to judge it."""
    unseen = unseen_lines(hands)
    if field.kind == 'line':
        return Subject('line', side=field.side, traits=feature(hands[field.side], field.line).traits, unseen=unseen)  # type: ignore[index,arg-type]
    if field.kind == 'shape':
        return Subject('shape', side=field.side, shape=hands[field.side].palmShape.traits, unseen=unseen)  # type: ignore[index]
    return Subject(field.kind, unseen=unseen)


# ------------------------------------------------------------------ the request


def theme_statement(entry: kb.Entry, sources: list[str]) -> str:
    """What the tradition reads a theme from, naming ONLY the sources that were detected in this reading. The entry's own text
    names every line the tradition uses for the theme, including ones that were not seen here; handing that to the model
    would invite it to talk about them, so the model is given this instead."""
    roles = entry.get('roles')
    parts = [
        f'the {"overall hand shape" if src == "shape" else FEATURE_NAMES[src].lower()} ({roles[src]})'
        for src in entry.get('reads')
        if src in sources
    ]
    return f'In traditional palmistry, the "{entry.get("title")}" theme is read from {list_words(parts)}.'


def knowledge_text(entry: kb.Entry, hands: dict[str, HandAnalysis]) -> str:
    """What the model is shown for an entry. Everything is shown as written, except a theme, which is cut down to the sources
    this reading detected (see `theme_statement`)."""
    if entry.kind != 'theme':
        return entry.text
    theme = next(t for t in THEMES if t.id == entry.get('theme'))
    return theme_statement(entry, theme_sources(hands, theme))


def knowledge_block(entry_ids: list[str], hands: dict[str, HandAnalysis]) -> str:
    order = {e.id: i for i, e in enumerate(kb.entries())}
    ids = sorted(set(entry_ids), key=lambda i: order[i])
    return '\n'.join(f'[{i}] {knowledge_text(kb.get(i), hands)}' for i in ids)


def schema_for(fields: list[Field]) -> dict:
    """The JSON the model must return: an object with one text value for every passage asked for, and nothing else."""
    return {
        'type': 'object',
        'properties': {f.key: {'type': 'string', 'description': 'One plain-text passage, no markdown, within the length asked for.'} for f in fields},
        'required': [f.key for f in fields],
    }


def report_prompt(hands: dict[str, HandAnalysis], fields: list[Field], complaints: dict[str, list[str]] | None = None) -> str:
    """The question for one call: the findings, the knowledge that fits them, and the passages to write. `complaints` is
    set on the second try: what the checks found wrong with the passages of the first."""
    entry_ids = [i for f in fields for i in f.uses]
    parts = [
        'FINDINGS (measured from the two photos by a computer-vision program; these are the only facts you have about the hands):',
        json.dumps(findings_payload(hands), indent=1),
        '',
        'KNOWLEDGE (curated notes on what traditional palmistry says; stay close to them):',
        knowledge_block(entry_ids, hands),
        '',
        'WRITE these passages (return a JSON object with exactly these keys):',
    ]
    for f in fields:
        parts.append(f'- {f.key}: {f.ask}  [draw on: {", ".join(f.uses) or "the FINDINGS"}]')
    if complaints:
        parts += ['', 'Your earlier answer was rejected for these passages. Write them again and fix exactly these problems:']
        parts += [f'- {key}: {"; ".join(reasons)}' for key, reasons in complaints.items()]
    return '\n'.join(parts)


# ------------------------------------------------------------------ the chat

SECTIONS = ('summary', 'comparison', 'uncertainty', 'themes', 'shape')

#: the JSON the chat model must return (see CHAT_SYSTEM): what the question was, the answer, and what the answer is about
CHAT_SCHEMA: dict = {
    'type': 'object',
    'properties': {
        'intent': {'type': 'string', 'enum': INTENTS},
        'answer': {'type': 'string'},
        'lines': {'type': 'array', 'items': {'type': 'string', 'enum': list(FEATURE_ORDER)}},
        'side': {'type': 'string', 'enum': ['left', 'right', 'both', 'none']},
        'section': {'type': 'string', 'enum': [*SECTIONS, 'none']},
    },
    'required': ['intent', 'answer', 'lines', 'side', 'section'],
}


def report_context(report: Report) -> str:
    """The report as plain text for the chat model: the same words the person can read on screen, so an answer agrees with
    the report. What the photos show and what the tradition says stay apart, as they are in the report."""
    out = [f'SUMMARY: {report.summary}', '']
    for section in report.sections:
        out.append(section.title.upper())
        for side in SIDES:
            seen, tradition = getattr(section.observed, side), getattr(section.traditional, side)
            out.append(f'- {side} hand, {seen.status}: {seen.text}' + (f' Tradition: {tradition}' if tradition else ''))
        if section.comparison:
            out.append(f'- the two hands: {section.comparison}')
    out += ['', 'HAND SHAPE']
    for side in SIDES:
        seen, tradition = getattr(report.shape.observed, side), getattr(report.shape.traditional, side)
        out.append(f'- {side} hand, {seen.status}: {seen.text}' + (f' Tradition: {tradition}' if tradition else ''))
    if report.shape.comparison:
        out.append(f'- the two hands: {report.shape.comparison}')
    out += ['', 'THEMES (what the tradition reads, from the lines that were detected)']
    for theme in report.themes:
        out.append(f'- {theme.title}: {theme.traditional or "nothing is said, because the lines it is read from were not clearly seen."}')
    out += ['', 'WHAT WAS UNCLEAR OR MISSING']
    out += [f'- {item}' for item in report.uncertainty] or ['- nothing: every line was found clearly on both hands']
    return '\n'.join(out)


def chat_prompt(
    hands: dict[str, HandAnalysis],
    report: Report,
    entries: list[kb.Entry],
    history: list[tuple[str, str]],
    question: str,
) -> str:
    """The question for one chat call. `history` is (role, text) pairs, oldest first, already cleaned of personal details."""
    knowledge = '\n'.join(f'[{e.id}] {knowledge_text(e, hands)}' for e in entries) or '(nothing in the knowledge base matched this question)'
    parts = [
        'READING (measured from the two photos by a computer-vision program; these are the only facts you have about the hands):',
        json.dumps(findings_payload(hands), separators=(',', ':')),
        '',
        'REPORT (what the person can read on screen, written from the READING):',
        report_context(report),
        '',
        'KNOWLEDGE (curated notes on what traditional palmistry says; stay close to them):',
        knowledge,
        '',
        'CONVERSATION so far (oldest first):',
    ]
    parts += [f'{"Person" if role == "user" else "Kiro"}: {text}' for role, text in history] or ['(this is the first message)']
    parts += ['', f'QUESTION: {question}']
    return '\n'.join(parts)
