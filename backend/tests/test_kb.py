"""The palmistry knowledge base (app/llm/kb/): every entry is well formed, cites a source, and obeys the same safety rules the
language model's passages are held to. These tests are what makes "the entries are cautious" a checked fact instead of a hope."""

from __future__ import annotations

import pytest
from test_standin import hands_for

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
from app.llm.report import build_report
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
    assert 'A palm shows the shape of the road, not every step' in THEMES[-1].outro  # the last theme carries the honest line, in the reader's voice


def test_what_palmistry_does_not_claim_is_written_down():
    topics = {e.get('topic') for e in kb.of_kind('limits')}
    assert {'science', 'medical', 'lifespan', 'financial', 'employment', 'relationship', 'prediction', 'missing', 'photo'} <= topics
    assert 'pseudoscience' in kb.limit_entry('science').text


def test_older_claims_about_health_and_lifespan_are_left_out_on_purpose():
    life = kb.line_entry('life').text.lower()
    assert 'not a clock' in life and 'says nothing about how many years' in life  # the entry says it is not a measure of a life
    for entry in kb.of_kind('line'):
        assert not guard.SENSITIVE['lifespan'].search(entry.text) or guard.NEGATION.search(entry.text), entry.id


def test_the_fixed_rule_wording_is_built_from_the_entries():
    traits = FeatureTraits(length='long', curve='gentle', clarity='deep')
    text = traditional_text('heart', 'detected', traits)
    assert text.startswith('Your heart line ')
    for trait, value in (('length', 'long'), ('curve', 'gentle'), ('clarity', 'deep')):
        assert KB['heart'][trait][value][:1].upper() + KB['heart'][trait][value][1:] in text
    assert traditional_text('fate', 'not_visible', FeatureTraits()) is None  # nothing is claimed about a line that was not seen
    assert 'Its length and shape could not be read' in traditional_text('fate', 'uncertain', FeatureTraits())
    assert line_clause('heart', traits).endswith('.') and shape_clause(PalmShapeTraits(palm='square', fingers='short')).startswith('A square palm')


# ---------------------------------------------------------------- plain words: no fancy or technical word anywhere in the notes


def every_piece_of_wording(entry: kb.Entry) -> list[str]:
    """All the words an entry can put on screen or in front of the model: its statement, its clause, and the short phrases the
    fixed writer joins into sentences (a theme's title, introduction, closing line and roles; a hand shape's words)."""
    pieces = [entry.text]
    for value in entry.fields.values():
        if isinstance(value, str):
            pieces.append(value)
    pieces += [str(v) for v in (entry.get('roles') or {}).values()]
    return pieces


@pytest.mark.parametrize('entry', kb.entries(), ids=lambda e: e.id)
def test_every_word_of_every_entry_is_plain(entry):
    for piece in every_piece_of_wording(entry):
        assert guard.FANCY.search(piece) is None, (entry.id, guard.FANCY.search(piece).group(0), piece)


def test_the_sentences_are_short_enough_to_read_at_a_glance():
    for entry in kb.entries():
        for sentence in guard.sentences(entry.text):
            assert len(sentence.split()) <= 30, (entry.id, sentence)
        assert len((entry.get('short') or '').split()) <= 30, entry.id


def test_an_entry_about_a_line_that_was_found_speaks_to_the_person():
    for entry in kb.of_kind('line'):
        words = f' {entry.text.lower()} '
        assert ' you ' in words or ' your ' in words, entry.id


@pytest.mark.parametrize('seed', ['rd_0000000000000001', 'rd_000000000000000a', 'rd_0000000000000007'])
def test_the_fixed_wording_of_a_whole_report_is_plain_from_top_to_bottom(seed):
    report = build_report(hands_for(seed, 0.95, 0.95), '2026-01-01T00:00:00.000Z')
    texts = [report.summary, report.disclaimer, report.shape.comparison or '', *report.uncertainty]
    for section in report.sections:
        texts += [section.comparison or '', section.traditional.left or '', section.traditional.right or '']
    texts += [report.shape.traditional.left or '', report.shape.traditional.right or '']
    texts += [theme.traditional or '' for theme in report.themes]
    assert any(len(t) > 50 for t in texts)
    for text in texts:
        assert guard.FANCY.search(text) is None, text


def test_the_themes_have_plain_names():
    assert [t.title for t in THEMES] == ['Your personality', 'Work and career', 'Money and success', 'Love and relationships', 'What lies ahead']
