"""scripts/check_gemini.py, the check the person runs on their own computer once their key is in backend/.env. It runs here
against a fake Gemini: what matters is that it tells the truth about what worked, never prints the key, and says what to do."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fake_gemini import FakeModel, good, good_answer, service_for, unavailable

from app.core.config import Settings
from app.llm.gemini import ModelService

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_gemini.py'
KEY = 'AIzaSyTestKeyForTheScriptOnly0123456789'
SETTINGS = Settings(gemini_api_key=KEY, gemini_model='fake-gemini')


@pytest.fixture(scope='module')
def check():
    spec = importlib.util.spec_from_file_location('check_gemini', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def keep_the_copy_in_a_temporary_folder(check, tmp_path, monkeypatch):
    """The check saves a text copy of what it prints; a test must never write into the real ..\\debug folder."""
    monkeypatch.setattr(check, 'DEBUG', tmp_path / 'debug')


def result_line(out: str) -> str:
    """The line that says how the check ended (the text-copy note comes after it)."""
    return [line for line in out.splitlines() if line.startswith('RESULT:')][-1]


def flat(text: str) -> str:
    """The text with every run of spaces and line breaks made one space: the script wraps long sentences at 100 columns."""
    return ' '.join(text.split())


def well(prompt):
    """A model that answers the tiny request, the report and the chat the way a well-behaved one would."""
    return {'reply': 'ready'} if 'reply field' in prompt else good(prompt)


def run(check, capsys, respond=well, argv=(), settings=SETTINGS, services=None):
    """Runs the check against a fake model. Returns (exit code, everything it printed, the model)."""
    model = FakeModel(respond)

    def make(_settings):
        service = service_for(model)
        if services is not None:
            services.append(service)
        return service

    code = check.main(list(argv), settings=settings, make_service=make, sleep=lambda seconds: None)
    return code, capsys.readouterr().out, model


# ------------------------------------------------------------------ a good run


def test_a_working_gemini_passes_all_four_steps(check, capsys):
    code, out, model = run(check, capsys)
    assert code == 0 and result_line(out) == 'RESULT: PASS'
    for step in ('[1/4] Settings', '[2/4] Connection', '[3/4] Report', '[4/4] Chat'):
        assert step in out
    assert 'Gemini wrote 20 of 20 passages' in out
    assert 'Chat answers by Gemini: 5 of 5' in out
    assert model.calls == 7  # one tiny request, one report, five chat answers: the three off-limits questions cost nothing


def test_the_key_is_never_printed_and_the_settings_say_only_present(check, capsys):
    code, out, _ = run(check, capsys)
    assert code == 0 and KEY not in out and 'AIza' not in out
    assert 'GEMINI_API_KEY .... present' in out


def test_it_says_what_is_and_is_not_sent_to_google(check, capsys):
    _, out, model = run(check, capsys)
    assert 'Never photos, names or contact details' in out and 'may use what it receives to improve its products' in out
    # the made-up hands are shown as the words that are sent
    assert '"heart":{"status"' in out
    sent = ' '.join(r.prompt for r in model.requests)
    assert 'rd_check' not in sent and 'Check' not in sent.split('READING')[0] and 'prf_check' not in sent


def test_the_boundary_questions_are_shown_as_turned_away_without_asking_gemini(check, capsys):
    _, out, _ = run(check, capsys)
    for question, boundary in (('Will I get married?', 'relationship'), ('How long will I live?', 'lifespan'), ('Should I quit my job?', 'employment')):
        assert f'OK   "{question}"  -> boundary: {boundary}, Gemini asked: no' in out


def test_by_default_it_shows_four_passages_and_with_full_it_shows_all(check, capsys):
    _, short, _ = run(check, capsys)
    assert '(16 more passages: run with --full to see them all)' in short
    _, full, _ = run(check, capsys, argv=['--full'])
    assert 'more passages' not in full and 'theme_future:' in full and 'shape_right:' in full


def test_quick_stops_after_the_first_tiny_request(check, capsys):
    code, out, model = run(check, capsys, argv=['--quick'])
    assert code == 0 and 'RESULT: PASS (quick check)' in out and '[3/4]' not in out and model.calls == 1


def test_a_model_and_a_thinking_level_can_be_tried_without_editing_the_file(check, capsys):
    seen = []

    def make(settings):
        seen.append((settings.gemini_model, settings.gemini_thinking))
        return service_for(FakeModel(well))

    code = check.main(['--quick', '--model', ' gemini-other ', '--thinking', 'low'], settings=SETTINGS, make_service=make, sleep=lambda s: None)
    assert code == 0 and seen == [('gemini-other', 'low')]
    assert 'model ............. gemini-other' in capsys.readouterr().out


# ------------------------------------------------------------------ the key is missing or wrong


def test_without_a_key_it_says_how_to_get_one_and_makes_no_request(check, capsys):
    made = []
    code = check.main([], settings=Settings(), make_service=lambda s: made.append(s) or service_for(FakeModel(well)), sleep=lambda s: None)
    out = capsys.readouterr().out
    assert code == 1 and made == [] and 'GEMINI_API_KEY .... MISSING' in out and 'RESULT: FAIL (no key)' in out
    assert 'https://aistudio.google.com/apikey' in out and 'Do NOT turn on billing' in out and 'backend\\.env' in out


@pytest.mark.parametrize(
    ('key', 'complaint'),
    [
        ('AIzaSy abc', 'a space'),
        ('"AIzaSyabc', 'a quote mark'),
        ('AIzaSyabc’', 'a curly quote'),
        ('GEMINI_API_KEY=AIzaSyabc', 'repeats the name'),
        ('your-key', 'placeholder'),
    ],
)
def test_a_key_pasted_the_wrong_way_is_called_out_without_showing_it(check, capsys, key, complaint):
    check.main(['--quick'], settings=SETTINGS.with_(gemini_api_key=key), make_service=lambda s: service_for(FakeModel(well)), sleep=lambda s: None)
    out = capsys.readouterr().out
    assert 'WARNING: the key looks wrong' in out and complaint in out and key not in out


def test_a_rejected_key_stops_the_check_with_advice_and_no_key_in_the_message(check, capsys):
    def refuse(prompt):
        return unavailable('bad_key', f'API key not valid: {KEY}. Please pass a valid API key.')

    code, out, model = run(check, capsys, respond=refuse)
    assert code == 1 and 'RESULT: FAIL (connection: bad_key)' in out
    assert KEY not in out and '[key]' in out
    assert 'the whole key, no quotes, no spaces' in flat(out) and '[3/4]' not in out and model.calls == 1


def test_an_unknown_model_lists_the_models_that_exist(check, capsys, monkeypatch):
    monkeypatch.setattr(check, 'fetch_model_names', lambda key: ['gemini-2.5-flash', 'gemini-3.5-flash'])
    code, out, _ = run(check, capsys, respond=lambda p: unavailable('bad_model', 'models/nope is not found'))
    assert code == 1 and 'RESULT: FAIL (connection: bad_model)' in out
    assert 'The models this key may use (2):' in out and '  gemini-3.5-flash' in out and 'GEMINI_MODEL=' in out


def test_a_busy_spell_on_the_first_request_is_repeated_once_like_in_the_app(check, capsys):
    answers = iter([unavailable('overloaded', 'This model is currently experiencing high demand.')])

    def respond(prompt):
        failure = next(answers, None) if 'reply field' in prompt else None
        return failure if failure is not None else well(prompt)

    code, out, model = run(check, capsys, respond=respond)
    assert code == 0 and 'OK: Google accepted the key and the model' in out and model.calls == 8
    assert 'Requests made to Gemini: 8 (1 of them repeated because Google was busy).' in out


def test_two_busy_answers_in_a_row_stop_the_check_and_say_to_try_again_later(check, capsys):
    code, out, model = run(check, capsys, respond=lambda p: unavailable('overloaded', 'This model is currently experiencing high demand.'))
    assert code == 1 and 'RESULT: FAIL (connection: overloaded)' in out and model.calls == 2
    assert 'in a few minutes' in flat(out) and 'Gemini is very busy right now' in out


@pytest.mark.parametrize(
    ('kind', 'words'),
    [
        ('rate_limited', 'run.bat gemini --probe'),
        ('overloaded', 'very busy right now'),
        ('region', 'do not turn on billing'),
        ('bad_request', 'Google refused the request itself'),
        ('timeout', 'internet connection'),
        ('cut_off', '--thinking LOW'),
    ],
)
def test_each_kind_of_failure_gets_advice_that_fits_it(check, capsys, kind, words):
    code, out, _ = run(check, capsys, respond=lambda p: unavailable(kind, 'what Google said'))
    assert code == 1 and f'[{kind}]' in out and words in flat(out) and 'Google said: what Google said' in flat(out)


# ------------------------------------------------------------------ Gemini works but its words are not all used


def test_passages_the_checks_refuse_are_listed_with_the_reason_and_the_check_still_passes(check, capsys):
    def mixed(prompt):
        out = well(prompt)
        if 'reply field' not in prompt and not prompt.startswith('READING'):
            out['heart_left'] = 'In traditional palmistry this heart line means you will meet someone special next year.'
        return out

    code, out, _ = run(check, capsys, respond=mixed)
    assert code == 0 and 'Gemini wrote 19 of 20 passages' in out
    assert 'These keep the fixed wording, and why' in out and 'heart_left:' in out
    assert 'Gemini wrote 19 of 20 passages. The other 1 did not pass a safety check' in flat(out)


def test_a_gemini_whose_every_passage_is_refused_fails_the_check(check, capsys):
    def predicts(prompt):
        if 'reply field' in prompt or prompt.startswith('READING'):
            return well(prompt)
        return {key: 'You will become rich next year.' for key in good_answer(prompt)}

    code, out, _ = run(check, capsys, respond=predicts)
    assert code == 1 and 'PROBLEM: Gemini wrote no report passage that passed the checks' in out and result_line(out) == 'RESULT: FAIL'


def test_a_chat_that_mostly_falls_back_fails_the_check_and_says_why(check, capsys):
    def no_chat(prompt):
        return unavailable('timeout', 'slow') if prompt.startswith('READING') else well(prompt)

    code, out, _ = run(check, capsys, respond=no_chat)
    assert code == 1 and 'PROBLEM: Gemini wrote only 0 of 5 chat answers' in out
    assert 'the KNOWLEDGE BASE wrote this' in out
    assert 'Why not Gemini: Gemini was not used for this answer because Gemini took too long to answer' in flat(out)


def test_a_pause_that_google_asks_for_is_waited_out_not_counted_as_a_failure(check, capsys):
    waits = []
    answers = iter([unavailable('rate_limited', 'Quota exceeded', 20.0)])

    def respond(prompt):
        if prompt.startswith('READING'):
            nxt = next(answers, None)
            if nxt is not None:
                return nxt
        return well(prompt)

    model = FakeModel(respond)
    clock = [1000.0]

    def make(_settings):
        return ModelService(model, clock=lambda: clock[0])

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    code = check.main([], settings=SETTINGS, make_service=make, sleep=sleep)
    out = capsys.readouterr().out
    assert waits == [21.0] and 'Gemini asked for a pause: waiting 20 s' in out  # once, before the second question
    assert 'Chat answers by Gemini: 4 of 5' in out  # the first fell back to the knowledge base; the other four went through
    assert 'Why not Gemini: Gemini was not used for this answer because Gemini’s free allowance is used up for now' in flat(out)
    assert code == 0


# ------------------------------------------------------------------ the text copy


def test_a_text_copy_of_everything_printed_is_saved_where_it_can_be_read(check, capsys, tmp_path):
    code, out, _ = run(check, capsys, argv=['--full'])
    saved = tmp_path / 'debug' / 'check_gemini.txt'
    assert code == 0 and saved.is_file()
    text = saved.read_text(encoding='utf-8')
    assert f'A text copy of this is saved in {saved}' in out
    # all of it: every question with who wrote the answer, every passage, and how it ended
    assert text.startswith('\nKiro AI: checking Gemini') and text.rstrip().endswith('RESULT: PASS')
    for question in check.QUESTIONS:
        assert question in text
    assert 'GEMINI wrote this' in text and 'shape_right:' in text and 'Requests made to Gemini: 7.' in text
    assert KEY not in text and 'AIza' not in text and 'A text copy of this is saved' not in text


def test_the_copy_says_which_chat_answer_did_not_come_from_gemini_and_why(check, capsys, tmp_path):
    def fifth_is_refused(prompt):
        if prompt.startswith('READING') and 'long life line means a long life' in prompt:
            return {'intent': 'answer', 'answer': 'Yes, a long life line means you will live a long life.', 'lines': ['life'], 'side': 'none', 'section': 'none'}
        return well(prompt)

    code, _, _ = run(check, capsys, respond=fifth_is_refused)
    text = (tmp_path / 'debug' / 'check_gemini.txt').read_text(encoding='utf-8')
    assert code == 0 and 'Chat answers by Gemini: 4 of 5' in text
    question = text.split('Q5: ')[1]
    assert question.startswith('I read that a long life line means a long life')
    assert 'the KNOWLEDGE BASE wrote this' in question and 'Why not Gemini:' in question


def test_a_failed_check_is_saved_too_and_the_next_run_replaces_it(check, capsys, tmp_path):
    saved = tmp_path / 'debug' / 'check_gemini.txt'
    code, _, _ = run(check, capsys, respond=lambda p: unavailable('bad_key', f'API key not valid: {KEY}'))
    first = saved.read_text(encoding='utf-8')
    assert code == 1 and first.rstrip().endswith('RESULT: FAIL (connection: bad_key)') and KEY not in first
    code, _, _ = run(check, capsys, argv=['--quick'])
    second = saved.read_text(encoding='utf-8')
    assert code == 0 and second.count('RESULT:') == 1 and second.rstrip().endswith('RESULT: PASS (quick check)')  # not both runs in one file


def test_the_copy_can_be_kept_in_another_folder(check, capsys, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    code, out, _ = run(check, capsys, argv=['--quick', '--out', str(elsewhere)])
    assert code == 0 and (elsewhere / 'check_gemini.txt').is_file() and not (tmp_path / 'debug').exists()
    assert str(elsewhere) in out


def test_a_folder_that_cannot_be_written_is_said_and_the_check_still_ends_properly(check, capsys, tmp_path):
    blocker = tmp_path / 'a-file-not-a-folder'
    blocker.write_text('x')
    code, out, _ = run(check, capsys, argv=['--quick', '--out', str(blocker)])
    assert code == 0 and 'A text copy could not be saved' in out and 'RESULT: PASS (quick check)' in out


# ------------------------------------------------------------------ the other options


def test_probe_tries_each_model_and_says_which_work(check, capsys, monkeypatch):
    monkeypatch.setattr(check, 'fetch_model_names', lambda key: ['gemini-2.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.5-pro', 'gemini-3.5-flash'])
    tried = []

    def make(settings):
        tried.append(settings.gemini_model)

        def respond(prompt):
            if settings.gemini_model == 'gemini-3.5-flash':
                return unavailable('rate_limited', 'Quota exceeded: limit: 0')
            return {'reply': 'ready'}

        return service_for(FakeModel(respond))

    code = check.main(['--probe'], settings=SETTINGS.with_(gemini_model='gemini-3.5-flash-lite'), make_service=make, sleep=lambda s: None)
    out = capsys.readouterr().out
    assert code == 0 and tried[0] == 'gemini-3.5-flash-lite' and 'gemini-3.5-pro' not in tried  # Flash and Flash-Lite models only
    assert 'works     gemini-3.5-flash-lite' in out and 'rate_limited gemini-3.5-flash   Quota exceeded: limit: 0' in out
    assert 'Models that work for your key: gemini-3.5-flash-lite, gemini-2.5-flash' in out


def test_probe_with_no_working_model_fails(check, capsys, monkeypatch):
    monkeypatch.setattr(check, 'fetch_model_names', lambda key: [])
    code = check.main(['--probe'], settings=SETTINGS, make_service=lambda s: service_for(FakeModel(lambda p: unavailable('bad_key', 'no'))), sleep=lambda s: None)
    assert code == 1 and 'No model answered' in capsys.readouterr().out


def test_list_models_lists_and_stops(check, capsys, monkeypatch):
    monkeypatch.setattr(check, 'fetch_model_names', lambda key: ['gemini-a', 'gemini-b'])
    made = []
    code = check.main(['--list-models'], settings=SETTINGS, make_service=lambda s: made.append(1), sleep=lambda s: None)
    out = capsys.readouterr().out
    assert code == 0 and 'gemini-a' in out and 'gemini-b' in out and not made and '[2/4]' not in out


def test_the_models_worth_probing_start_with_the_chosen_one_and_prefer_stable_names(check):
    names = ['gemini-3.5-flash-preview-0901', 'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-3.5-flash-lite', 'gemini-3.5-pro', 'gemini-3.5-flash']
    assert check.candidates(names, 'gemini-2.5-flash') == [
        'gemini-2.5-flash',
        'gemini-2.5-flash-lite',
        'gemini-3.5-flash-lite',
        'gemini-3.5-flash',
        'gemini-3.5-flash-preview-0901',
    ]
    assert check.candidates([], 'x')[0] == 'x' and 'gemini-2.5-flash' in check.candidates([], 'x')
