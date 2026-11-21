"""THE LANGUAGE-MODEL CHAT: Gemini answers a question about one reading, the server decides what it may say.

Every chat message goes through `respond`, in this order:

    1. boundaries   llm/chat.boundary_answer, plain rules, no model: another profile's name, health, lifespan, money, jobs,
                    relationships, "will I ..." and "should I ...". They are declined in fixed wording and never reach Gemini.
    2. eligibility  Gemini is asked only for a real reading, when a key is set, when this chat has answers left, and when the
                    message is not a plain "hello" or "thanks" (those have friendly fixed answers).
    3. context      the server builds everything the model is told: the findings (words only), the report as the person reads
                    it, the knowledge-base entries that fit the question (BM25 keyword search, filtered to what this reading
                    shows), and the last few messages. The question and the earlier messages are scrubbed of e-mail
                    addresses, phone numbers, links and names first (llm/privacy.py). Photos are never sent.
    4. answer       one JSON reply: an intent, the answer, and what it is about. No second try: a chat should feel quick.
    5. intent       anything but "answer" (medical, lifespan, advice, a prediction, off topic) means the model recognised a
                    boundary the plain rules missed: the model's words are dropped and the fixed wording for that boundary is
                    used instead.
    6. checks       llm/guard.py judges the answer, with the chat's extra tests (a sentence about one line on one hand must
                    agree with the findings for it).
    7. fallback     whatever goes wrong (no answer, a used-up allowance, a failed check) the rule-based answer is used instead,
                    and a note says why. A question always gets an answer.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.llm import guard
from app.llm.chat import (
    GREETS,
    HARD_BOUNDARIES,
    SOFT_BOUNDARIES,
    THANKS,
    ChatAnswer,
    ChatContext,
    boundary_answer,
    decline_advice,
    decline_prediction,
    normalise,
    off_topic_answer,
    rule_answer,
)
from app.llm.gemini import ModelService, ModelUnavailable
from app.llm.knowledge import FEATURE_ORDER
from app.llm.privacy import scrub
from app.llm.prompts import (
    CHAT_SCHEMA,
    CHAT_SYSTEM,
    INTENTS,
    SECTIONS,
    chat_prompt,
    unseen_lines,
)
from app.llm.retrieval import retrieve, seen_lines
from app.schemas import Message, MessageFlags, MessageRefs, Reading

log = logging.getLogger('kiro.chat')

#: how many earlier messages the model is shown, and the most it is shown of each
HISTORY_MESSAGES = 6
HISTORY_CHARS = 500

HARD_REPLY = {kind: reply for kind, _pattern, reply in HARD_BOUNDARIES}
SOFT_REPLY = {kind: reply for kind, _pattern, reply in SOFT_BOUNDARIES}


@dataclass
class Response:
    """What the chat route needs to store and send."""

    answer: ChatAnswer
    #: "gemini" when the model wrote the answer, "knowledge-base" when it was expected to and the fixed wording answered
    #: instead, None when there was nothing to explain (no key, a boundary, a greeting)
    source: Literal['gemini', 'knowledge-base'] | None
    #: one sentence on why the model did not answer, when that is worth saying
    note: str | None
    #: how many answers to count against this chat's allowance
    model_calls: int


@dataclass
class Attempt:
    answer: ChatAnswer | None
    note: str | None
    calls: int


def failure_note(exc: ModelUnavailable) -> str | None:
    """Why the model did not answer, as one sentence. None when there is no key at all: nothing to explain then."""
    if exc.kind == 'no_key':
        return None
    return f'Gemini was not used for this answer because {exc.clause}, so it comes from the knowledge base.'


# ------------------------------------------------------------------ what the model says


def intent_answer(intent: str, reading: Reading) -> ChatAnswer:
    """The fixed wording for a boundary that the model recognised (the plain rules had not)."""
    if intent == 'medical':
        return ChatAnswer(text=HARD_REPLY['medical'], flags=MessageFlags(boundary='medical', disclaimer=True))
    if intent == 'lifespan':
        return ChatAnswer(text=HARD_REPLY['lifespan'], flags=MessageFlags(boundary='lifespan', disclaimer=True))
    if intent == 'financial_advice':
        return ChatAnswer(text=SOFT_REPLY['financial'], flags=MessageFlags(boundary='financial', disclaimer=True))
    if intent == 'employment_advice':
        return ChatAnswer(text=SOFT_REPLY['employment'], flags=MessageFlags(boundary='employment', disclaimer=True))
    if intent == 'relationship_advice':
        return ChatAnswer(text=SOFT_REPLY['relationship'], flags=MessageFlags(boundary='relationship', disclaimer=True))
    if intent == 'prediction':
        return decline_prediction(reading)
    if intent == 'advice':
        return decline_advice()
    return off_topic_answer(reading)


def parse_reply(text: str) -> dict:
    """The model's JSON reply, checked for shape. Raises ModelUnavailable('bad_output') when it cannot be used."""
    body = text.strip()
    fenced = re.match(r'^```(?:json)?\s*(.*?)\s*```$', body, re.DOTALL)
    if fenced:
        body = fenced.group(1)
    try:
        data = json.loads(body)
    except ValueError:
        raise ModelUnavailable('bad_output', 'the reply is not JSON') from None
    if not isinstance(data, dict) or data.get('intent') not in INTENTS or not isinstance(data.get('answer'), str):
        raise ModelUnavailable('bad_output', 'the reply does not have an intent and an answer')
    lines = data.get('lines') if isinstance(data.get('lines'), list) else []
    return {
        'intent': data['intent'],
        'answer': data['answer'],
        'lines': [x for x in lines if x in FEATURE_ORDER],
        'side': data.get('side') if data.get('side') in ('left', 'right', 'both', 'none') else 'none',
        'section': data.get('section') if data.get('section') in (*SECTIONS, 'none') else 'none',
    }


