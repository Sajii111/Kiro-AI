"""The language-model report writer (app/llm/writer.py), run against a fake Gemini that is made to behave well and badly.
The things that matter: what the model is shown, what it is asked, which of its passages are used, and that the report is
never worse than the fixed wording, whatever the model does."""

from __future__ import annotations

import json

import pytest
from fake_gemini import FakeModel, asked, good_answer, service_for, unavailable
from test_standin import hands_for

from app.cv.versions import REAL_DETECTOR, REAL_PIPELINE
from app.llm import prompts, writer
from app.llm.knowledge import THEMES
from app.llm.report import (
    REAL_META,
    STAND_IN_META,
    build_report,
    compare_parts,
    left_out_sentence,
    near_the_line,
)
from app.llm.retrieval import feature
from app.schemas import Hands, PalmShape, PalmShapeTraits, Reading

BAD = 'In traditional palmistry this line means you will meet someone special next year.'


def setup(seed='rd_0000000000000001', respond=None, **options):
    hands = hands_for(seed, 0.95, 0.95)
    baseline = build_report(hands, '2026-01-01T00:00:00.000Z')
    model = FakeModel(respond)
    return hands, baseline, model, service_for(model, **options)


def reading_for(hands, meta=REAL_META):
    return Reading(
        id='rd_test',
        profileId='prf_test',
        createdAt='2026-01-01T00:00:00.000Z',
        hands=Hands(left=hands['left'], right=hands['right']),
        report=build_report(hands, '2026-01-01T00:00:00.000Z'),
        meta=meta,
    )


def answer_with(bad: dict[str, str], *, always=False):
    """A model that answers well except for the passages in `bad`, which it gets wrong the first time (or every time)."""
    calls = []

    def respond(prompt):
        calls.append(prompt)
        out = good_answer(prompt)
        if always or len(calls) == 1:
            out.update({k: v for k, v in bad.items() if k in out})
        return out

    return respond


# ---------------------------------------------------------------- how firm the hand shape is


def shape_of(*, palm=1.03, fingers=1.08, status='detected', method=REAL_DETECTOR):
    return PalmShape(
        status=status,
        traits=PalmShapeTraits(palm='square', fingers='long'),
        palmRatio=palm,
        fingerRatio=fingers,
        confidence=0.8,
        observation='A square palm with long fingers.',
        method=method,
    )


def test_a_shape_measured_close_to_a_dividing_line_says_so():
    assert near_the_line(shape_of(fingers=0.99)) == ['the finger length (0.99) is close to the line between short and long fingers']
    assert near_the_line(shape_of(fingers=1.04)) == ['the finger length (1.04) is close to the line between short and long fingers']
    assert near_the_line(shape_of(palm=0.90)) == ['the palm width (0.90) is close to the line between a square and a long palm']
    assert len(near_the_line(shape_of(palm=0.87, fingers=1.02))) == 2


def test_a_shape_measured_well_away_from_the_lines_says_nothing():
    assert near_the_line(shape_of(palm=1.03, fingers=1.08)) == []
    assert near_the_line(shape_of(palm=0.95, fingers=0.94)) == []  # 0.07 and 0.06 away from the lines is not "close"


def test_only_a_real_measurement_of_a_clear_hand_can_be_close_to_a_line():
    assert near_the_line(shape_of(fingers=0.99, status='uncertain')) == []
    assert near_the_line(shape_of(fingers=0.99, method='sample-detector 0.2')) == []  # a stand-in's numbers are drawn, not measured


def test_the_report_lists_a_close_call_among_what_is_uncertain_but_keeps_the_word():
    hands = hands_for('rd_0000000000000001', 0.95, 0.95)
    quiet = build_report(hands, '2026-01-01T00:00:00.000Z')
    assert not [u for u in quiet.uncertainty if 'close to the line' in u]
    hands['left'] = hands['left'].model_copy(update={'palmShape': shape_of(palm=0.915, fingers=0.986)})  # a real left hand: both near a line
    hands['right'] = hands['right'].model_copy(update={'palmShape': shape_of(palm=1.033, fingers=1.076)})
    report = build_report(hands, '2026-01-01T00:00:00.000Z')
    close = [u for u in report.uncertainty if 'close to the line' in u]
    expected = (
        'Left hand, shape: the finger length (0.99) is close to the line between short and long fingers and the palm width (0.92) is close '
        'to the line between a square and a long palm, so another photo of the same hand could be called the other way.'
    )
    assert close == [expected]
    assert report.shape.observed.left.text == hands['left'].palmShape.observation  # the word itself is unchanged


