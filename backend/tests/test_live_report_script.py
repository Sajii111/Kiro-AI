"""scripts/live_report.py, which the person runs on their own photos. Here it runs on two drawn hands (a fake hand finder stands in
for the hand model) with a fake Gemini. What matters: it shows what was found and exactly what Gemini is told, labels who wrote
each passage, never prints the key, saves a copy outside the project, and still works with no key at all."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fake_gemini import FakeModel, good, good_answer, service_for, unavailable
from realapp import drawn_hands
from synth import FakeFinder

from app.core.config import Settings
from app.llm.writer import REPEATS

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'live_report.py'
KEY = 'AIzaSyTestKeyForTheScriptOnly0123456789'
SETTINGS = Settings(gemini_api_key=KEY, gemini_model='fake-gemini')


@pytest.fixture(scope='module')
def live():
    spec = importlib.util.spec_from_file_location('live_report', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def photos(tmp_path):
    """A folder with the two drawn hands as left.jpg and right.jpg, and the fake finder that knows them."""
    hands = drawn_hands()
    folder = tmp_path / 'test-photos' / 'person1'
    folder.mkdir(parents=True)
    (folder / 'left.jpg').write_bytes(hands.left)
    (folder / 'right.jpg').write_bytes(hands.right)
    return folder, FakeFinder(hands.known), tmp_path / 'debug'


def flat(text: str) -> str:
    return ' '.join(text.split())


def run(live, capsys, photos, argv=(), respond=good, settings=SETTINGS):
    folder, finder, out = photos
    model = FakeModel(respond)
    code = live.main([str(folder), '--out', str(out), *argv], settings=settings, make_service=lambda s: service_for(model), finder=finder)
    return code, capsys.readouterr().out, model


# ------------------------------------------------------------------ with Gemini


def test_it_shows_the_findings_what_gemini_is_told_and_the_report_with_who_wrote_what(live, capsys, photos):
    code, out, model = run(live, capsys, photos)
    assert code == 0
    for part in ('WHAT WAS FOUND', 'WHAT GEMINI IS TOLD', 'THE REPORT', 'SUMMARY [app]', 'HEART LINE', 'HAND SHAPE', 'THEME: YOUR PERSONALITY', 'UNCERTAINTY [app]', 'DISCLAIMER', 'HOW THIS READING WAS MADE'):
        assert part in out, part
    assert '[Gemini]' in out and 'writer: gemini / fake-gemini' in out
    assert 'Gemini wrote' in out and 'passed every check' in out
    assert model.calls == 1  # one request carries the whole report


def test_the_findings_gemini_is_told_are_printed_as_the_words_that_are_sent(live, capsys, photos):
    _, out, model = run(live, capsys, photos)
    shown = out.split('WHAT GEMINI IS TOLD')[1].split('Asking Gemini')[0]
    assert '"heart":{"status"' in shown and 'photo' not in shown.lower().replace('no photo', '')
    sent = model.requests[0].prompt
    assert 'left.jpg' not in sent and 'right.jpg' not in sent and 'person1' not in sent and 'test-photos' not in sent


def test_the_key_is_never_printed_or_saved(live, capsys, photos):
    _, out, _ = run(live, capsys, photos)
    saved = (photos[2] / 'live_report_person1.txt').read_text(encoding='utf-8')
    assert KEY not in out and 'AIza' not in out and KEY not in saved


def test_a_text_copy_is_saved_where_it_was_asked_and_holds_what_was_printed(live, capsys, photos):
    _, out, _ = run(live, capsys, photos)
    saved = (photos[2] / 'live_report_person1.txt').read_text(encoding='utf-8')
    assert 'THE REPORT' in saved and 'WHAT WAS FOUND' in saved
    assert 'never commit it' in out and 'live_report_person1.txt' in out
    assert not any(p.suffix in ('.jpg', '.png') for p in photos[2].iterdir())  # only text: the photos are not copied anywhere


def test_a_passage_the_checks_refuse_keeps_the_fixed_wording_and_is_labelled_so(live, capsys, photos):
    def mixed(prompt):
        out = good_answer(prompt)
        out['heart_left'] = 'In traditional palmistry this heart line means you will meet someone special next year.'
        return out

    code, out, _ = run(live, capsys, photos, respond=mixed)
    assert code == 0
    assert 'These kept the fixed wording, and why:' in out and 'heart_left:' in out
    assert 'Tradition, left hand [fixed wording]' in out and 'Tradition, left hand [Gemini]' in out


def test_when_gemini_fails_the_report_is_still_written_and_says_why(live, capsys, photos):
    code, out, _ = run(live, capsys, photos, respond=lambda p: unavailable('rate_limited', f'Quota exceeded for {KEY}'))
    assert code == 0 and KEY not in out
    assert 'The last request failed' in out and '[rate_limited]' in out
    assert 'THE REPORT   (all the words come from the knowledge base)' in out or '[fixed wording]' in out
    assert 'writer: knowledge-base / rule-based-writer' in out
    assert 'Gemini’s free allowance is used up for now' in flat(out)


def test_a_busy_spell_that_passes_is_mentioned_and_the_report_is_still_by_gemini(live, capsys, photos):
    answers = iter([unavailable('overloaded', 'This model is currently experiencing high demand.')])

    def respond(prompt):
        failure = next(answers, None)
        return failure if failure is not None else good_answer(prompt)

    code, out, model = run(live, capsys, photos, respond=respond)
    assert code == 0 and model.calls == 2
    assert 'repeated once because Google was busy' in out and 'Tradition, left hand [Gemini]' in out and 'The last request failed' not in out


def test_two_busy_answers_in_a_row_are_reported_as_busy_not_as_unreachable(live, capsys, photos):
    code, out, model = run(live, capsys, photos, respond=lambda p: unavailable('overloaded', 'This model is currently experiencing high demand.'))
    assert code == 0 and model.calls == 1 + REPEATS and '[overloaded]' in out and 'Gemini is very busy right now' in flat(out)  # the report is asked for, then repeated
    assert f'repeated {REPEATS} times because Google was busy' in out and 'writer: knowledge-base / rule-based-writer' in out


def test_it_says_which_gemini_models_take_turns_and_which_one_wrote(live, capsys, photos):
    _, out, _ = run(live, capsys, photos)
    assert 'Gemini: fake-gemini (if it is busy: gemini-3.1-flash-lite, gemma-4-31b-it, gemma-4-26b-a4b-it).' in out
    assert 'The model that wrote them: fake-gemini' in out


def test_model_uses_that_one_model_alone(live, capsys, photos):
    seen = []
    folder, finder, out_dir = photos

    def make(settings):
        seen.append(settings.gemini_models)
        return service_for(FakeModel(good))

    code = live.main([str(folder), '--out', str(out_dir), '--model', ' gemini-2.5-flash '], settings=SETTINGS, make_service=make, finder=finder)
    out = capsys.readouterr().out
    assert code == 0 and seen == [['gemini-2.5-flash']] and 'Gemini: gemini-2.5-flash.' in out and 'if it is busy' not in out


def test_the_examiner_is_asked_to_look_for_dates_health_money_orders_and_invented_marks(live, capsys, photos):
    _, out, _ = run(live, capsys, photos)
    assert 'fortune teller' in flat(out) and 'a date or an age' in flat(out) and 'names a mark your hands do not show' in flat(out)


# ------------------------------------------------------------------ without Gemini


def test_no_gemini_shows_the_fixed_wording_only_and_asks_nobody(live, capsys, photos):
    code, out, model = run(live, capsys, photos, argv=['--no-gemini'])
    assert code == 0 and model.calls == 0
    assert 'WHAT GEMINI IS TOLD' not in out and '[Gemini]' not in out
    assert 'all the words come from the knowledge base' in out and 'writer: knowledge-base / rule-based-writer' in out


def test_without_a_key_it_still_works_and_says_gemini_was_not_used(live, capsys, photos):
    folder, finder, out_dir = photos
    code = live.main([str(folder), '--out', str(out_dir)], settings=Settings(), make_service=lambda s: service_for(None), finder=finder)
    out = capsys.readouterr().out
    assert code == 0 and 'Gemini: not used, because there is no key' in flat(out) and 'THE REPORT' in out


# ------------------------------------------------------------------ the photos


def test_a_folder_without_both_photos_says_what_to_do(live, capsys, tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    (empty / 'left.jpg').write_bytes(b'x')
    code = live.main([str(empty), '--out', str(tmp_path / 'debug')], settings=SETTINGS, make_service=lambda s: service_for(FakeModel()), finder=FakeFinder())
    out = capsys.readouterr().out
    assert code == 1 and 'No left and right photo found' in out and 'left.jpg' in out and 'right.jpg' in out


def test_a_photo_that_fails_the_checks_is_named_with_the_reason_and_nothing_is_sent(live, capsys, tmp_path):
    folder = tmp_path / 'p'
    folder.mkdir()
    (folder / 'left.jpg').write_bytes(b'this is not a photo')
    (folder / 'right.jpg').write_bytes(drawn_hands().right)
    model = FakeModel()
    code = live.main([str(folder), '--out', str(tmp_path / 'debug')], settings=SETTINGS, make_service=lambda s: service_for(model), finder=FakeFinder(drawn_hands().known))
    out = capsys.readouterr().out
    assert code == 1 and 'The left photo (left.jpg) does not pass the photo checks' in out and model.calls == 0


def test_the_folder_can_be_given_as_a_name_beside_the_project_or_in_test_photos(live, tmp_path, monkeypatch):
    monkeypatch.setattr(live, 'TEST_PHOTOS', tmp_path / 'photos')
    monkeypatch.setattr(live, 'ROOT', tmp_path / 'proj')
    (tmp_path / 'photos' / 'person2').mkdir(parents=True)
    (tmp_path / 'test-photos' / 'person3').mkdir(parents=True)
    assert live.resolve_folder('person2') == tmp_path / 'photos' / 'person2'
    assert live.resolve_folder('test-photos/person3') == tmp_path / 'test-photos' / 'person3'  # beside the project folder
    assert live.resolve_folder(None) == tmp_path / 'photos' / 'person1'
    assert live.resolve_folder(str(tmp_path / 'photos' / 'person2')) == tmp_path / 'photos' / 'person2'


def test_left_and_right_are_told_apart_by_the_file_name_even_in_a_subfolder(live, tmp_path):
    sub = tmp_path / 'a' / 'b'
    sub.mkdir(parents=True)
    for name in ('IMG_1_Left.JPG', 'IMG_2_RIGHT.png', 'notes.txt'):
        (sub / name).write_bytes(b'x')
    pair = live.find_pair(tmp_path / 'a')
    assert pair is not None and pair[0].name == 'IMG_1_Left.JPG' and pair[1].name == 'IMG_2_RIGHT.png'
    assert live.find_pair(tmp_path / 'nothing') is None
