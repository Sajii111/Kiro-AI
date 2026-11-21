"""The palmistry knowledge base: short, curated entries kept as JSON files next to this one.

    lines.json     the five principal lines: what each is linked with, then one entry for each length, curve and clarity
    shape.json     the four hand shapes (earth, air, water, fire)
    themes.json    the five themes of the report: personality, career, financial, relationships, future
    compare.json   how the tradition reads the two hands together
    limits.json    what palmistry does not claim, and what this reading never does
    sources.json   the books and pages the entries were written from (entries name them in `basis`)

Every entry is written in cautious wording ("In traditional palmistry ... is often read as ..."). Both writers use the
same entries, so the wording is checked once:

  * the fixed-rule writer (llm/knowledge.py) picks the entries that match the findings and joins their `short` clauses;
  * the language model is given the matching entries (llm/retrieval.py) and writes the report from them, and every
    sentence it writes is checked by the same safety rules the entries themselves must pass (tests/test_kb.py).

The entries are written in the project's own words from the sources in sources.json, and they leave out on purpose
whatever older books say about health, length of life, fortune or events. They are a draft for the author to check
against the named sources: see README.md in this folder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

DIR = Path(__file__).resolve().parent

#: written into every reading's `meta.knowledgeBase`; change it whenever an entry changes
KB_VERSION = 'palm-kb 1.0'

FILES = ('lines.json', 'shape.json', 'themes.json', 'compare.json', 'limits.json')
KINDS = ('line', 'shape', 'theme', 'compare', 'limits')

#: the extra fields each kind of entry must carry (besides id, kind, text, keywords and basis)
REQUIRED: dict[str, tuple[str, ...]] = {
    'line': ('line', 'trait', 'value', 'short'),
    'shape': ('element', 'named', 'shape', 'temperament'),
    'theme': ('theme', 'title', 'intro', 'outro', 'reads', 'roles'),
    'compare': ('case',),
    'limits': ('topic',),
}


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    #: the full cautious statement the language model is given
    text: str
    #: words a search can match besides the text itself
    keywords: tuple[str, ...]
    #: ids of the sources (sources.json) the entry was written from
    basis: tuple[str, ...]
    #: the fields that belong to one kind of entry only (a line entry's `line`, `trait`, `value` and `short`, and so on)
    fields: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        return self.fields.get(name, default)

    def search_text(self) -> str:
        """What a keyword search reads: the statement, the keywords, and the names of the line, theme or shape."""
        names = [str(self.fields.get(k) or '') for k in ('line', 'theme', 'element', 'topic', 'case', 'trait', 'value')]
        return ' '.join([self.text, *self.keywords, *names])


class KnowledgeBaseError(ValueError):
    """An entry file is not in the shape this module expects."""


def read_json(name: str):
    return json.loads((DIR / name).read_text(encoding='utf-8'))


def make_entry(raw: dict, file: str) -> Entry:
    for key in ('id', 'kind', 'text', 'keywords', 'basis'):
        if key not in raw:
            raise KnowledgeBaseError(f'{file}: an entry has no "{key}": {str(raw)[:80]}')
    kind = raw['kind']
    if kind not in KINDS:
        raise KnowledgeBaseError(f'{file}: {raw["id"]} has an unknown kind "{kind}"')
    missing = [k for k in REQUIRED[kind] if k not in raw]
    if missing:
        raise KnowledgeBaseError(f'{file}: {raw["id"]} is missing {", ".join(missing)}')
    extra = {k: (tuple(v) if isinstance(v, list) else v) for k, v in raw.items() if k not in ('id', 'kind', 'text', 'keywords', 'basis')}
    return Entry(id=raw['id'], kind=kind, text=raw['text'], keywords=tuple(raw['keywords']), basis=tuple(raw['basis']), fields=extra)


@lru_cache(maxsize=1)
def sources() -> dict[str, dict]:
    return {s['id']: s for s in read_json('sources.json')}


@lru_cache(maxsize=1)
def entries() -> tuple[Entry, ...]:
    """Every entry, in file order. Read once."""
    out: list[Entry] = []
    seen: set[str] = set()
    for file in FILES:
        for raw in read_json(file):
            entry = make_entry(raw, file)
            if entry.id in seen:
                raise KnowledgeBaseError(f'{file}: the id {entry.id} is used twice')
            seen.add(entry.id)
            out.append(entry)
    return tuple(out)


@lru_cache(maxsize=1)
def by_id() -> dict[str, Entry]:
    return {e.id: e for e in entries()}


def get(entry_id: str) -> Entry:
    return by_id()[entry_id]


def of_kind(kind: str) -> list[Entry]:
    return [e for e in entries() if e.kind == kind]


def line_entry(line: str, trait: str | None = None, value: str | None = None) -> Entry | None:
    """The entry for a line (`trait` and `value` left out: its general entry) or for one length, curve or clarity of it."""
    return by_id().get(f'{line}.general' if trait is None else f'{line}.{trait}.{value}')


def shape_entry(element: str | None) -> Entry | None:
    return by_id().get('shape.general' if element is None else f'shape.{element}')


def theme_entry(theme: str) -> Entry:
    return by_id()[f'theme.{theme}']


def limit_entry(topic: str) -> Entry | None:
    return next((e for e in of_kind('limits') if e.get('topic') == topic), None)