# ---------------------------------------------------------------- the model's passages go in, the server's facts stay


def test_a_well_behaved_model_writes_every_interpretive_passage_in_one_call():
    hands, baseline, model, service = setup()
    outcome = writer.write_report(hands, baseline, service)
    keys = [key for key, _ask, _ids in asked(model.requests[0].prompt)]
    assert model.calls == 1 and outcome.calls == 1 and outcome.error is None
    assert set(outcome.accepted) == set(keys) and outcome.replaced == {} and outcome.asked == len(keys)
    request = model.requests[0]
    assert request.temperature == 0.2 and request.max_tokens == writer.MAX_TOKENS and request.system == prompts.REPORT_SYSTEM
    assert list(request.schema['properties']) == keys and request.schema['required'] == keys


def test_what_the_photos_show_is_always_written_by_the_server():
    hands, baseline, _model, service = setup()
    report = writer.write_report(hands, baseline, service).report
    assert report.disclaimer == baseline.disclaimer and report.uncertainty == baseline.uncertainty and report.generatedAt == baseline.generatedAt
    assert report.shape.observed == baseline.shape.observed and report.shape.comparison == baseline.shape.comparison
    for new, old in zip(report.sections, baseline.sections, strict=True):
        assert new.observed == old.observed and new.title == old.title
    assert [(t.themeId, t.basedOn, t.leftOut) for t in report.themes] == [(t.themeId, t.basedOn, t.leftOut) for t in baseline.themes]


def test_the_models_passages_replace_the_fixed_sentences_where_a_line_was_detected():
    hands, baseline, _model, service = setup()
    outcome = writer.write_report(hands, baseline, service)
    report = outcome.report
    for section, old in zip(report.sections, baseline.sections, strict=True):
        for side in ('left', 'right'):
            status = getattr(section.observed, side).status
            new = getattr(section.traditional, side)
            if status == 'detected':
                assert new == outcome.accepted[f'{section.featureId}_{side}'] != getattr(old.traditional, side)
            else:  # a line that was not clearly seen keeps the server's loose or empty wording
                assert new == getattr(old.traditional, side)
    assert report.shape.traditional.left == outcome.accepted['shape_left']


def test_the_summary_keeps_the_servers_facts_and_adds_the_models_overview():
    hands, baseline, _model, service = setup()
    outcome = writer.write_report(hands, baseline, service)
    assert outcome.report.summary == f'{baseline.summary}\n{outcome.accepted["summary"]}'
    assert 'not a science' in outcome.accepted['summary']


def test_a_comparison_keeps_the_servers_description_of_the_two_hands_and_adds_what_the_tradition_reads():
    hands, baseline, _model, service = setup()
    outcome = writer.write_report(hands, baseline, service)
    for section in outcome.report.sections:
        key = f'compare_{section.featureId}'
        parts = compare_parts(section.title, feature(hands['left'], section.featureId), feature(hands['right'], section.featureId))
        if key in outcome.accepted:
            assert section.comparison == f'{parts[0]} {outcome.accepted[key]}' and parts[0].startswith(f'The {section.title.lower()}')
        else:  # only one hand showed the line, or neither: nothing to read from a comparison
            assert section.comparison == next(s for s in baseline.sections if s.featureId == section.featureId).comparison


def test_a_theme_is_the_models_text_then_what_was_left_out_then_the_fixed_reminder():
    hands, baseline, _model, service = setup()
    outcome = writer.write_report(hands, baseline, service)
    outros = {t.id: t.outro for t in THEMES}
    for theme in outcome.report.themes:
        key = f'theme_{theme.themeId}'
        if key not in outcome.accepted:
            continue
        lines = theme.traditional.split('\n')
        assert lines[0] == outcome.accepted[key] and lines[-1] == outros[theme.themeId]
        left_out = left_out_sentence(list(theme.leftOut))
        assert (left_out in lines) == bool(left_out)


# ---------------------------------------------------------------- a passage that breaks a rule


