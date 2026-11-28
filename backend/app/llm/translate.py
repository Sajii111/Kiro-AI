"""READINGS AND CHAT ANSWERS IN SINHALA OR TAMIL: written and checked in English first, then translated by Gemini.

The website can be shown in English, Sinhala or Tamil, and a new reading or chat answer is written in the language the
person chose. Everything that keeps a reading honest works on English text: the guard (llm/guard.py) looks for dates, ages,
health, money, orders, invented marks and contradictions of the findings with English word patterns, and the fixed
wording is English. So the order never changes:

    1. write     the reading (llm/writer.py) or the chat answer (llm/chat_llm.py) is written and checked in English, exactly
                 as before; whatever Gemini wrote has already passed every rule
    2. translate one more request asks Gemini to translate those finished English texts, faithfully and in plain words,
                 into Sinhala or Tamil, as JSON with the same keys (nothing new is written at this step)
    3. check     each translation must be in the right script, add no digit or link that the English did not have, and be
                 of a sensible length; one that fails is asked for once more, then the English is kept for that text

A translation never costs the person their reading: when Gemini is busy, has no key, or keeps failing the checks, the
English text is shown and a note says so. A built-in sample reading is never sent to Gemini, so it stays in English.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from app.llm.gemini import ModelService, ModelUnavailable, unwrap_json
from app.llm.privacy import name_parts
from app.schemas import Reading, Report

log = logging.getLogger('kiro.translate')

TRANSLATE_PROMPT_VERSION = 'translate 1.1'

#: the languages a reading can be written in, besides English (the code the website sends, and the language's name)
LANGUAGES = {'si': 'Sinhala', 'ta': 'Tamil'}
CODES = ('en', *LANGUAGES)

#: the letters of each script (Unicode blocks)
SCRIPT = {'si': re.compile('[඀-෿]'), 'ta': re.compile('[஀-௿]')}
LETTER = re.compile(r'[^\W\d_]')
DIGIT = re.compile(r'\d')
URL = re.compile(r'https?:|www\.|@[\w-]+\.[a-z]{2,}', re.IGNORECASE)

#: how much English one request carries (the translation is about twice as many tokens as the English)
CHUNK_CHARS = 3500
MAX_TOKENS = 8192
#: a reading's translation may wait this long in all (Google's busy spells), a chat answer's much less
READING_WAIT = 120.0
CHAT_WAIT = 30.0

#: the plain names used for the lines and words that matter, so a reading says them the same way as the website does
GLOSSARY = {
    'si': {
        'heart line': 'හෘදය රේඛාව',
        'head line': 'ශීර්ෂ රේඛාව',
        'life line': 'ආයු රේඛාව',
        'fate line': 'භාග්‍ය රේඛාව',
        'sun line': 'රවි රේඛාව',
        'palm': 'අත්ල',
        'palmistry': 'හස්ත ශාස්ත්‍රය',
        'a reading (the result of reading the palms)': 'හස්ත රේඛා කියවීම',
        'fortune teller, reader': 'පේන කියන්නා',
        'profile': 'පැතිකඩ',
        'left hand / right hand': 'වම් අත / දකුණු අත',
        'detected / uncertain / not visible': 'හඳුනාගත් / අවිනිශ්චිත / නොපෙනේ',
    },
    'ta': {
        'heart line': 'இதய ரேகை',
        'head line': 'தலை ரேகை',
        'life line': 'ஆயுள் ரேகை',
        'fate line': 'விதி ரேகை',
        'sun line': 'சூரிய ரேகை',
        'palm': 'உள்ளங்கை',
        'palmistry': 'கைரேகை சாஸ்திரம்',
        'a reading (the result of reading the palms)': 'கைரேகை பலன் (or just பலன்)',
        'fortune teller, reader': 'குறி சொல்பவர்',
        'profile': 'சுயவிவரம்',
        'left hand / right hand': 'இடது கை / வலது கை',
        'detected / uncertain / not visible': 'கண்டறியப்பட்டது / உறுதியில்லை / தெரியவில்லை',
    },
}


def system_for(lang: str) -> str:
    name = LANGUAGES[lang]
    words = '\n'.join(f'- {en}: {local}' for en, local in GLOSSARY[lang].items())
    return f"""You translate the text of Kiro AI, a palm-reading app, from English into {name} for people in Sri Lanka.

