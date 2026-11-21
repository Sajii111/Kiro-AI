"""The palmistry knowledge base (app/llm/kb/): every entry is well formed, cites a source, and obeys the same safety rules the
language model's passages are held to. These tests are what makes "the entries are cautious" a checked fact instead of a hope."""

from __future__ import annotations

import pytest

from app.llm import guard, kb
from app.llm.knowledge import (
    FEATURE_ORDER,
    KB,
    THEMES,
    element_of,
    line_clause,
    shape_clause,
    traditional_text,
)
from app.schemas import FeatureTraits, PalmShapeTraits

LENGTHS = ('short', 'medium', 'long')
CURVES = ('straight', 'gentle', 'pronounced')
CLARITIES = ('clear', 'deep')  # a faintly marked line has no entry: nothing is claimed about faintness


def subject_for_entry(entry: kb.Entry) -> guard.Subject:
    if entry.kind == 'line':
        trait, value = entry.get('trait'), entry.get('value')
        return guard.Subject('line', side='left', traits=FeatureTraits(**({trait: value} if trait else {})))
    if entry.kind == 'shape':
        element = entry.get('element')
        palm = {'earth': 'square', 'air': 'square', 'water': 'long', 'fire': 'long'}.get(element)
        fingers = {'earth': 'short', 'air': 'long', 'water': 'long', 'fire': 'short'}.get(element)
        return guard.Subject('shape', side='left', shape=PalmShapeTraits(palm=palm, fingers=fingers) if element else None)
    return guard.Subject(entry.kind)


def test_the_files_load_and_ids_are_unique():
    entries = kb.entries()
    assert len(entries) == 68
    assert len({e.id for e in entries}) == len(entries)
    assert kb.KB_VERSION.startswith('palm-kb ')


def test_every_entry_names_sources_that_exist():
    sources = kb.sources()
    assert set(sources) == {'S1', 'S2', 'S3', 'S4'}
    for entry in kb.entries():
        # the one entry without a source is about this app's own photos (how to take a better one), not about palmistry
        assert entry.basis or entry.id == 'limits.photo', entry.id
        assert set(entry.basis) <= set(sources), entry.id
    for source in sources.values():
        assert source['title'] and source['author'] and source['url'].startswith('https://')


@pytest.mark.parametrize('entry', kb.entries(), ids=lambda e: e.id)
def test_every_entry_passes_the_safety_rules(entry):
    assert guard.check(guard.clean(entry.text), subject_for_entry(entry)) == []


def test_every_line_has_an_entry_for_every_length_curve_and_clarity():
    for line in FEATURE_ORDER:
        assert kb.line_entry(line) is not None
        for length in LENGTHS:
            assert kb.line_entry(line, 'length', length) is not None, (line, length)
        for curve in CURVES:
            assert kb.line_entry(line, 'curve', curve) is not None, (line, curve)
        for clarity in CLARITIES:
            assert kb.line_entry(line, 'clarity', clarity) is not None, (line, clarity)
        assert kb.line_entry(line, 'clarity', 'faint') is None
    assert len(kb.of_kind('line')) == 5 * (1 + 3 + 3 + 2)


def test_the_four_hand_shapes_and_the_general_note_exist():
    assert {e.get('element') for e in kb.of_kind('shape')} == {None, 'earth', 'air', 'water', 'fire'}
    assert element_of(PalmShapeTraits(palm='square', fingers='short')) == 'earth'
    assert element_of(PalmShapeTraits(palm='square', fingers='long')) == 'air'
    assert element_of(PalmShapeTraits(palm='long', fingers='long')) == 'water'
    assert element_of(PalmShapeTraits(palm='long', fingers='short')) == 'fire'


def test_themes_say_which_lines_they_are_read_from_and_what_each_adds():
    assert [t.id for t in THEMES] == ['personality', 'career', 'financial', 'relationships', 'future']
    for entry in kb.of_kind('theme'):
        reads, roles = entry.get('reads'), entry.get('roles')
        assert set(roles) == set(reads), entry.id
        assert all(name in {*FEATURE_ORDER, 'shape'} for name in reads)
        assert entry.get('outro') and entry.get('intro')
    assert THEMES[-1].outro.endswith('Palmistry is a traditional practice, not a science.')


def test_what_palmistry_does_not_claim_is_written_down():
    topics = {e.get('topic') for e in kb.of_kind('limits')}
    assert {'science', 'medical', 'lifespan', 'financial', 'employment', 'relationship', 'prediction', 'missing', 'photo'} <= topics
    assert 'pseudoscience' in kb.limit_entry('science').text


def test_older_claims_about_health_and_lifespan_are_left_out_on_purpose():
    life = kb.line_entry('life').text.lower()
    assert 'does not use those claims' in life  # the entry says it leaves them out
    for entry in kb.of_kind('line'):
        assert not guard.SENSITIVE['lifespan'].search(entry.text) or guard.NEGATION.search(entry.text), entry.id


def test_the_fixed_rule_wording_is_built_from_the_entries():
    traits = FeatureTraits(length='long', curve='gentle', clarity='deep')
    text = traditional_text('heart', 'detected', traits)
    assert text.startswith('In traditional palmistry the heart line is linked with ')
    for trait, value in (('length', 'long'), ('curve', 'gentle'), ('clarity', 'deep')):
        assert KB['heart'][trait][value][:1].upper() + KB['heart'][trait][value][1:] in text
    assert traditional_text('fate', 'not_visible', FeatureTraits()) is None  # nothing is claimed about a line that was not seen
    assert 'nothing is said about its length or shape' in traditional_text('fate', 'uncertain', FeatureTraits())
    assert line_clause('heart', traits).endswith('.') and shape_clause(PalmShapeTraits(palm='square', fingers='short')).startswith('A square palm')