def test_a_passage_that_breaks_a_rule_is_asked_for_again_with_the_complaint_and_nothing_else_is():
    hands, baseline, model, service = setup(respond=answer_with({'heart_left': BAD}))
    outcome = writer.write_report(hands, baseline, service)
    first, second = model.requests
    assert model.calls == 2 and outcome.replaced == {} and 'heart_left' in outcome.accepted
    assert list(second.schema['properties']) == ['heart_left']  # only the failed passage is asked for again
    assert 'Your earlier answer was rejected' in second.prompt and 'heart_left: predicts or gives timing' in second.prompt
    assert BAD not in outcome.report.sections[0].traditional.left
    assert len(second.prompt) < len(first.prompt)


def test_a_passage_that_fails_twice_keeps_the_fixed_wording_and_the_rest_are_used():
    hands, baseline, model, service = setup(respond=answer_with({'heart_left': BAD}, always=True))
    outcome = writer.write_report(hands, baseline, service)
    assert model.calls == 2 and list(outcome.replaced) == ['heart_left'] and 'predicts' in outcome.replaced['heart_left'][0]
    assert outcome.report.sections[0].traditional.left == baseline.sections[0].traditional.left
    assert outcome.report.sections[0].traditional.right == outcome.accepted['heart_right']
    assert len(outcome.accepted) == outcome.asked - 1
    meta = writer.meta_for(outcome, service)
    assert meta.provider == 'gemini' and meta.note == f'Gemini wrote {outcome.asked - 1} of {outcome.asked} passages. The other 1 did not pass a safety check, so they use the fixed wording from the knowledge base.'


@pytest.mark.parametrize(
    ('key', 'passage', 'word'),
    [
        ('heart_left', 'In traditional palmistry the heart line is read as warmth, shown by 3 branches.', 'number'),
        ('head_right', 'In traditional palmistry the head line is read as thinking style, and you should trust your mind.', 'advice'),
        ('life_left', 'In traditional palmistry the life line is read as energy, and also says how long you will live.', 'lifespan'),
        ('shape_left', 'In traditional palmistry this hand is called an earth hand, with a mount of Venus below.', 'not among the findings'),
        ('compare_head', 'This is only a comparison with no framing.', 'tradition reading'),
        ('theme_personality', 'In traditional palmistry the sun line, the fate line and the head line show personality.', 'not clearly seen'),
        ('heart_right', 'In traditional palmistry the left hand heart line is long and so is this one.', 'other hand'),
    ],
)
def test_each_kind_of_bad_passage_is_caught_and_replaced(key, passage, word):
    hands, baseline, _model, service = setup('rd_000000000000000a', respond=answer_with({key: passage}, always=True))
    if key not in {k for k, _a, _i in asked(prompts.report_prompt(hands, prompts.plan_fields(hands)))}:
        pytest.skip('this reading has no such passage')
    outcome = writer.write_report(hands, baseline, service)
    assert key in outcome.replaced and any(word in reason for reason in outcome.replaced[key]), outcome.replaced
    assert passage not in json.dumps(outcome.report.model_dump())


def test_a_passage_that_describes_a_line_differently_from_the_findings_is_replaced():
    hands, baseline, _model, service = setup(respond=answer_with({'heart_left': 'In traditional palmistry a short heart line is read as reserve.'}, always=True))
    assert feature(hands['left'], 'heart').traits.length == 'long'
    outcome = writer.write_report(hands, baseline, service)
    assert 'calls the line short' in outcome.replaced['heart_left'][0]


# ---------------------------------------------------------------- an answer that is not usable


def test_an_answer_that_is_not_json_is_asked_for_again_and_then_the_fixed_wording_stands():
    hands, baseline, model, service = setup(respond=lambda prompt: 'Sorry, I cannot write that.')
    outcome = writer.write_report(hands, baseline, service)
    assert model.calls == 2 and outcome.accepted == {} and outcome.error.kind == 'bad_output'
    assert outcome.report == baseline
    meta = writer.meta_for(outcome, service)
    assert (meta.provider, meta.model) == ('knowledge-base', 'rule-based-writer') and 'not in the form' in meta.note


def test_a_first_answer_that_is_not_json_does_not_cost_the_reading_if_the_second_is_good():
    answers = ['not json', None]

    def respond(prompt):
        return answers.pop(0) or good_answer(prompt)

    hands, baseline, model, service = setup(respond=respond)
    outcome = writer.write_report(hands, baseline, service)
    assert model.calls == 2 and outcome.replaced == {} and len(outcome.accepted) == outcome.asked and outcome.error is None