Rules:
- Translate faithfully and completely. Keep the exact meaning of every sentence. Add nothing, leave nothing out, and do not explain.
- Use plain, everyday {name}, the way a friendly fortune teller in Sri Lanka would talk to a visitor: short sentences, common words, polite but warm. Avoid old-fashioned literary words.
- Speak to the person directly, as the English does ("you", "your").
- Write natural {name}, not word for word. When an English phrase would sound odd translated literally, say the same thing the way a {name} speaker would.
- Keep these names as they are, in Latin letters: Kiro, Kiro AI, Gemini, Google. Keep placeholders such as NAME1 exactly as they are.
- Write numbers only where the English has them. Never add a date, an age, an amount or a link.
- Keep line breaks where the English has them.
- Use these words for these terms:
{words}

You receive a JSON object of texts. Answer with a JSON object that has exactly the same keys, each holding the {name} translation of its text."""


def prompt_for(texts: dict[str, str]) -> str:
    return 'TRANSLATE these texts. Answer with the same keys.\n' + json.dumps(texts, ensure_ascii=False, indent=1)


def schema_for(keys: list[str]) -> dict:
    return {'type': 'object', 'properties': {k: {'type': 'string'} for k in keys}, 'required': keys}


def problems(source: str, text: str, lang: str) -> list[str]:
    """What is wrong with one translation (empty when it can be used)."""
    found = []
    if not text.strip():
        return ['is empty']
    letters = LETTER.findall(text)
    script = SCRIPT[lang].findall(text)
    if not script or len(script) < 0.5 * len(letters):
        found.append(f'is not written in {LANGUAGES[lang]}')
    if DIGIT.search(text) and not DIGIT.search(source):
        found.append('adds a number the English does not have')
    if URL.search(text) and not URL.search(source):
        found.append('adds a link')
    if len(text) > max(80, 4 * len(source)):
        found.append('is far longer than the English')
    if len(text) < 0.25 * len(source):
        found.append('is far shorter than the English')
    return found


def chunks(texts: dict[str, str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = [{}]
    size = 0
    for key, text in texts.items():
        if out[-1] and size + len(text) > CHUNK_CHARS:
            out.append({})
            size = 0
        out[-1][key] = text
        size += len(text)
    return [c for c in out if c]


def parse(text: str, keys: list[str]) -> dict[str, str]:
    try:
        data = json.loads(unwrap_json(text))
    except ValueError:
        raise ModelUnavailable('bad_output', 'the translation is not JSON') from None
    if not isinstance(data, dict):
        raise ModelUnavailable('bad_output', 'the translation is not a JSON object')
    return {k: data[k] for k in keys if isinstance(data.get(k), str)}


class Result:
    """The translations that passed, by key, and why the others did not."""

    def __init__(self) -> None:
        self.done: dict[str, str] = {}
        self.failed: dict[str, list[str]] = {}
        self.error: ModelUnavailable | None = None
        self.model = ''


def translate_texts(
    texts: dict[str, str],
    lang: str,
    service: ModelService,
    *,
    wait: float,
    cancelled: Callable[[], bool] | None = None,
) -> Result:
    """`texts` (key -> English) translated into `lang`. Identical texts are asked for once. Never raises for anything Gemini does."""
    result = Result()
    if lang not in LANGUAGES or not texts:
        return result
    unique: dict[str, str] = {}
    keys_of: dict[str, list[str]] = {}
    for key, text in texts.items():
        if not text.strip():
            result.done[key] = text
            continue
        if text not in keys_of:
            short = f't{len(unique)}'
            unique[short] = text
            keys_of[text] = []
        keys_of[text].append(key)
    done: dict[str, str] = {}
    reasons: dict[str, list[str]] = {}
    pending = dict(unique)
    for _attempt in range(2):  # the texts that failed a check are asked for once more
        if not pending:
            break
        failed_now: dict[str, str] = {}
        stop = False
        for part in chunks(pending):
            if cancelled is not None and cancelled():
                stop = True
                break
            keys = list(part)
            try:
                raw = service.call(
                    system=system_for(lang),
                    prompt=prompt_for(part),
                    schema=schema_for(keys),
                    temperature=0.1,
                    max_tokens=MAX_TOKENS,
                    timeout_s=wait,
                    cache=True,
                    validate=lambda text, keys=keys: parse(text, keys),  # an answer that is not JSON is never remembered
                    retries=4 if wait >= 60 else 1,
                )
            except ModelUnavailable as exc:
                result.error = exc
                for k in part:
                    reasons[k] = [f'was not translated: {exc.reason}']
                if exc.kind in ('bad_output', 'empty'):
                    failed_now.update(part)  # an unusable answer: worth one more try
                    continue
                stop = True  # Google is busy, the allowance is used up, ...: the English stays
                break
            result.model = result.model or getattr(raw, 'model', '') or ''
            got = parse(raw, keys)
            for k, source in part.items():
                text = got.get(k, '').strip()
                found = problems(source, text, lang) if k in got else ['was missing from the answer']
                if found:
                    reasons[k] = found
                    failed_now[k] = source
                else:
                    done[k] = text
                    reasons.pop(k, None)
        if stop:
            break
        pending = failed_now
    for short, source in unique.items():
        for key in keys_of[source]:
            if short in done:
                result.done[key] = done[short]
            else:
                result.failed[key] = reasons.get(short, ['was not translated'])
    if result.failed:
        log.info('translation into %s: %d of %d texts kept in English: %s', lang, len(result.failed), len(texts), '; '.join(f'{k} {", ".join(v)}' for k, v in list(result.failed.items())[:5]))
    return result


# ------------------------------------------------------------------ a reading


def report_texts(report: Report) -> dict[str, str]:
    """Every text of a report that a person reads, by a key that says where it sits."""
    out: dict[str, str] = {'summary': report.summary, 'disclaimer': report.disclaimer}
    for i, s in enumerate(report.sections):
        out[f's{i}.title'] = s.title
        for side in ('left', 'right'):
            out[f's{i}.observed.{side}'] = getattr(s.observed, side).text
            value = getattr(s.traditional, side)
            if value:
                out[f's{i}.traditional.{side}'] = value
        if s.comparison:
            out[f's{i}.comparison'] = s.comparison
    for side in ('left', 'right'):
        out[f'shape.observed.{side}'] = getattr(report.shape.observed, side).text
        value = getattr(report.shape.traditional, side)
        if value:
            out[f'shape.traditional.{side}'] = value
    if report.shape.comparison:
        out['shape.comparison'] = report.shape.comparison
    for i, th in enumerate(report.themes):
        out[f't{i}.title'] = th.title
        if th.traditional:
            out[f't{i}.traditional'] = th.traditional
    for i, u in enumerate(report.uncertainty):
        out[f'u{i}'] = u
    return out


def apply_texts(report: Report, texts: dict[str, str]) -> Report:
    """A copy of `report` with the translated texts in their places (a text that is not in `texts` stays as it was)."""
    out = report.model_copy(deep=True)
    get = texts.get
    out.summary = get('summary', out.summary)
    out.disclaimer = get('disclaimer', out.disclaimer)
    for i, s in enumerate(out.sections):
        s.title = get(f's{i}.title', s.title)
        for side in ('left', 'right'):
            obs = getattr(s.observed, side)
            obs.text = get(f's{i}.observed.{side}', obs.text)
            value = getattr(s.traditional, side)
            if value:
                setattr(s.traditional, side, get(f's{i}.traditional.{side}', value))
        if s.comparison:
            s.comparison = get(f's{i}.comparison', s.comparison)
    for side in ('left', 'right'):
        obs = getattr(out.shape.observed, side)
        obs.text = get(f'shape.observed.{side}', obs.text)
        value = getattr(out.shape.traditional, side)
        if value:
            setattr(out.shape.traditional, side, get(f'shape.traditional.{side}', value))
    if out.shape.comparison:
        out.shape.comparison = get('shape.comparison', out.shape.comparison)
    for i, th in enumerate(out.themes):
        th.title = get(f't{i}.title', th.title)
        if th.traditional:
            th.traditional = get(f't{i}.traditional', th.traditional)
    out.uncertainty = [get(f'u{i}', u) for i, u in enumerate(out.uncertainty)]
    return out


def reading_note(lang: str, result: Result, total: int) -> str | None:
    name = LANGUAGES[lang]
    if not result.failed:
        return None
    if not result.done:
        why = f' because {result.error.clause}' if result.error is not None and result.error.kind != 'no_key' else ''
        return f'This reading could not be translated into {name}{why}, so it is shown in English.'
    return f'{len(result.failed)} of {total} parts could not be translated into {name}, so they are shown in English.'


def translate_reading(reading: Reading, lang: str, service: ModelService | None, *, cancelled: Callable[[], bool] | None = None) -> Reading:
    """The reading with its report in `lang`. English, a sample reading or no Gemini key: the reading as it is. Never raises."""
    if lang not in LANGUAGES or reading.meta.mock:
        return reading
    if service is None or not service.available:
        note = f'Gemini is not set up on this server, so this reading is shown in English instead of {LANGUAGES[lang]}.'
        return reading.model_copy(update={'meta': reading.meta.model_copy(update={'note': join(reading.meta.note, note)})})
    try:
        texts = report_texts(reading.report)
        result = translate_texts(texts, lang, service, wait=min(READING_WAIT, service.timeout_s), cancelled=cancelled)
    except Exception:  # a bug here must never cost a person their reading
        log.exception('the translation failed; the reading stays in English')
        note = f'This reading could not be translated into {LANGUAGES[lang]} because of an unexpected problem, so it is shown in English.'
        return reading.model_copy(update={'meta': reading.meta.model_copy(update={'note': join(reading.meta.note, note)})})
    meta = reading.meta.model_copy(
        update={
            'language': lang if result.done else None,
            'note': join(reading.meta.note, reading_note(lang, result, len(texts))),
        }
    )
    return reading.model_copy(update={'report': apply_texts(reading.report, result.done), 'meta': meta})


def join(*notes: str | None) -> str | None:
    text = ' '.join(n for n in notes if n)
    return text or None


# ------------------------------------------------------------------ a chat answer


def hide_names(text: str, names: list[str]) -> tuple[str, dict[str, str]]:
    """The text with each name (a profile's name can be in a fixed answer) replaced by a placeholder, so no name goes to Gemini."""
    hidden: dict[str, str] = {}
    for part in name_parts(names):
        def swap(m: re.Match[str]) -> str:
            token = f'NAME{len(hidden) + 1}'
            hidden[token] = m.group(0)
            return token

        text = re.sub(rf'(?<!\w){re.escape(part)}(?!\w)', swap, text, flags=re.IGNORECASE)
    return text, hidden


def show_names(text: str, hidden: dict[str, str]) -> str:
    for token in sorted(hidden, key=len, reverse=True):
        text = text.replace(token, hidden[token])
    return text


def translate_answer(text: str, lang: str, service: ModelService | None, names: list[str] | None = None) -> tuple[str, str | None]:
    """A chat answer in `lang`, and a note when it had to stay in English. `names` (the profiles' names) never leave the server:
    they are swapped for placeholders before the request and put back after. Never raises."""
    if lang not in LANGUAGES or not text.strip():
        return text, None
    if service is None or not service.available:
        return text, None  # no Gemini at all: the fixed wording answers in English, as the Settings page says
    masked, hidden = hide_names(text, names or [])
    try:
        result = translate_texts({'answer': masked}, lang, service, wait=CHAT_WAIT)
    except Exception:
        log.exception('the chat translation failed; the answer stays in English')
        result = Result()
    if 'answer' in result.done:
        return show_names(result.done['answer'], hidden), None
    return text, f'This answer could not be translated into {LANGUAGES[lang]}, so it is shown in English.'
