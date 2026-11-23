"""The care a free key needs (app/llm/gemini.py): calls counted per minute, a pause after a failure that grows when the failure
repeats, identical requests answered from memory, every error turned into one `ModelUnavailable`, and the key never in a message.
No test here, or anywhere, reaches the network: the model is a fake and the clock is a variable."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fake_gemini import FakeModel

from app.llm import gemini
from app.llm.gemini import (
    BACKOFF_CAP,
    BACKOFF_FIRST,
    BUSY_FIRST,
    GeminiModel,
    ModelService,
    ModelUnavailable,
    build_service,
    classify,
    redact,
    retry_seconds,
    text_of,
)

SCHEMA = {'type': 'object', 'properties': {'a': {'type': 'string'}}, 'required': ['a']}
KEY = 'AIzaSyD-this-is-not-a-real-key-0123456789'


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds


class ApiError(Exception):
    """What google-genai raises: an error with a code, a status, a message and details."""

    def __init__(self, code, status='', message='', details=None):
        super().__init__(f'{code} {status}. {message}')
        self.code, self.status, self.message, self.details = code, status, message, details


def ask(service, prompt='hello', **options):
    return service.call(system='s', prompt=prompt, schema=SCHEMA, **options)


def service_with(respond, clock=None, **options):
    model = FakeModel(respond)
    return model, ModelService(model, clock=clock or Clock(), **options)


# ---------------------------------------------------------------- no key, and the plain case


def test_without_a_model_every_call_says_so_at_once():
    service = ModelService(None)
    assert not service.available and service.name is None
    with pytest.raises(ModelUnavailable) as caught:
        ask(service)
    assert caught.value.kind == 'no_key' and 'no key' in caught.value.reason


def test_a_call_goes_to_the_model_with_what_was_asked():
    model, service = service_with(lambda prompt: {'a': 'hi'})
    assert json.loads(ask(service, 'the question', temperature=0.1, max_tokens=99, timeout_s=7)) == {'a': 'hi'}
    sent = model.requests[0]
    assert (sent.system, sent.prompt, sent.schema, sent.temperature, sent.max_tokens, sent.timeout_s) == ('s', 'the question', SCHEMA, 0.1, 99, 7)
    assert service.available and service.name == 'fake-gemini' and service.calls == 1


# ---------------------------------------------------------------- the per-minute share


def test_only_so_many_calls_are_made_in_a_minute():
    clock = Clock()
    model, service = service_with(lambda p: {'a': 'x'}, clock, per_minute=3)
    for _ in range(3):
        ask(service)
        clock.wait(10)
    with pytest.raises(ModelUnavailable) as caught:
        ask(service)
    assert caught.value.kind == 'busy' and 29 < caught.value.retry_after <= 31  # the first call leaves the minute in 30 seconds
    assert model.calls == 3  # the refused call never reached the model
    clock.wait(31)
    ask(service)
    assert model.calls == 4


# ---------------------------------------------------------------- resting after a failure


def test_a_rate_limit_pauses_every_call_and_the_wait_grows_when_it_repeats():
    clock = Clock()
    model, service = service_with(lambda p: ApiError(429, 'RESOURCE_EXHAUSTED', 'Quota exceeded'), clock)
    with pytest.raises(ModelUnavailable) as first:
        ask(service)
    assert first.value.kind == 'rate_limited' and model.calls == 1
    assert BACKOFF_FIRST - 1 < service.resting_for() <= BACKOFF_FIRST
    with pytest.raises(ModelUnavailable) as resting:  # asked again at once: refused without calling the model
        ask(service)
    assert resting.value.kind == 'rate_limited' and resting.value.retry_after > 0 and model.calls == 1
    clock.wait(BACKOFF_FIRST + 1)
    with pytest.raises(ModelUnavailable):
        ask(service)
    assert model.calls == 2 and 2 * BACKOFF_FIRST - 1 < service.resting_for() <= 2 * BACKOFF_FIRST  # twice as long this time
    for _ in range(10):
        clock.wait(BACKOFF_CAP + 1)
        with pytest.raises(ModelUnavailable):
            ask(service)
    assert service.resting_for() <= BACKOFF_CAP


def test_the_wait_google_asks_for_is_honoured():
    clock = Clock()
    details = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '34s'}]}}
    _, service = service_with(lambda p: ApiError(429, 'RESOURCE_EXHAUSTED', 'Quota exceeded', details), clock)
    with pytest.raises(ModelUnavailable):
        ask(service)
    assert 33 < service.resting_for() <= 34


def test_a_success_ends_the_rest_and_resets_the_growth():
    clock = Clock()
    answers = [ApiError(503, 'UNAVAILABLE', 'overloaded'), {'a': 'ok'}, ApiError(503, 'UNAVAILABLE', 'overloaded')]
    _, service = service_with(lambda p: answers.pop(0), clock)
    with pytest.raises(ModelUnavailable):
        ask(service)
    clock.wait(BACKOFF_FIRST + 1)
    assert json.loads(ask(service)) == {'a': 'ok'} and service.last_failure is None
    with pytest.raises(ModelUnavailable):
        ask(service)
    assert service.resting_for() <= BACKOFF_FIRST  # the growth started again from the beginning


def test_a_bad_key_or_a_bad_model_name_rests_for_the_longest_time():
    for error, kind in ((ApiError(400, 'INVALID_ARGUMENT', 'API key not valid. Please pass a valid API key.'), 'bad_key'), (ApiError(404, 'NOT_FOUND', 'models/x is not found'), 'bad_model')):
        _, service = service_with(lambda p, error=error: error, Clock())
        with pytest.raises(ModelUnavailable) as caught:
            ask(service)
        assert caught.value.kind == kind and service.resting_for() > BACKOFF_CAP - 1


def test_a_problem_with_one_answer_does_not_stop_the_next_call():
    clock = Clock()
    answers = ['', json.dumps({'a': 'fine'})]
    _, service = service_with(lambda p: answers.pop(0), clock)
    # an empty text is the model's, not the service's, so the service does not rest (text_of raises it in GeminiModel; a fake model returns it)
    assert ask(service) == ''
    assert json.loads(ask(service)) == {'a': 'fine'}


def test_a_model_that_raises_an_ordinary_error_is_treated_as_a_failure_of_the_service():
    _, service = service_with(lambda p: RuntimeError('socket closed'), Clock())
    with pytest.raises(ModelUnavailable) as caught:
        ask(service)
    assert caught.value.kind == 'error' and service.resting_for() > 0


# ---------------------------------------------------------------- repeating once when Google is busy

BUSY = ApiError(503, 'UNAVAILABLE', 'This model is currently experiencing high demand. Spikes in demand are usually temporary.')


def waiting_service(respond, clock=None, **options):
    """A service whose pauses are written down, not slept."""
    naps: list[float] = []
    model = FakeModel(respond)
    service = ModelService(model, clock=clock or Clock(), sleep=naps.append, retry_wait=4.0, **options)
    return model, service, naps


def test_a_busy_answer_is_repeated_once_when_the_call_allows_it():
    answers = [BUSY, {'a': 'second time lucky'}]
    model, service, naps = waiting_service(lambda p: answers.pop(0))
    assert json.loads(ask(service, retries=1)) == {'a': 'second time lucky'}
    assert model.calls == 2 and naps == [4.0] and service.repeats == 1
    # a repeat that works leaves no trace: no rest, nothing remembered as a failure, the growth is not started
    assert service.last_failure is None and service.resting_for() == 0
    assert service.calls == 2  # both requests count towards the minute's share


def test_a_call_does_not_repeat_unless_it_is_allowed_to():
    model, service, naps = waiting_service(lambda p: BUSY)
    with pytest.raises(ModelUnavailable) as caught:
        ask(service)
    assert caught.value.kind == 'overloaded' and model.calls == 1 and naps == [] and service.repeats == 0


def test_two_busy_answers_in_a_row_make_the_service_rest_once():
    model, service, naps = waiting_service(lambda p: BUSY)
    with pytest.raises(ModelUnavailable) as caught:
        ask(service, retries=1)
    assert caught.value.kind == 'overloaded' and caught.value.clause == 'Gemini is very busy right now'
    assert model.calls == 2 and naps == [4.0] and service.repeats == 1
    assert BUSY_FIRST - 1 < service.resting_for() <= BUSY_FIRST  # one failure counted, not two, and a busy spell is a short rest
    with pytest.raises(ModelUnavailable):
        ask(service, retries=1)  # resting: refused at once, and not repeated
    assert model.calls == 2


def test_a_failure_that_does_not_pass_by_itself_is_never_repeated():
    for error, kind in (
        (ApiError(429, 'RESOURCE_EXHAUSTED', 'Quota exceeded'), 'rate_limited'),
        (ApiError(504, 'DEADLINE_EXCEEDED', 'took too long'), 'timeout'),
        (ApiError(401, 'UNAUTHENTICATED', 'bad'), 'bad_key'),
        (ApiError(404, 'NOT_FOUND', 'models/x is not found'), 'bad_model'),
        (ApiError(400, 'INVALID_ARGUMENT', 'Invalid JSON payload'), 'bad_request'),
    ):
        model, service, naps = waiting_service(lambda p, error=error: error)
        with pytest.raises(ModelUnavailable) as caught:
            ask(service, retries=1)
        assert caught.value.kind == kind and model.calls == 1 and naps == [], kind


def test_a_connection_error_is_repeated_once_too():
    answers = [RuntimeError('socket closed'), {'a': 'back'}]
    model, service, naps = waiting_service(lambda p: answers.pop(0))
    assert json.loads(ask(service, retries=1)) == {'a': 'back'} and model.calls == 2 and naps == [4.0]


def test_the_repeat_counts_towards_the_minutes_share_and_is_refused_when_the_share_is_used():
    model, service, _naps = waiting_service(lambda p: BUSY, per_minute=1)
    with pytest.raises(ModelUnavailable) as caught:
        ask(service, retries=1)
    assert caught.value.kind == 'busy' and model.calls == 1 and service.repeats == 0


def test_the_wait_before_a_repeat_is_a_few_seconds_and_a_test_can_remove_it(monkeypatch):
    assert gemini.RETRY_WAIT == 0.0 and ModelService(None).retry_wait == 0.0  # the test setup (conftest) removed it
    monkeypatch.undo()
    assert 1.0 <= gemini.RETRY_WAIT <= 10.0  # the real value: long enough for a busy spell to pass, short enough to wait for
    assert ModelService(None).retry_wait == gemini.RETRY_WAIT
    assert ModelService(None, retry_wait=1.5).retry_wait == 1.5


# ---------------------------------------------------------------- remembering


def test_an_identical_request_is_answered_from_memory_when_asked_to_be():
    model, service = service_with(lambda p: {'a': 'x'}, cache_size=2)
    assert ask(service, 'one', cache=True) == ask(service, 'one', cache=True)
    assert model.calls == 1 and service.cache_hits == 1
    ask(service, 'one')  # not asked to use the memory: a new call
    assert model.calls == 2
    ask(service, 'two', cache=True)
    ask(service, 'three', cache=True)  # 'one' is the oldest of three and the memory holds two
    ask(service, 'one', cache=True)
    assert model.calls == 5


def test_the_memory_can_be_switched_off():
    model, service = service_with(lambda p: {'a': 'x'}, cache_size=0)
    ask(service, cache=True)
    ask(service, cache=True)
    assert model.calls == 2


def test_a_remembered_answer_does_not_use_up_the_minutes_share_or_wait_after_a_failure():
    clock = Clock()
    answers = [{'a': 'x'}, ApiError(429, 'RESOURCE_EXHAUSTED', 'Quota exceeded')]
    model, service = service_with(lambda p: answers.pop(0), clock, per_minute=2)
    ask(service, cache=True)
    assert ask(service, cache=True)  # remembered: no second call, so it does not count towards the minute's two
    with pytest.raises(ModelUnavailable):
        ask(service, 'other')
    assert ask(service, cache=True)  # even while resting, what is remembered is still answered
    assert model.calls == 2


def test_an_unusable_answer_is_not_remembered_and_does_not_make_the_service_rest():
    answers = ['not json', json.dumps({'a': 'ok'})]
    model, service = service_with(lambda p: answers.pop(0), Clock())

    def need_json(text):
        try:
            json.loads(text)
        except ValueError:
            raise ModelUnavailable('bad_output', 'not JSON') from None

    with pytest.raises(ModelUnavailable) as caught:
        ask(service, cache=True, validate=need_json)
    assert caught.value.kind == 'bad_output' and service.resting_for() == 0
    assert json.loads(ask(service, cache=True, validate=need_json)) == {'a': 'ok'} and model.calls == 2  # asked again, not served from memory


# ---------------------------------------------------------------- errors, and the key


@pytest.mark.parametrize(
    ('error', 'kind'),
    [
        (ApiError(429, 'RESOURCE_EXHAUSTED', 'Quota exceeded'), 'rate_limited'),
        (ApiError(401, 'UNAUTHENTICATED', 'bad'), 'bad_key'),
        (ApiError(403, 'PERMISSION_DENIED', 'no'), 'bad_key'),
        (ApiError(400, 'INVALID_ARGUMENT', 'API key not valid. Please pass a valid API key.'), 'bad_key'),
        (ApiError(404, 'NOT_FOUND', 'models/nope is not found'), 'bad_model'),
        (ApiError(400, 'FAILED_PRECONDITION', 'User location is not supported for the API use.'), 'region'),
        (ApiError(400, 'FAILED_PRECONDITION', 'Gemini API free tier is not available in your country. Please enable billing.'), 'region'),
        (ApiError(400, 'INVALID_ARGUMENT', 'Invalid JSON payload received. Unknown name "additionalProperties"'), 'bad_request'),
        (ApiError(400, '', 'something about the request'), 'bad_request'),
        (ApiError(504, 'DEADLINE_EXCEEDED', 'took too long'), 'timeout'),
        (TimeoutError('timed out'), 'timeout'),
        (ApiError(503, 'UNAVAILABLE', 'This model is currently experiencing high demand. Spikes in demand are usually temporary.'), 'overloaded'),
        (ApiError(500, 'INTERNAL', 'An internal error has occurred.'), 'error'),
        (ValueError('who knows'), 'error'),
    ],
)
def test_every_kind_of_failure_becomes_one_error_with_a_kind(error, kind):
    assert classify(error).kind == kind


def test_the_key_never_appears_in_an_error_or_a_log_line(caplog):
    error = ApiError(400, 'INVALID_ARGUMENT', f'API key not valid: {KEY}. Request to https://x/?key={KEY}')
    failure = classify(error, KEY)
    assert KEY not in failure.detail and KEY not in str(failure) and '[key]' in failure.detail
    assert KEY not in redact(f'before {KEY} after', KEY) and 'AIza' not in redact('AIzaSyabcdefghijklmnopqrstuvwxyz0123', '')
    model = FakeModel(lambda p: error)
    model._key = KEY  # type: ignore[attr-defined]
    service = ModelService(model, clock=Clock())
    with caplog.at_level('WARNING', logger='kiro.llm'), pytest.raises(ModelUnavailable):
        ask(service)
    assert KEY not in caplog.text


def test_the_wait_a_message_asks_for_is_read_from_its_words_too():
    assert retry_seconds(ApiError(429, 'RESOURCE_EXHAUSTED', 'Quota exceeded. Please retry in 12.25s.')) == 12.25
    assert retry_seconds(ApiError(429, 'RESOURCE_EXHAUSTED', 'nothing about time')) is None
    assert retry_seconds(ApiError(429, 'X', 'retry in 99999s')) == BACKOFF_CAP


# ---------------------------------------------------------------- reading a response


def response(text='{"a":"x"}', finish=None, block=None):
    candidates = [SimpleNamespace(finish_reason=finish)] if finish is not None else []
    return SimpleNamespace(candidates=candidates, prompt_feedback=SimpleNamespace(block_reason=block) if block else None, text=text)


@pytest.mark.parametrize(
    ('reply', 'kind'),
    [
        (response(finish='FinishReason.MAX_TOKENS'), 'cut_off'),
        (response(finish='FinishReason.SAFETY'), 'blocked'),
        (response(finish='PROHIBITED_CONTENT'), 'blocked'),
        (response(block='SAFETY'), 'blocked'),
        (response(text=''), 'empty'),
        (response(text='   '), 'empty'),
        (response(text=None), 'empty'),
    ],
)
def test_a_response_with_no_usable_text_says_why(reply, kind):
    with pytest.raises(ModelUnavailable) as caught:
        text_of(reply)
    assert caught.value.kind == kind


def test_a_response_with_text_gives_the_text():
    assert text_of(response(finish='FinishReason.STOP')) == '{"a":"x"}'
    assert text_of(response()) == '{"a":"x"}'


# ---------------------------------------------------------------- building it


def test_no_key_means_no_model_and_a_key_means_gemini_without_reaching_out():
    assert build_service('', 'gemini-3.5-flash-lite').model is None
    assert build_service('   ', 'gemini-3.5-flash-lite').model is None
    service = build_service(KEY, 'gemini-3.5-flash-lite', thinking='low', per_minute=5, cache_size=4, timeout_s=30, chat_limit=7)
    assert isinstance(service.model, GeminiModel) and service.name == 'gemini-3.5-flash-lite'
    assert (service.per_minute, service.cache_size, service.timeout_s, service.chat_limit) == (5, 4, 30, 7)
    assert service.model._client is None and service.model._thinking == 'LOW'  # the library is not loaded until the first call


def test_the_settings_make_the_service():
    from app.core.config import Settings

    settings = Settings(gemini_api_key=KEY, gemini_model='gemini-3.8-flash', gemini_per_minute=3, gemini_cache=0, gemini_timeout_s=20, gemini_chat_limit=2)
    service = gemini.service_from_settings(settings)
    assert service.name == 'gemini-3.8-flash' and service.per_minute == 3 and service.timeout_s == 20.0 and service.chat_limit == 2
    assert KEY not in repr(settings)  # printing the settings never shows the key
    assert not gemini.service_from_settings(Settings()).available


# ---------------------------------------------------------------- the real adapter, with a stand-in for Google's library


class FakeClient:
    """What `google.genai.Client` offers the adapter: `client.models.generate_content(model=, contents=, config=)`."""

    def __init__(self, reply):
        self.reply = reply
        self.calls: list[tuple] = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append((model, contents, config))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_the_real_adapter_asks_google_for_json_in_the_given_shape_and_never_retries_by_itself():
    pytest.importorskip('google.genai')
    model = GeminiModel(KEY, 'gemini-test', thinking=' low ')
    model._client = FakeClient(response('{"a":"x"}', finish='STOP'))
    assert model.generate('the system', 'the prompt', SCHEMA, temperature=0.3, max_tokens=123, timeout_s=7) == '{"a":"x"}'
    name, contents, config = model._client.calls[0]
    assert (name, contents) == ('gemini-test', 'the prompt')
    assert config.system_instruction == 'the system' and config.temperature == 0.3 and config.max_output_tokens == 123
    assert config.response_mime_type == 'application/json' and config.response_json_schema == SCHEMA
    assert config.http_options.timeout == 7000 and config.http_options.retry_options.attempts == 1  # the service decides when to try again
    assert config.thinking_config.thinking_level.value == 'LOW'


def test_the_real_adapter_leaves_thinking_alone_unless_asked():
    pytest.importorskip('google.genai')
    model = GeminiModel(KEY, 'gemini-test')
    model._client = FakeClient(response(finish='STOP'))
    model.generate('s', 'p', SCHEMA, temperature=0.2, max_tokens=50, timeout_s=5)
    assert model._client.calls[0][2].thinking_config is None


def test_the_real_adapter_turns_google_errors_into_one_error_without_the_key():
    pytest.importorskip('google.genai')
    for error, kind in [
        (ApiError(400, 'INVALID_ARGUMENT', f'API key not valid: {KEY}'), 'bad_key'),
        (ApiError(429, 'RESOURCE_EXHAUSTED', f'Quota exceeded for {KEY}. Please retry in 20s'), 'rate_limited'),
        (ApiError(400, 'INVALID_ARGUMENT', 'Unknown name "foo" at generation_config'), 'bad_request'),
    ]:
        model = GeminiModel(KEY, 'gemini-test')
        model._client = FakeClient(error)
        with pytest.raises(ModelUnavailable) as caught:
            model.generate('s', 'p', SCHEMA, temperature=0.2, max_tokens=50, timeout_s=5)
        assert caught.value.kind == kind and KEY not in str(caught.value) and KEY not in caught.value.detail


def test_the_real_adapter_says_when_google_answered_but_gave_nothing_usable():
    pytest.importorskip('google.genai')
    for reply, kind in [(response(text='', finish='STOP'), 'empty'), (response(finish='MAX_TOKENS'), 'cut_off'), (response(finish='SAFETY'), 'blocked')]:
        model = GeminiModel(KEY, 'gemini-test')
        model._client = FakeClient(reply)
        with pytest.raises(ModelUnavailable) as caught:
            model.generate('s', 'p', SCHEMA, temperature=0.2, max_tokens=50, timeout_s=5)
        assert caught.value.kind == kind


def test_tests_are_not_allowed_to_reach_google(never_reach_google):
    pytest.importorskip('google.genai')
    with pytest.raises(AssertionError, match='real Gemini client'):
        GeminiModel(KEY, 'gemini-test').client()
    never_reach_google.clear()  # this was the point of the test: tell the guard that nothing slipped through