def test_an_answer_wrapped_in_a_code_fence_is_still_read():
    assert writer.parse_passages('```json\n{"a": "x", "b": 3}\n```', ['a', 'b', 'c']) == {'a': 'x'}  # b is not text, c is missing
    with pytest.raises(writer.ModelUnavailable):
        writer.parse_passages('[1, 2]', ['a'])


def test_a_passage_missing_from_the_answer_is_replaced():
    def respond(prompt):
        out = good_answer(prompt)
        out.pop('summary', None)
        return out

    hands, baseline, _model, service = setup(respond=respond)
    outcome = writer.write_report(hands, baseline, service)
    assert outcome.replaced == {'summary': ['was missing from the answer']} and outcome.report.summary == baseline.summary


def test_line_breaks_inside_a_passage_become_spaces_and_markdown_is_removed():
    hands, baseline, _model, service = setup(respond=answer_with({'heart_left': '**In traditional palmistry** the heart line is linked with emotional style,\nand a long one is read as warmth.'}))
    outcome = writer.write_report(hands, baseline, service)
    assert outcome.accepted['heart_left'] == 'In traditional palmistry the heart line is linked with emotional style, and a long one is read as warmth.'


# ---------------------------------------------------------------- the model is not available


@pytest.mark.parametrize(
    ('kind', 'requests'),
    [('rate_limited', 1), ('timeout', 1), ('bad_key', 1), ('bad_model', 1), ('blocked', 1), ('cut_off', 1), ('overloaded', 2), ('error', 2)],
)
def test_when_the_model_cannot_answer_the_reading_still_finishes_with_the_fixed_wording(kind, requests):
    hands, baseline, model, service = setup(respond=lambda prompt: unavailable(kind, 'detail'))
    outcome = writer.write_report(hands, baseline, service)
    assert outcome.report == baseline and outcome.accepted == {} and outcome.error.kind == kind
    assert model.calls == requests  # asking again straight away would not help, except when Google is only busy: that is tried once more
    assert outcome.calls == 1 and outcome.repeats == requests - 1
    reading = writer.write_reading(reading_for(hands), service)
    assert reading.report == baseline
    assert (reading.meta.provider, reading.meta.mock) == ('knowledge-base', False)
    assert reading.meta.note.startswith('Gemini was not used for this reading because ') and reading.meta.note.endswith('so the words come from the knowledge base.')


def test_a_busy_spell_that_passes_in_seconds_still_gives_a_gemini_report():
    answers = iter([unavailable('overloaded', 'This model is currently experiencing high demand.')])

    def respond(prompt):
        failure = next(answers, None)
        return failure if failure is not None else good_answer(prompt)

    hands, baseline, model, service = setup(respond=respond)
    outcome = writer.write_report(hands, baseline, service)
    assert model.calls == 2 and outcome.calls == 1 and outcome.repeats == 1  # one request made, repeated once
    assert outcome.error is None and outcome.replaced == {} and len(outcome.accepted) == outcome.asked
    assert service.resting_for() == 0
    reading = writer.write_reading(reading_for(hands), service)  # the next reading is not held back either
    assert reading.meta.provider == 'gemini' and reading.meta.note.startswith('Gemini wrote all ')


def test_two_busy_answers_in_a_row_leave_the_fixed_wording_and_say_why():
    hands, baseline, model, service = setup(respond=lambda prompt: unavailable('overloaded', 'This model is currently experiencing high demand.'))
    reading = writer.write_reading(reading_for(hands), service)
    assert model.calls == 2 and reading.report == baseline
    assert (reading.meta.provider, reading.meta.mock) == ('knowledge-base', False)
    assert reading.meta.note == 'Gemini was not used for this reading because Gemini is very busy right now, so the words come from the knowledge base.'
    assert service.resting_for() > 0  # the next reading does not queue up behind a busy Google: it goes straight to the fixed wording


def test_a_server_with_no_key_leaves_the_reading_exactly_as_it_was():
    hands, _baseline, _model, _service = setup()
    reading = reading_for(hands)
    assert writer.write_reading(reading, service_for(None)) is reading
    assert reading.meta.note is None


