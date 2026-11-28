"""A stand-in for Gemini, so no test ever touches the network.

`FakeModel` is a TextModel (llm/gemini.py). It reads the passages a report prompt asks for (the lines
"- key: what to write  [draw on: entry, entry]") and answers the way a well-behaved model would: it writes each passage from the
knowledge-base entries named for it. A test makes it misbehave by giving it a `respond` function of its own: one that predicts the
future, returns nonsense, raises ModelUnavailable, and so on.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.llm import kb
from app.llm.gemini import ModelService, ModelUnavailable

ASKED = re.compile(r'^- (\w+): (.*?)  \[draw on: (.*)\]$', re.MULTILINE)
DOMINANT = ' This reading does not know which of your hands is dominant, so it cannot say which hand shows which.'


def asked(prompt: str) -> list[tuple[str, str, list[str]]]:
    """The passages a report prompt asks for: (key, what to write, the knowledge-base entry ids to draw on)."""
    return [(m.group(1), m.group(2), [i.strip() for i in m.group(3).split(',') if i.strip() in kb.by_id()]) for m in ASKED.finditer(prompt)]


def passage(key: str, ids: list[str]) -> str:
    """A passage for `key` written from its entries, as a model that follows the rules would."""
    entries = [kb.get(i) for i in ids]
    if key == 'summary':
        body = [e.text for e in entries if e.kind in ('line', 'shape')][:2] + [kb.get('limits.not_science').text]
    elif key.startswith('compare_'):
        body = [e.text for e in entries if e.id in ('compare.same', 'compare.differ')][:1] + [DOMINANT.strip()]
    elif key.startswith('theme_'):
        body = [e.text for e in entries if e.kind == 'line'][:3]
        body.insert(0, 'Your palm reads this theme from the lines that were found.')
    else:
        body = [e.text for e in entries][:3]
    return ' '.join(body)


def good_answer(prompt: str) -> dict[str, str]:
    """A report: one passage for every key the prompt asks for."""
    return {key: passage(key, ids) for key, _ask, ids in asked(prompt)}


KNOWLEDGE = re.compile(r'^\[([\w.]+)\] (.*)$', re.MULTILINE)


def good_chat(prompt: str) -> dict:
    """A chat answer written from the first two knowledge entries the prompt carries."""
    block = prompt.split('KNOWLEDGE', 1)[1].split('CONVERSATION', 1)[0]
    entries = KNOWLEDGE.findall(block)
    lines = [i.split('.')[0] for i, _text in entries if i.split('.')[0] in ('heart', 'head', 'life', 'fate', 'sun')]
    return {
        'intent': 'answer',
        'answer': ' '.join(text for _i, text in entries[:2]) or 'Your lines found in this reading can be read one by one.',
        'lines': list(dict.fromkeys(lines))[:2],
        'side': 'none',
        'section': 'none',
    }


#: a stand-in "translation": every Latin letter becomes a Sinhala or Tamil letter, so the result is in the right script and
#: keeps the length, and the test can still tell which English text it came from (`untranslate`)
SCRIPT_BASE = {'Sinhala': 0x0D9A, 'Tamil': 0x0B95}


KEEP = re.compile(r'(NAME\d+|Gemini|Kiro)')


def fake_translate(text: str, language: str) -> str:
    """Placeholders for names, and the names Gemini and Kiro, stay as they are, as the instructions ask."""
    base = SCRIPT_BASE[language]
    return ''.join(
        part if KEEP.fullmatch(part) else ''.join(chr(base + (ord(c.lower()) - 97) % 20) if c.isascii() and c.isalpha() else c for c in part)
        for part in KEEP.split(text)
    )


def good_translation(system: str, prompt: str) -> dict:
    """A translation: the same keys, each text in the stand-in script of the language the system prompt names."""
    language = 'Tamil' if 'into Tamil' in system else 'Sinhala'
    texts = json.loads(prompt.split('\n', 1)[1])
    return {key: fake_translate(text, language) for key, text in texts.items()}


def good(prompt: str) -> dict:
    """What a well-behaved model answers: a chat answer for a chat prompt (they start with READING), a report otherwise.
    (A translation request is answered by FakeModel itself: it needs the system prompt too.)"""
    return good_chat(prompt) if prompt.startswith('READING') else good_answer(prompt)


@dataclass
class Request:
    system: str
    prompt: str
    schema: dict
    temperature: float
    max_tokens: int
    timeout_s: float


class FakeModel:
    """`respond(prompt)` returns a dict (sent back as JSON), a string (sent back as it is) or an exception to raise."""

    name = 'fake-gemini'

    def __init__(self, respond: Callable[[str], object] | None = None, translate: Callable[[str, str], object] | None = None):
        self.respond = respond or good
        #: how a translation request (its prompt starts with TRANSLATE) is answered: `translate(system, prompt)`
        self.translate = translate or good_translation
        self.requests: list[Request] = []

    def generate(self, system: str, prompt: str, schema: dict, *, temperature: float, max_tokens: int, timeout_s: float) -> str:
        self.requests.append(Request(system, prompt, schema, temperature, max_tokens, timeout_s))
        out = self.translate(system, prompt) if prompt.startswith('TRANSLATE') else self.respond(prompt)
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, str) else json.dumps(out)

    @property
    def calls(self) -> int:
        return len(self.requests)


def service_for(model: FakeModel | None = None, **options) -> ModelService:
    """A ModelService around a fake model (or around none: `service_for(None)` is a server with no key)."""
    return ModelService(model, **options)


def unavailable(kind: str, detail: str = '', retry_after: float | None = None) -> ModelUnavailable:
    return ModelUnavailable(kind, detail, retry_after)
