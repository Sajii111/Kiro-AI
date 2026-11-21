"""Checks that Gemini works with Kiro AI. Run it once after you put your key in backend\\.env.

    run.bat gemini                       Windows
    run.bat gemini --model NAME          try another model without editing .env (for example gemini-2.5-flash)
    run.bat gemini --probe               try several models with one tiny request each, and say which ones work for your key
    run.bat gemini --list-models         list the models your key may use, then stop
    run.bat gemini --quick               only steps 1 and 2 (the key and one tiny request)
    run.bat gemini --full                show every passage Gemini wrote (the default shows the first four)
    run.bat gemini --out FOLDER          keep the text copy somewhere else (default: ..\\debug)
    python scripts/check_gemini.py ...   the same, from any terminal (use the Python in backend/.venv)

What it does, in order (about eight requests in all, a small part of the free allowance):

    1  settings     reads backend\\.env and says whether a key is there. The key itself is NEVER printed.
    2  connection   one tiny request, to see that Google accepts the key and the model name
    3  report       a report for two MADE-UP hands (no photos, no person): Gemini writes the passages, every one is checked
    4  chat         five questions Gemini answers, and three that must be turned away without asking Gemini at all

Nothing about you is sent. The made-up hands are described in words ("heart line: long, gentle curve") and that is all Google
gets: never a photo, a name or a contact detail. It ends with  RESULT: PASS  or  RESULT: FAIL  (exit code 0 or 1).
PASS means Gemini answered and its words got through the safety checks. Whether the words are GOOD is for you to judge: read them.

A text copy of everything it prints is saved as  ..\\debug\\check_gemini.txt  (the key is never in it, and the hands are made up), so
that nobody has to copy a long screen by hand: it can be read from that file.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import textwrap
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, 'reconfigure'):  # a Windows console may not speak UTF-8; never let a print crash the check
    sys.stdout.reconfigure(errors='replace')

try:
    from app.core.config import BACKEND_DIR, Settings, read_settings
    from app.core.rand import hash_string
    from app.cv.standin import build_analysis, plan_statuses
    from app.llm.chat import ChatContext
    from app.llm.chat_llm import Response, respond
    from app.llm.gemini import (
        ModelService,
        ModelUnavailable,
        classify,
        redact,
        service_from_settings,
    )
    from app.llm.prompts import findings_payload, plan_fields
    from app.llm.report import build_report
    from app.llm.writer import Outcome, meta_for, note_for, write_report
    from app.schemas import (
        HandAnalysis,
        HandProfile,
        Hands,
        Message,
        PhotoQuality,
        PhotoSize,
        Reading,
    )
except ImportError:
    print()
    print('  The Python packages are not installed in this Python.')
    print('  Run  run.bat  once (it makes backend\\.venv and installs them), then use  run.bat gemini')
    print()
    raise SystemExit(1) from None

#: the made-up hands: a reading with twenty passages to write, two hands that differ a little
MADE_UP = 'rd_check_gemini_0005'

TINY_SCHEMA = {'type': 'object', 'properties': {'reply': {'type': 'string'}}, 'required': ['reply']}

#: the chat questions Gemini should answer, in order. The second one only makes sense after the first (it tests the memory).
QUESTIONS = [
    'What does my heart line say?',
    'How is it different between my two hands?',
    'What does the tradition say about my head line?',
    'How sure is the app about these findings?',
    'I read that a long life line means a long life. Is that true?',
]
#: questions that the app must turn away with fixed wording, without asking Gemini
BOUNDARIES = ['Will I get married?', 'How long will I live?', 'Should I quit my job?']

#: used when Google's list of models cannot be fetched
FALLBACK_MODELS = ['gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-flash']
NOT_FOR_TEXT = ('embedding', 'tts', 'image', 'live', 'audio', 'robotics', 'computer-use', 'aqa', 'imagen', 'veo', 'learnlm')

DEBUG = ROOT.parent / 'debug'
WIDTH = 100


#: everything printed, kept so that a text copy can be saved. It holds nothing about a person: the hands are made up, and the key
#: is never printed.
LOG: list[str] = []


def say(text: str = '') -> None:
    LOG.append(text)
    print(text, flush=True)


def wrapped(text: str, indent: str = '     ', first: str | None = None) -> None:
    lines = textwrap.wrap(text, WIDTH - len(indent), initial_indent=first if first is not None else indent, subsequent_indent=indent, break_long_words=False)
    say('\n'.join(lines) if lines else '')


def heading(number: int, text: str) -> None:
    say()
    say(f'[{number}/4] {text}')


def plural(n: int, word: str) -> str:
    return f'{n} {word}' + ('' if n == 1 else 's')


# ------------------------------------------------------------------ 1. settings


def key_problems(key: str) -> list[str]:
    """Certain mistakes in a pasted key, found without printing any of it. (Google's key format is not assumed.)"""
    problems = []
    if any(ch.isspace() for ch in key):
        problems.append('it contains a space or a line break')
    if not key.isascii():
        problems.append('it contains a character that is not a plain letter, digit or symbol (a curly quote or a long dash from copying?)')
    if key[:1] in ('"', "'", '`') or key[-1:] in ('"', "'", '`'):
        problems.append('it starts or ends with a quote mark')
    if key.upper().startswith('GEMINI_API_KEY'):
        problems.append('it repeats the name GEMINI_API_KEY')
    if key.lower() in ('your-key', 'your_key', 'your-key-here', 'paste-your-key-here', 'xxx', 'changeme'):
        problems.append('it is still the placeholder text')
    return problems


def show_settings(settings: Settings) -> bool:
    """Step 1. False when there is no key to try."""
    heading(1, 'Settings')
    env = BACKEND_DIR / '.env'
    key = settings.gemini_api_key
    say(f'     backend\\.env ...... {"found" if env.is_file() else "NOT FOUND"}')
    say(f'     GEMINI_API_KEY .... {"present" if key else "MISSING"}')
    say(f'     model ............. {settings.gemini_model}')
    say(f'     thinking .......... {settings.gemini_thinking or "(the model\'s own default)"}')
    say(f'     limits ............ {settings.gemini_per_minute} requests a minute, {settings.gemini_timeout_s} s per report, {settings.gemini_chat_limit} chat answers per session')
    say('     Sent to Google: only the findings, as words. Never photos, names or contact details.')
    say("     On Google's free tier, Google may use what it receives to improve its products, and people may read it.")
    if not key:
        say()
        wrapped('There is no key yet. To get one (free, no card needed):', '  ')
        for step in (
            '1. Open https://aistudio.google.com/apikey and sign in with a Google account.',
            '2. Choose "Create API key", and copy it. Do NOT turn on billing.',
            '3. If backend\\.env does not exist, copy backend\\.env.example to backend\\.env.',
            '4. Open backend\\.env in Notepad, add a line   GEMINI_API_KEY=your-key   (no quotes, no spaces) and save it.',
            '5. Run this again.',
        ):
            wrapped(step, '     ', '    ')
        wrapped('Never paste the key into a chat, an e-mail or any file that is committed.', '  ')
        return False
    for problem in key_problems(key):
        say(f'     WARNING: the key looks wrong: {problem}. Check the line in backend\\.env.')
    return True


# ------------------------------------------------------------------ 2. one tiny request


def check_tiny(text: str) -> None:
    try:
        data = json.loads(text)
    except ValueError:
        raise ModelUnavailable('bad_output', 'the answer was not JSON') from None
    if not isinstance(data, dict) or not isinstance(data.get('reply'), str):
        raise ModelUnavailable('bad_output', 'the answer had no "reply" text')


def tiny_request(service: ModelService) -> float:
    """Seconds one tiny request took. Raises ModelUnavailable."""
    started = time.monotonic()
    service.call(
        system='You reply with JSON only.',
        prompt='Put the single word ready in the reply field.',
        schema=TINY_SCHEMA,
        temperature=0.0,
        max_tokens=1024,  # a model that thinks first spends some of this on thinking
        timeout_s=min(service.timeout_s, 40.0),
        validate=check_tiny,
        retries=1,  # as in the app: "high demand" is usually over in a few seconds
    )
    return time.monotonic() - started


ADVICE = {
    'bad_key': 'Check the line GEMINI_API_KEY=... in backend\\.env: the whole key, no quotes, no spaces. If it is right, make a new key at https://aistudio.google.com/apikey',
    'bad_model': 'Google does not know that model name. Put a name from the list below in backend\\.env as GEMINI_MODEL=..., or try it first with   run.bat gemini --model NAME',
    'rate_limited': "The free allowance for this model is used up, or this model has none for your key. Wait a minute and try again, or try another model: run.bat gemini --probe shows which ones work.",
    'region': "Google says the Gemini API (or its free tier) is not offered from here. Tell me exactly what it said above, and do not turn on billing.",
    'bad_request': 'Google refused the request itself (a setting or the answer format). Tell me exactly what it said above: the program can be changed to fit.',
    'overloaded': "Google says this model is very busy right now. That is usually over within minutes (the free tier is shared). Run this again in a few minutes, or try another model: run.bat gemini --probe shows which ones work.",
    'timeout': 'Google did not answer in time. Check the internet connection (and any proxy or company network) and try again.',
    'error': 'Google could not be reached, or it failed. Check the internet connection (and any proxy or company network), then try again.',
    'cut_off': 'The model ran out of room before it finished, probably because it spent it thinking. Try   run.bat gemini --thinking LOW   (or MINIMAL).',
    'empty': 'The model sent back nothing. Try again; if it repeats, try   run.bat gemini --thinking LOW   or another model.',
    'bad_output': 'The model answered, but not in the form that was asked for. Tell me what it says above.',
    'blocked': 'Google declined to answer. Tell me what it says above.',
}


def show_failure(exc: ModelUnavailable, key: str) -> None:
    say(f'     FAILED  [{exc.kind}]  {exc.reason}')
    if exc.detail:
        wrapped(f'Google said: {redact(exc.detail, key, 400)}', '       ')
    advice = ADVICE.get(exc.kind)
    if advice:
        wrapped(f'What to do: {advice}', '       ')


def fetch_model_names(key: str) -> list[str]:
    """The Gemini models this key may use to write text (names only). Raises ModelUnavailable when Google refuses."""
    from google import genai

    names: set[str] = set()
    try:
        for model in genai.Client(api_key=key).models.list():
            name = str(getattr(model, 'name', '') or '').removeprefix('models/')
            if name.startswith('gemini') and 'generateContent' in (getattr(model, 'supported_actions', None) or []) and not any(w in name for w in NOT_FOR_TEXT):
                names.add(name)
    except Exception as exc:  # noqa: BLE001 - the library and the network raise many kinds of error; each becomes one, with the key removed
        raise classify(exc, key) from None
    return sorted(names)


def show_models(key: str) -> list[str]:
    try:
        names = fetch_model_names(key)
    except ModelUnavailable as exc:
        say('     Could not get the list of models:')
        show_failure(exc, key)
        return []
    say(f'     The models this key may use ({len(names)}):')
    for name in names:
        say(f'       {name}')
    return names


def candidates(names: list[str], current: str) -> list[str]:
    """The models worth trying with --probe: the chosen one first, then Flash-Lite and Flash ones (stable names before previews)."""
    pool = [n for n in names if 'flash' in n or 'lite' in n] or FALLBACK_MODELS

    def rank(name: str) -> tuple[int, int, str]:
        unstable = any(w in name for w in ('preview', 'exp', 'latest'))
        return (0 if name == current else 1, (2 if unstable else 0) + (0 if 'lite' in name else 1), name)

    return sorted({current, *pool}, key=rank)[:8]


def probe(settings: Settings, make_service: Callable[[Settings], ModelService]) -> int:
    say()
    say('Trying one tiny request with each model (a model with no free allowance for your key says so):')
    key = settings.gemini_api_key
    try:
        names = fetch_model_names(key)
    except ModelUnavailable:
        names = []
    working = []
    for name in candidates(names, settings.gemini_model):
        service = make_service(settings.with_(gemini_model=name))
        try:
            seconds = tiny_request(service)
            say(f'  works     {name}   ({seconds:.1f} s)')
            working.append(name)
        except ModelUnavailable as exc:
            say(f'  {exc.kind:9s} {name}   {redact(exc.detail, key, 160)}')
    say()
    if working:
        say(f'  Models that work for your key: {", ".join(working)}')
        say('  To use one, put   GEMINI_MODEL=<name>   in backend\\.env (or try it first with   run.bat gemini --model NAME).')
    else:
        say('  No model answered. Tell me the lines above.')
    return 0 if working else 1


# ------------------------------------------------------------------ 3. a report for two made-up hands


def made_up_hands() -> dict[str, HandAnalysis]:
    """Two drawn-by-the-program hands (the same ones every time). They belong to nobody."""
    seed = hash_string(MADE_UP)
    level = PhotoQuality(sharpness='good', lighting='good', resolution='good', palmVisible=True, score=0.95)
    quality = {'left': level, 'right': level}
    plan = plan_statuses(seed, quality)
    size = PhotoSize(width=800, height=1000)
    return {side: build_analysis(side, plan[side], size, quality[side], seed) for side in ('left', 'right')}  # type: ignore[arg-type]


def show_passages(accepted: dict[str, str], everything: bool) -> None:
    keys = list(accepted)
    shown = keys if everything else keys[:4]
    for key in shown:
        say()
        wrapped(accepted[key], '       ', f'     {key}:  ')
    if len(shown) < len(keys):
        say()
        say(f'     ({len(keys) - len(shown)} more passages: run with --full to see them all)')


def report_step(service: ModelService, hands: dict[str, HandAnalysis], everything: bool, key: str) -> tuple[Outcome, str]:
    """Step 3. Returns (what the writer produced, the time it was made)."""
    heading(3, 'Report: Gemini writes the passages for two made-up hands (no photos)')
    fields = plan_fields(hands)
    say(f'     {len(fields)} passages are asked for. This is everything about the hands that Gemini is told:')
    payload = findings_payload(hands)
    for side in ('left', 'right'):
        wrapped(json.dumps(payload[side], separators=(',', ':')), '       ', f'     {side:5s} ')
    say('     (the instructions and the matching knowledge-base text go with it; no photo, no name)')
    say('     Asking Gemini... (this can take up to a minute)')
    now = datetime.now(UTC).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    baseline = build_report(hands, now)
    started = time.monotonic()
    outcome = write_report(hands, baseline, service)
    seconds = time.monotonic() - started
    got = len(outcome.accepted)
    repeated = ', repeated once because Google was busy' if outcome.repeats else ''
    say(f'     Gemini wrote {got} of {outcome.asked} passages that passed every check ({plural(outcome.calls, "request")}{repeated}, {seconds:.1f} s).')
    if outcome.replaced:
        say('     These keep the fixed wording, and why (a refused passage is the safety checks doing their job):')
        for passage_key, reasons in outcome.replaced.items():
            wrapped(f'{passage_key}: {"; ".join(reasons)}', '         ', '       ')
    if outcome.error is not None:
        show_failure(outcome.error, key)
    note = note_for(outcome)
    if note:
        wrapped(f'What the reading would say about this: "{note}"', '       ', '     ')
    show_passages(outcome.accepted, everything)
    return outcome, now


# ------------------------------------------------------------------ 4. the chat


def refs_text(answer) -> str:
    refs = answer.refs
    if refs is None:
        return 'no references'
    parts = []
    if refs.featureIds:
        parts.append('lines ' + '+'.join(refs.featureIds))
    if refs.side:
        parts.append(f'{refs.side} hand')
    if refs.section:
        parts.append(f'section {refs.section}')
    return ', '.join(parts) or 'no references'


def wait_if_resting(service: ModelService, sleep: Callable[[float], None]) -> None:
    """Google may ask for a pause after a rate limit. Waiting a little keeps the rest of the check meaningful."""
    rest = service.resting_for()
    if 0 < rest <= 90:
        say(f'     (Gemini asked for a pause: waiting {rest:.0f} s)')
        sleep(rest + 1)


def chat_step(service: ModelService, reading: Reading, sleep: Callable[[float], None]) -> tuple[int, int, int]:
    """Step 4. Returns (answers Gemini wrote, boundary questions turned away correctly, boundary questions asked)."""
    heading(4, 'Chat: five questions for Gemini, and three it must never be asked')
    profile = HandProfile(id='prf_check', name='Check', owner='self', consent=True, createdAt=reading.createdAt, readingCount=1, lastReadingAt=reading.createdAt)
    history: list[Message] = []
    gemini_answers = replies_so_far = 0

    def remember(role: str, text: str) -> None:
        history.append(Message(id=f'msg_{len(history):04d}', conversationId='cnv_check', role=role, text=text, createdAt=reading.createdAt))  # type: ignore[arg-type]

    def ask(question: str) -> tuple[Response, float]:
        nonlocal replies_so_far
        started = time.monotonic()
        response = respond(question, ChatContext(reading=reading, profile=profile, other_profiles=[], history=list(history)), service, replies_so_far)
        replies_so_far += response.model_calls
        remember('user', question)
        remember('assistant', response.answer.text)
        return response, time.monotonic() - started

    for number, question in enumerate(QUESTIONS, 1):
        say()
        say(f'     Q{number}: {question}')
        wait_if_resting(service, sleep)
        response, seconds = ask(question)
        who = {'gemini': 'GEMINI wrote this', 'knowledge-base': 'the KNOWLEDGE BASE wrote this', None: 'fixed wording, Gemini was not asked'}[response.source]
        say(f'     -> {who} ({seconds:.1f} s; {refs_text(response.answer)})')
        if response.note:
            wrapped(f'Why not Gemini: {response.note}', '        ', '        ')
        wrapped(response.answer.text, '        ', '        ')
        gemini_answers += response.source == 'gemini'

    say()
    say('     Now three questions that the app must turn away with fixed wording, without asking Gemini at all:')
    turned_away = 0
    for question in BOUNDARIES:
        calls_before = service.calls
        response, _seconds = ask(question)
        boundary = response.answer.flags.boundary if response.answer.flags else None
        correct = boundary is not None and response.source is None and service.calls == calls_before and response.model_calls == 0
        turned_away += correct
        say(f'     {"OK  " if correct else "FAIL"} "{question}"  -> boundary: {boundary}, Gemini asked: {"no" if service.calls == calls_before else "YES"}')
    return gemini_answers, turned_away, len(BOUNDARIES)


# ------------------------------------------------------------------ main


def save_copy(folder: Path) -> Path | None:
    """Writes what was printed to check_gemini.txt in `folder`. A folder that cannot be written is said, not fatal."""
    target = folder / 'check_gemini.txt'
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target.write_text('\n'.join(LOG) + '\n', encoding='utf-8')
    except OSError as exc:
        say(f'     (A text copy could not be saved in {folder}: {exc.strerror or type(exc).__name__}.)')
        return None
    return target


def main(
    argv: list[str],
    *,
    settings: Settings | None = None,
    make_service: Callable[[Settings], ModelService] = service_from_settings,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description='Checks that Gemini works with Kiro AI.')
    parser.add_argument('--model', help='try this model instead of the one in backend\\.env')
    parser.add_argument('--thinking', help='try this thinking level (MINIMAL, LOW, MEDIUM or HIGH) instead of the one in backend\\.env')
    parser.add_argument('--probe', action='store_true', help='try several models with one tiny request each')
    parser.add_argument('--list-models', action='store_true', help='list the models the key may use, then stop')
    parser.add_argument('--quick', action='store_true', help='only the settings and one tiny request')
    parser.add_argument('--full', action='store_true', help='show every passage Gemini wrote')
    parser.add_argument('--out', type=Path, default=DEBUG, help='where the text copy goes (default: ..\\debug)')
    args = parser.parse_args(argv)

    LOG.clear()
    try:
        code = run(args, settings=settings, make_service=make_service, sleep=sleep)
    finally:
        saved = save_copy(args.out)
    if saved is not None:
        say(f'A text copy of this is saved in {saved}')
        say()
    return code


def run(
    args: argparse.Namespace,
    *,
    settings: Settings | None,
    make_service: Callable[[Settings], ModelService],
    sleep: Callable[[float], None],
) -> int:
    settings = settings or read_settings()
    if args.model:
        settings = settings.with_(gemini_model=args.model.strip())
    if args.thinking is not None:
        settings = settings.with_(gemini_thinking=args.thinking.strip())

    say()
    say('Kiro AI: checking Gemini')
    if not show_settings(settings):
        say()
        say('RESULT: FAIL (no key)')
        return 1
    key = settings.gemini_api_key
    if importlib.util.find_spec('google') is None or importlib.util.find_spec('google.genai') is None:
        say()
        wrapped('The Gemini library (google-genai) is not installed in this Python. Run  run.bat  once: it installs what is missing. Then run this again.', '  ')
        say()
        say('RESULT: FAIL (library missing)')
        return 1

    if args.list_models:
        say()
        return 0 if show_models(key) else 1
    if args.probe:
        return probe(settings, make_service)

    service = make_service(settings)
    heading(2, f'Connection: one tiny request to {settings.gemini_model}')
    try:
        seconds = tiny_request(service)
    except ModelUnavailable as exc:
        show_failure(exc, key)
        if exc.kind == 'bad_model':
            say()
            show_models(key)
        say()
        say('     The report and chat tests need a working connection, so they were not run.')
        say()
        say(f'RESULT: FAIL (connection: {exc.kind})')
        return 1
    say(f'     OK: Google accepted the key and the model, and answered in {seconds:.1f} s.')
    if args.quick:
        say()
        say('RESULT: PASS (quick check)')
        return 0

    hands = made_up_hands()
    outcome, now = report_step(service, hands, args.full, key)
    reading = Reading(
        id='rd_check',
        profileId='prf_check',
        createdAt=now,
        hands=Hands(left=hands['left'], right=hands['right']),
        report=outcome.report,
        meta=meta_for(outcome, service),
    )
    gemini_answers, turned_away, boundary_total = chat_step(service, reading, sleep)

    problems = []
    if not outcome.accepted:
        problems.append('Gemini wrote no report passage that passed the checks')
    if gemini_answers < 3:
        problems.append(f'Gemini wrote only {gemini_answers} of {len(QUESTIONS)} chat answers (at least 3 are expected)')
    if turned_away < boundary_total:
        problems.append(f'only {turned_away} of {boundary_total} off-limits questions were turned away correctly')
    say()
    say('-' * WIDTH)
    repeats = f' ({service.repeats} of them repeated because Google was busy)' if service.repeats else ''
    say(f'Requests made to Gemini: {service.calls}{repeats}. Passages accepted: {len(outcome.accepted)} of {outcome.asked}. Chat answers by Gemini: {gemini_answers} of {len(QUESTIONS)}.')
    say('Now READ the passages and answers above, as an examiner would. Copy to me anything that sounds like a prediction ("you will..."),')
    say('a medical or money claim, advice, or a mark the hands do not show. (A passage the checks refused is not a problem: they are working.)')
    say()
    if problems:
        for problem in problems:
            say(f'  PROBLEM: {problem}')
        say()
    say(f'RESULT: {"FAIL" if problems else "PASS"}')
    return 1 if problems else 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        say()
        say('Stopped.')
        sys.exit(1)