def test_a_sample_reading_is_never_rewritten_or_sent_anywhere():
    hands, _baseline, model, service = setup()
    reading = reading_for(hands, STAND_IN_META)
    assert writer.write_reading(reading, service) is reading and model.calls == 0


def test_a_real_reading_says_which_words_gemini_wrote():
    hands, _baseline, model, service = setup()
    reading = reading_for(hands)
    new = writer.write_reading(reading, service)
    assert new.hands == reading.hands and (new.id, new.profileId, new.createdAt) == (reading.id, reading.profileId, reading.createdAt)
    assert new.report != reading.report
    assert new.meta.provider == 'gemini' and new.meta.model == 'fake-gemini' and new.meta.mock is False
    assert new.meta.prompt == 'report-prompt 1.0 + guard 1.0' and new.meta.pipeline == f'{REAL_PIPELINE} + {REAL_DETECTOR}'
    assert new.meta.note.startswith('Gemini wrote all ') and 'passed the safety checks' in new.meta.note
    assert model.calls == 1


def test_the_writer_never_raises_whatever_the_model_does(monkeypatch):
    hands, _baseline, _model, service = setup(respond=lambda prompt: RuntimeError('socket closed'))
    reading = reading_for(hands)
    assert writer.write_reading(reading, service).report == reading.report
    monkeypatch.setattr(writer, 'write_report', lambda *a, **k: 1 / 0)  # a bug in the writer itself
    kept = writer.write_reading(reading, service)
    assert kept.report == reading.report and 'unexpected problem' in kept.meta.note


def test_a_cancelled_reading_is_not_asked_for_a_second_time():
    states = iter([False, True])
    hands, baseline, model, service = setup(respond=answer_with({'heart_left': BAD}))
    outcome = writer.write_report(hands, baseline, service, cancelled=lambda: next(states))
    assert model.calls == 1 and 'heart_left' in outcome.replaced


def test_the_same_findings_are_not_paid_for_twice():
    hands, baseline, model, service = setup()
    first = writer.write_report(hands, baseline, service)
    second = writer.write_report(hands, baseline, service)
    assert model.calls == 1 and service.cache_hits == 1 and first.report == second.report


# ---------------------------------------------------------------- what the model is shown and asked


def test_the_model_is_only_asked_about_lines_that_were_detected_and_is_never_shown_the_others():
    hands, _baseline, model, service = setup('rd_000000000000000a')
    writer.write_report(hands, build_report(hands, 'x'), service)
    prompt = model.requests[0].prompt
    keys = [k for k, _a, _i in asked(prompt)]
    assert not any(k.startswith(('fate', 'sun', 'compare_fate')) for k in keys)
    knowledge = prompt.split('KNOWLEDGE', 1)[1].split('WRITE these', 1)[0]
    assert '[fate.' not in knowledge and '[sun.' not in knowledge
    assert 'fate line' not in knowledge and 'sun line' not in knowledge  # not even the theme notes name a line that was not seen
    findings = json.loads(prompt.split('\n', 1)[1].split('\n\nKNOWLEDGE')[0])
    assert findings['left']['lines']['fate'] == {'status': 'not_visible'}  # said plainly, with no traits to improvise on
    assert findings['right']['lines']['sun'] == {'status': 'uncertain'}


def test_a_theme_note_names_only_the_sources_that_were_detected():
    hands, _baseline, model, service = setup('rd_000000000000000a')
    writer.write_report(hands, build_report(hands, 'x'), service)
    knowledge = model.requests[0].prompt
    career = next(line for line in knowledge.splitlines() if line.startswith('[theme.career]'))
    assert career == '[theme.career] In traditional palmistry, the "Career and professional life" theme is read from the head line (working style).'


def test_the_system_prompt_states_the_rules_and_the_findings_carry_no_personal_data():
    hands, _baseline, model, service = setup()
    writer.write_report(hands, build_report(hands, 'x'), service)
    request = model.requests[0]
    system = request.system.lower()
    for rule in ('never say that you see', 'never predict', 'never give advice', 'plain text only', 'say so plainly'):
        assert rule in system, rule
    payload = prompts.findings_payload(hands)
    assert set(payload) == {'left', 'right'}
    assert all(set(side) == {'lines', 'handShape'} for side in payload.values())
