"""THE LANGUAGE-MODEL REPORT WRITER: Gemini writes what the tradition says, the server writes what the photos show.

Every real reading is first written completely by the fixed rules (llm/report.py). This module then asks Gemini to put the
interpretive passages into its own words, checks each one, and swaps in only the ones that pass:

    1. plan      llm/prompts.plan_fields lists the passages worth asking for: only where something was clearly seen
    2. ask       one request carries the findings (words only, never a photo), the knowledge-base entries that fit them
                 (llm/retrieval.py) and the passages to write, and asks for JSON in a fixed shape
    3. check     llm/guard.py judges every passage on its own: prediction, advice, health, invented marks, an unseen line, a
                 contradiction of the findings, numbers, missing "in traditional palmistry" framing
    4. retry     the passages that failed are asked for once more, with what was wrong, and nothing else is asked again.
                 (A request that fails because Google is busy is repeated once, after a few seconds, by llm/gemini.py.)
    5. compose   an accepted passage replaces the fixed wording; a passage that failed twice keeps the fixed wording

What the model never writes: which lines were found, how the two hands differ, what was unclear, the closing reminders and
the disclaimer. Those are measured or fixed, so the server writes them and the model cannot get them wrong. A reading always
finishes, whatever Gemini does: no key, a used-up allowance, a timeout, nonsense, or a passage that breaks a rule. In every
case the worst result is the fixed wording, and `meta` says honestly which words came from where.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.llm import guard
from app.llm.gemini import ModelService, ModelUnavailable
from app.llm.guard import GUARD_VERSION
from app.llm.knowledge import FEATURE_NAMES, KB_VERSION, THEMES
from app.llm.prompts import (
    REPORT_PROMPT_VERSION,
    REPORT_SYSTEM,
    Field,
    plan_fields,
    report_prompt,
    schema_for,
    subject_for,
)
from app.llm.report import REAL_META, SIDES, compare_parts, left_out_sentence
from app.llm.retrieval import feature
from app.schemas import HandAnalysis, Reading, ReadingMeta, Report

log = logging.getLogger('kiro.writer')

#: plenty for about twenty short passages, even if the model thinks first (thinking counts against this limit)
MAX_TOKENS = 16384

#: failures where asking again can help, because the model answered but not usably
RETRY_KINDS = frozenset({'bad_output', 'empty'})


@dataclass
class Outcome:
    """What a run of the writer produced, for the reading and for anyone who wants to look closer (the live script, the tests)."""

    report: Report
    #: the passages Gemini wrote that passed every check, by key
    accepted: dict[str, str] = field(default_factory=dict)
    #: for each passage that kept the fixed wording: what was wrong with it
    replaced: dict[str, list[str]] = field(default_factory=dict)
    asked: int = 0
    #: how many requests were made to Gemini (a repeat after a temporary failure is counted in `repeats`, not here)
    calls: int = 0
    #: how many of the requests were repeated once because Google said it was busy
    repeats: int = 0
    #: the failure that stopped a request, if one did
    error: ModelUnavailable | None = None


# ------------------------------------------------------------------ reading the answer


def parse_passages(text: str, keys: list[str]) -> dict[str, str]:
    """The passages in an answer, by key. Anything that is not a text under an asked-for key is ignored (the caller treats
    the key as missing). Raises ModelUnavailable('bad_output') when the answer is not a JSON object at all."""
    body = text.strip()
    fenced = re.match(r'^```(?:json)?\s*(.*?)\s*```$', body, re.DOTALL)
    if fenced:
        body = fenced.group(1)
    try:
        data = json.loads(body)
    except ValueError:
        raise ModelUnavailable('bad_output', 'the answer is not JSON') from None
    if not isinstance(data, dict):
        raise ModelUnavailable('bad_output', 'the answer is not a JSON object')
    return {key: data[key] for key in keys if isinstance(data.get(key), str)}


def flat(text: str) -> str:
    """A report passage is one paragraph: any line breaks the model added become spaces."""
    return ' '.join(text.split())


# ------------------------------------------------------------------ asking, checking, asking again


def write_report(
    hands: dict[str, HandAnalysis],
    baseline: Report,
    service: ModelService,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Outcome:
    """Gemini's passages, checked, laid over the fixed-rule `baseline`. Never raises for anything Gemini does."""
    fields = plan_fields(hands)
    by_key = {f.key: f for f in fields}
    accepted: dict[str, str] = {}
    reasons: dict[str, list[str]] = {}
    pending: list[Field] = list(fields)
    complaints: dict[str, list[str]] | None = None
    calls = 0
    repeats_before = service.repeats
    error: ModelUnavailable | None = None

    for attempt in range(2):
        if not pending or (cancelled is not None and cancelled()):
            break
        try:
            calls += 1
            keys = [f.key for f in pending]
            raw = service.call(
                system=REPORT_SYSTEM,
                prompt=report_prompt(hands, pending, complaints),
                schema=schema_for(pending),
                temperature=0.2,
                max_tokens=MAX_TOKENS,
                timeout_s=service.timeout_s,
                cache=True,
                validate=lambda text, keys=keys: parse_passages(text, keys),  # an answer that is not JSON is never remembered
                retries=1,  # "high demand" is usually over in seconds: one more try before the fixed wording is used
            )
            passages = parse_passages(raw, keys)
        except ModelUnavailable as exc:
            error = exc
            if exc.kind in RETRY_KINDS and attempt == 0:
                continue  # an unusable answer: the same request once more, and then the fixed wording
            break
        error = None
        rejected: dict[str, list[str]] = {}
        for f in pending:
            if f.key not in passages:
                rejected[f.key] = ['was missing from the answer']
                continue
            text = flat(guard.clean(passages[f.key]))
            problems = guard.check(text, subject_for(f, hands))
            if problems:
                rejected[f.key] = problems
            else:
                accepted[f.key] = text
        reasons.update(rejected)
        pending = [by_key[key] for key in rejected]
        complaints = rejected or None

    replaced = {f.key: reasons.get(f.key, ['was not written']) for f in fields if f.key not in accepted}
    repeats = service.repeats - repeats_before
    outcome = Outcome(report=compose(hands, baseline, accepted), accepted=accepted, replaced=replaced, asked=len(fields), calls=calls, repeats=repeats, error=error)
    log.info(
        'report: %d of %d passages by %s (%d calls, %d repeated)%s',
        len(accepted), len(fields), service.name, calls, repeats, ''.join(f'\n  replaced {k}: {"; ".join(v)}' for k, v in replaced.items()),
    )
    return outcome