def refs_from(reply: dict, hands: dict) -> MessageRefs | None:
    """What the answer is about, for the chips under it: only lines that were really detected, however the model listed them."""
    seen = seen_lines(hands)
    ids = [fid for fid in FEATURE_ORDER if fid in reply['lines'] and fid in seen]
    side = reply['side'] if reply['side'] in ('left', 'right') else None
    section = None if reply['section'] == 'none' else reply['section']
    if section is None and len(ids) == 1:
        section = ids[0]
    if not (ids or side or section):
        return None
    return MessageRefs(featureIds=ids or None, side=side, section=section)  # type: ignore[arg-type]


# ------------------------------------------------------------------ asking


def history_for_prompt(history: list[Message], names: list[str]) -> list[tuple[str, str]]:
    out = []
    for m in history[-HISTORY_MESSAGES:]:
        text = scrub(m.text, names)
        out.append((m.role, text if len(text) <= HISTORY_CHARS else text[: HISTORY_CHARS - 1].rstrip() + '…'))
    return out


def ask_model(raw: str, ctx: ChatContext, service: ModelService, replies_so_far: int) -> Attempt:
    """One try at a model-written answer. `answer` is None when the fixed wording must answer instead."""
    if replies_so_far >= service.chat_limit:
        return Attempt(None, failure_note(ModelUnavailable('chat_limit')), 0)
    reading = ctx.reading
    hands = {'left': reading.hands.left, 'right': reading.hands.right}
    names = [ctx.profile.name, *[p.name for p in ctx.other_profiles]]
    question = scrub(raw, names)
    earlier = next((m.text for m in reversed(ctx.history) if m.role == 'user'), '')
    entries = retrieve(question, hands, earlier=scrub(earlier, names))
    prompt = chat_prompt(hands, reading.report, entries, history_for_prompt(ctx.history, names), question)
    try:
        text = service.call(
            system=CHAT_SYSTEM,
            prompt=prompt,
            schema=CHAT_SCHEMA,
            temperature=0.3,
            max_tokens=2048,
            timeout_s=max(10.0, service.timeout_s / 2),
        )
    except ModelUnavailable as exc:
        return Attempt(None, failure_note(exc), 0)
    try:
        reply = parse_reply(text)
    except ModelUnavailable as exc:
        return Attempt(None, failure_note(exc), 1)

    if reply['intent'] != 'answer':
        log.info('chat: the model recognised a boundary (%s)', reply['intent'])
        return Attempt(intent_answer(reply['intent'], reading), None, 1)

    answer = guard.clean(reply['answer'])
    problems = guard.check(answer, guard.Subject('chat', unseen=unseen_lines(hands), hands=hands))
    if problems:
        log.info('chat: the answer did not pass the checks: %s', '; '.join(problems))
        return Attempt(None, 'Gemini’s answer did not pass the safety checks, so this answer comes from the knowledge base.', 1)
    return Attempt(ChatAnswer(text=answer, refs=refs_from(reply, hands), flags=MessageFlags(disclaimer=True)), None, 1)


def respond(raw: str, ctx: ChatContext, service: ModelService, replies_so_far: int = 0) -> Response:
    """The answer to one chat message, and everything the route needs to say about where it came from. This blocks while
    Gemini answers (up to half the report's time limit), so the route runs it in a worker thread. It never raises for
    anything Gemini does."""
    boundary = boundary_answer(raw, ctx)
    if boundary is not None:
        return Response(boundary, None, None, 0)
    t = normalise(raw).strip()
    if not service.available or ctx.reading.meta.mock or GREETS.search(t) or THANKS.search(t):
        return Response(rule_answer(raw, ctx), None, None, 0)
    try:
        attempt = ask_model(raw, ctx, service, replies_so_far)
    except Exception:
        log.exception('the chat writer failed; the rule-based answer is used')
        attempt = Attempt(None, 'Gemini was not used for this answer because of an unexpected problem, so it comes from the knowledge base.', 0)
    if attempt.answer is None:
        return Response(rule_answer(raw, ctx), 'knowledge-base', attempt.note, attempt.calls)
    if attempt.answer.flags and attempt.answer.flags.boundary:
        return Response(attempt.answer, None, None, attempt.calls)
    return Response(attempt.answer, 'gemini', None, attempt.calls)
