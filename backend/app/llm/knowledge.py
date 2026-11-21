"""The fixed-rule wording: what the tradition says about a line, a hand shape or a theme, built from the entries of the
palmistry knowledge base (llm/kb/).

The entries live in JSON files, so there is one place to check them. This module only reads them and puts a few of them
together: the `short` clause of each entry that matches a finding, joined into sentences. It is what writes the report
when the language model is not available (no key, no internet, a used-up allowance, or a passage that failed the safety
checks), and it is the standard the model is held to: every claim is phrased as "in traditional palmistry ...", is about
general temperament, and never gives medical, financial, employment or relationship advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.llm import kb as base
from app.schemas import (
    FeatureStatus,
    FeatureTraits,
    PalmShapeTraits,
    ThemeId,
    ThemeSource,
)

KB_VERSION = base.KB_VERSION

FEATURE_ORDER: list[str] = ['heart', 'head', 'life', 'fate', 'sun']

FEATURE_NAMES: dict[str, str] = {
    'heart': 'Heart line',
    'head': 'Head line',
    'life': 'Life line',
    'fate': 'Fate line',
    'sun': 'Sun line',
}



def build_kb() -> dict[str, dict]:
    """For each line: the theme it is linked with, then a clause for each length, curve and clarity. Read from the
    entries of llm/kb/lines.json."""
    out: dict[str, dict] = {}
    for fid in FEATURE_ORDER:
        general = base.line_entry(fid)
        assert general is not None, f'the knowledge base has no entry for the {fid} line'
        out[fid] = {'theme': general.get('short'), 'length': {}, 'curve': {}, 'clarity': {}}
    for entry in base.of_kind('line'):
        if entry.get('trait'):
            out[entry.get('line')][entry.get('trait')][entry.get('value')] = entry.get('short')
    return out


KB: dict[str, dict] = build_kb()


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def traditional_text(feature_id: str, status: FeatureStatus, traits: FeatureTraits) -> str | None:
    """What the tradition says, for one line on one hand. None when the line was not seen, so nothing is claimed.
    For an uncertain line only the general theme is offered, with no detail about its shape."""
    if status == 'not_visible':
        return None
    name = FEATURE_NAMES[feature_id].lower()
    entry = KB[feature_id]
    if status == 'uncertain':
        return (
            f'Only as a loose idea: in traditional palmistry the {name} is linked with {entry["theme"]}. '
            'Because the line was not clearly seen, nothing is said about its length or shape.'
        )
    parts: list[str] = []
    if traits.length:
        parts.append(cap(entry['length'][traits.length]))
    if traits.curve:
        parts.append(cap(entry['curve'][traits.curve]))
    if traits.clarity and traits.clarity != 'faint':
        parts.append(cap(entry['clarity'][traits.clarity]))
    return f'In traditional palmistry the {name} is linked with {entry["theme"]}. {". ".join(parts)}.'


# ------------------------------------------------------------------ the shape of the hand

Element = Literal['earth', 'air', 'water', 'fire']


def element_of(traits: PalmShapeTraits) -> Element | None:
    """The traditional element of a hand, from how broad the palm is and how long the fingers are.
    None when either was not judged."""
    if not traits.palm or not traits.fingers:
        return None
    if traits.palm == 'square':
        return 'earth' if traits.fingers == 'short' else 'air'
    return 'water' if traits.fingers == 'long' else 'fire'


ELEMENT_KB: dict[str, dict[str, str]] = {
    e.get('element'): {'named': e.get('named'), 'shape': e.get('shape'), 'theme': e.get('temperament')} for e in base.of_kind('shape') if e.get('element')
}


def shape_traditional_text(status: FeatureStatus, traits: PalmShapeTraits) -> str | None:
    """What the tradition says about the shape of one hand. None when the shape was not seen."""
    if status == 'not_visible':
        return None
    element = element_of(traits)
    if status == 'uncertain' or not element:
        return (
            'Only as a loose idea: traditional palmistry sorts hands into four shapes called earth, air, water and fire. '
            'Because the hand was not clearly in view, nothing is said about which one this is.'
        )
    e = ELEMENT_KB[element]
    return f'In traditional palmistry {e["shape"]} is called {e["named"]}, which is linked with {e["theme"]}.'


# ------------------------------------------------------------------ the themes


@dataclass(frozen=True)
class ThemeDef:
    id: ThemeId
    title: str
    #: what the tradition reads this theme from: one sentence
    intro: str
    #: the sources, in the order the tradition lists them
    sources: tuple[ThemeSource, ...]
    #: the reminder that closes every theme
    outro: str


THEMES: list[ThemeDef] = [
    ThemeDef(id=e.get('theme'), title=e.get('title'), intro=e.get('intro'), sources=tuple(e.get('reads')), outro=e.get('outro')) for e in base.of_kind('theme')
]

THEME_ORDER: list[str] = [t.id for t in THEMES]


def source_name(src: str) -> str:
    return 'Hand shape' if src == 'shape' else FEATURE_NAMES[src]


def list_words(names: list[str]) -> str:
    """'a, b and c'"""
    if len(names) <= 1:
        return ''.join(names)
    return f'{", ".join(names[:-1])} and {names[-1]}'


def line_clause(feature_id: str, traits: FeatureTraits) -> str:
    """One clause about a detected line, from its length and curve."""
    entry = KB[feature_id]
    parts: list[str] = []
    if traits.length:
        parts.append(cap(entry['length'][traits.length]))
    if traits.curve:
        parts.append(cap(entry['curve'][traits.curve]))
    return f'{". ".join(parts)}.'


def shape_clause(traits: PalmShapeTraits) -> str:
    """One clause about a detected hand shape."""
    element = element_of(traits)
    if not element:
        return ''
    e = ELEMENT_KB[element]
    return f'{cap(e["shape"])} is called {e["named"]}, linked with {e["theme"]}.'