# ------------------------------------------------------------------ putting the accepted passages in place


def compose(hands: dict[str, HandAnalysis], baseline: Report, accepted: dict[str, str]) -> Report:
    """A copy of the fixed-rule report with each accepted passage in its place. Whatever the photos show is left exactly as
    the server wrote it; the passage is added to it (the overview, a comparison) or put where the fixed sentence was."""
    out = baseline.model_copy(deep=True)
    if 'summary' in accepted:
        out.summary = f'{out.summary}\n{accepted["summary"]}'
    for section in out.sections:
        fid = section.featureId
        for side in SIDES:
            text = accepted.get(f'{fid}_{side}')
            if text:
                setattr(section.traditional, side, text)
        text = accepted.get(f'compare_{fid}')
        if text:
            parts = compare_parts(FEATURE_NAMES[fid], feature(hands['left'], fid), feature(hands['right'], fid))
            if parts is not None and parts[1] is not None:
                section.comparison = f'{parts[0]} {text}'
    for side in SIDES:
        text = accepted.get(f'shape_{side}')
        if text:
            setattr(out.shape.traditional, side, text)
    outros = {t.id: t.outro for t in THEMES}
    for theme in out.themes:
        text = accepted.get(f'theme_{theme.themeId}')
        if text:
            theme.traditional = '\n'.join(x for x in [text, left_out_sentence(list(theme.leftOut)), outros[theme.themeId]] if x)
    return out


# ------------------------------------------------------------------ telling the person which words came from where


def note_for(outcome: Outcome) -> str | None:
    """One plain sentence for `meta.note`. None when Gemini is not set up at all: the reading then simply says it was written
    from the knowledge base, and there is nothing more to explain."""
    written, asked = len(outcome.accepted), outcome.asked
    if written:
        if written == asked:
            return f'Gemini wrote all {asked} passages that interpret the findings, and each one passed the safety checks.'
        rest = asked - written
        why = f' and Gemini could not be asked again because {outcome.error.clause}' if outcome.error else ''
        return (
            f'Gemini wrote {written} of {asked} passages. The other {rest} did not pass a safety check{why}, '
            'so they use the fixed wording from the knowledge base.'
        )
    if outcome.error is not None:
        if outcome.error.kind == 'no_key':
            return None
        return f'Gemini was not used for this reading because {outcome.error.clause}, so the words come from the knowledge base.'
    return 'Gemini’s passages did not pass the safety checks, so the words come from the knowledge base.'


def meta_for(outcome: Outcome, service: ModelService) -> ReadingMeta:
    """`meta` for a reading: Gemini and its model name when at least one of its passages was used, otherwise the fixed-rule
    writer, with a note that says why."""
    note = note_for(outcome)
    if outcome.accepted:
        return ReadingMeta(
            provider='gemini',
            model=service.name or 'gemini',
            knowledgeBase=KB_VERSION,
            prompt=f'{REPORT_PROMPT_VERSION} + {GUARD_VERSION}',
            pipeline=REAL_META.pipeline,
            mock=False,
            note=note,
        )
    return REAL_META.model_copy(update={'note': note})


def write_reading(reading: Reading, service: ModelService, *, cancelled: Callable[[], bool] | None = None) -> Reading:
    """The reading with Gemini's checked passages in its report. A built-in sample reading, or a server with no key, is returned
    as it is. This never raises: whatever goes wrong, the reading keeps the fixed wording and says so in `meta.note`."""
    if reading.meta.mock or not service.available:
        return reading
    hands = {'left': reading.hands.left, 'right': reading.hands.right}
    try:
        outcome = write_report(hands, reading.report, service, cancelled=cancelled)
    except Exception:  # a bug here must never cost a person their reading
        log.exception('the report writer failed; the fixed wording is kept')
        return reading.model_copy(update={'meta': REAL_META.model_copy(update={'note': 'Gemini was not used for this reading because of an unexpected problem, so the words come from the knowledge base.'})})
    return reading.model_copy(update={'report': outcome.report, 'meta': meta_for(outcome, service)})
