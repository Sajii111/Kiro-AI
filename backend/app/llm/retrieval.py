"""Choosing which knowledge-base entries the language model is shown. This is the "retrieval" in retrieval-augmented
generation (RAG): the model never answers from memory alone, it is handed the curated entries that fit.

Two strategies, one for each job:

  report  A LOOKUP. The findings say exactly which entries apply (the heart line, long, gently curved, clear...), so
          they are picked by key: no guessing, and the same findings always give the same entries.
  chat    A KEYWORD SEARCH (BM25) over the entries, because a question is free text. The search is then FILTERED by the
          reading: an entry about a line that was not clearly seen, or about a length or curve this person's hands do
          not show, is never offered, so the model cannot be handed something that is not in the findings.

BM25 is written out here (about thirty lines) instead of imported, so the project needs no extra package for it and it
can be explained line by line.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from app.llm import kb
from app.llm.kb import Entry
from app.llm.knowledge import FEATURE_ORDER, element_of
from app.schemas import FeatureResult, FeatureTraits, HandAnalysis, PalmShapeTraits

# ------------------------------------------------------------------ lookup (the report)


def line_entries(line_id: str, traits: FeatureTraits) -> list[Entry]:
    """The entries for one detected line: what it is linked with, then one for each trait that was judged. A line that
    is only faintly marked has no entry for how clear it is: nothing is claimed about that."""
    found = [kb.line_entry(line_id)]
    for trait in ('length', 'curve'):
        value = getattr(traits, trait)
        if value:
            found.append(kb.line_entry(line_id, trait, value))
    if traits.clarity and traits.clarity != 'faint':
        found.append(kb.line_entry(line_id, 'clarity', traits.clarity))
    return [e for e in found if e is not None]


def shape_entries(traits: PalmShapeTraits) -> list[Entry]:
    """The entry for a detected hand shape (and the general note about the four shapes)."""
    element = element_of(traits)
    found = [kb.shape_entry(None), kb.shape_entry(element) if element else None]
    return [e for e in found if e is not None]


def entries_for_findings(hands: dict[str, HandAnalysis]) -> list[Entry]:
    """Every line and shape entry that matches something DETECTED on either hand, once each, in knowledge-base order."""
    wanted: dict[str, Entry] = {}
    for hand in hands.values():
        for feature in hand.features:
            if feature.status == 'detected':
                for entry in line_entries(feature.id, feature.traits):
                    wanted[entry.id] = entry
        if hand.palmShape.status == 'detected':
            for entry in shape_entries(hand.palmShape.traits):
                wanted[entry.id] = entry
    order = {e.id: i for i, e in enumerate(kb.entries())}
    return sorted(wanted.values(), key=lambda e: order[e.id])


# ------------------------------------------------------------------ BM25 (the chat)

#: words that carry no topic: the usual small words, and the words every question or every entry of this knowledge base uses
#: ("what does palmistry traditionally say ...", "in traditional palmistry ..."), which would otherwise make a short entry that
#: happens to contain a rare one of them (say, "traditionally") outrank the entry about the line that was asked about
STOPWORDS = frozenset(
    ['a', 'an', 'and', 'are', 'as', 'at', 'be', 'but', 'by', 'can', 'could', 'do', 'does', 'for', 'from', 'has', 'have', 'how', 'i', 'if', 'in', 'is', 'it', 'its', 'me', 'my', 'of', 'on', 'or', 'so', 'that', 'the', 'their', 'them', 'then', 'there', 'these', 'this', 'to', 'was', 'we', 'what', 'when', 'which', 'who', 'why', 'will', 'with', 'would', 'you', 'your', 'please', 'about', 'also', 'any', 'some', 'more', 'most', 'much', 'many', 'very', 'tell', 'show', 'say', 'says', 'said', 'explain', 'detail', 'details', 'mean', 'means', 'meaning', 'represent', 'represents', 'interpretation', 'interpretations', 'interpret', 'tradition', 'traditional', 'traditionally', 'palmistry', 'reading', 'read', 'reads', 'often', 'linked', 'associated']
)


def stem(word: str) -> str:
    """The lightest possible stemming, so "lines" finds "line" and "feelings" finds "feeling"."""
    if len(word) > 4 and word.endswith('ies'):
        return word[:-3] + 'y'
    if len(word) > 3 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS and len(w) > 1]


@dataclass(frozen=True)
class Hit:
    entry: Entry
    score: float


class Bm25:
    """Okapi BM25: a word scores higher when it is rare across the entries (idf) and frequent in this one, with the
    effect of repetition flattened (k1) and long entries mildly penalised (b)."""

    def __init__(self, items: Iterable[Entry], k1: float = 1.5, b: float = 0.75):
        self.items = list(items)
        self.k1, self.b = k1, b
        self.counts = [Counter(tokens(e.search_text())) for e in self.items]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        document_frequency: Counter[str] = Counter()
        for c in self.counts:
            document_frequency.update(c.keys())
        n = len(self.items)
        self.idf = {w: math.log((n - df + 0.5) / (df + 0.5) + 1.0) for w, df in document_frequency.items()}

    def score(self, query: list[str], index: int) -> float:
        counts, length = self.counts[index], self.lengths[index]
        total = 0.0
        for word in set(query):
            tf = counts.get(word, 0)
            if not tf:
                continue
            norm = tf + self.k1 * (1 - self.b + self.b * length / (self.average or 1.0))
            total += self.idf[word] * tf * (self.k1 + 1) / norm
        return total

    def search(self, query_text: str, k: int = 5, allow=None) -> list[Hit]:
        query = tokens(query_text)
        hits = [Hit(e, self.score(query, i)) for i, e in enumerate(self.items) if allow is None or allow(e)]
        hits = [h for h in hits if h.score > 0]
        hits.sort(key=lambda h: (-h.score, h.entry.id))
        return hits[:k]


_index: Bm25 | None = None


def index() -> Bm25:
    global _index
    if _index is None:
        _index = Bm25(kb.entries())
    return _index


# ------------------------------------------------------------------ what this reading allows


def feature(hand: HandAnalysis, line_id: str) -> FeatureResult:
    return next(f for f in hand.features if f.id == line_id)


def seen_lines(hands: dict[str, HandAnalysis]) -> set[str]:
    """The lines that were clearly seen (detected) on at least one hand."""
    return {fid for fid in FEATURE_ORDER if any(feature(h, fid).status == 'detected' for h in hands.values())}


def allowed(entry: Entry, hands: dict[str, HandAnalysis]) -> bool:
    """May the model be shown this entry for this reading? Entries about a line, a length, a curve or a hand shape are
    only allowed when a detected hand actually shows it. General entries (themes, comparing the hands, what palmistry
    does not claim) are always allowed."""
    if entry.kind == 'line':
        line = entry.get('line')
        detected = [feature(h, line) for h in hands.values() if feature(h, line).status == 'detected']
        if not detected:
            return False
        trait = entry.get('trait')
        if trait is None:
            return True
        return any(getattr(f.traits, trait) == entry.get('value') for f in detected)
    if entry.kind == 'shape':
        element = entry.get('element')
        if element is None:
            return any(h.palmShape.status == 'detected' for h in hands.values())
        return any(h.palmShape.status == 'detected' and element_of(h.palmShape.traits) == element for h in hands.values())
    return True


LINE_WORDS = {
    'heart': re.compile(r'\bheart\b', re.IGNORECASE),
    'head': re.compile(r'\bhead\b|\bintellect\b', re.IGNORECASE),
    'life': re.compile(r'\blife\b|\bvitality\b', re.IGNORECASE),
    'fate': re.compile(r'\bfate\b|\bdestiny\b', re.IGNORECASE),
    'sun': re.compile(r'\bsun\b|\bapollo\b', re.IGNORECASE),
}


def retrieve(question: str, hands: dict[str, HandAnalysis], earlier: str = '', k: int = 6) -> list[Entry]:
    """The entries to show the model for a question, and only ones this reading allows:

      1. the general entry of every line the question names (when that line was detected), so "my heart line" always brings
         what the tradition links the heart line with;
      2. the best matches of a keyword search (BM25) over the whole knowledge base;
      3. when nothing at all matched (a follow-up such as "and the left hand?" or "why?"), the best matches for the question
         before it, so the follow-up still has a subject.
    """

    def ok(entry: Entry) -> bool:
        return allowed(entry, hands)

    found: dict[str, Entry] = {}
    for fid, pattern in LINE_WORDS.items():
        entry = kb.line_entry(fid)
        if entry is not None and pattern.search(question) and ok(entry):
            found[entry.id] = entry
    for hit in index().search(question, k=k, allow=ok):
        found.setdefault(hit.entry.id, hit.entry)
    if earlier and not found:
        for hit in index().search(earlier, k=k, allow=ok):
            found.setdefault(hit.entry.id, hit.entry)
    return list(found.values())[:k]
