"""Several Gemini models behind one key (app/llm/gemini.py): when Google says one model is "experiencing high demand", or its free
allowance is used up, the next model is tried at once, and the one that failed is left alone for a while. No test here reaches the
network: the models are fakes and the clock is a variable."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.config import GEMINI_FALLBACK_MODELS, Settings, read_settings
from app.llm import gemini
from app.llm.gemini import (
    BACKOFF_CAP,
    BACKOFF_FIRST,
    BUSY_CAP,
    BUSY_FIRST,
    TRY_CAP,
    Answer,
    Failover,
    GeminiModel,
    ModelService,
    ModelUnavailable,
    build_service,
    models_in,
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


class Member:
    """A model that does what it is told: each reply is the text to return, or the failure to raise (the last one repeats)."""

    def __init__(self, name, *replies, clock=None, takes=0.0):
        self.name = name
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.clock, self.takes = clock, takes

    def generate(self, system, prompt, schema, **options):
        self.calls.append(options)
        if self.clock:
            self.clock.wait(self.takes)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, BaseException):
            raise reply
        return reply


def chain(*members, clock=None):
    clock = clock or Clock()
    return Failover(list(members), clock=clock), clock


def generate(model, timeout_s=30.0):
    return model.generate('s', 'p', SCHEMA, temperature=0.2, max_tokens=100, timeout_s=timeout_s)


def rate_limited(wait=None):
    return ModelUnavailable('rate_limited', 'Quota exceeded', wait)


def busy():
    return ModelUnavailable('overloaded', 'This model is currently experiencing high demand.')


# ---------------------------------------------------------------- taking turns


def test_the_first_model_that_can_answer_does_and_the_answer_knows_which_one_wrote_it():
    first, second = Member('gemini-a', '{"a": "1"}'), Member('gemini-b', '{"a": "2"}')
    failover, _ = chain(first, second)
    text = generate(failover)
    assert text == '{"a": "1"}' and isinstance(text, Answer) and text.model == 'gemini-a' and not second.calls


def test_a_model_that_is_busy_hands_over_to_the_next_at_once():
    first, second = Member('gemini-a', busy()), Member('gemini-b', '{"a": "2"}')
    failover, _ = chain(first, second)
    text = generate(failover)
    assert text == '{"a": "2"}' and text.model == 'gemini-b' and failover.handovers == 1


def test_a_model_that_cannot_answer_is_left_alone_while_it_rests_and_asked_again_after():
    first = Member('gemini-a', rate_limited(10.0))
    second = Member('gemini-b', '{"a": "2"}')
    failover, clock = chain(first, second)
    assert generate(failover).model == 'gemini-b'
    clock.wait(5)
    assert generate(failover).model == 'gemini-b' and len(first.calls) == 1  # still resting: not asked
    assert 4 < failover.resting(first) <= 5
    clock.wait(6)
    generate(failover)
    assert len(first.calls) == 2  # its rest is over: it is asked again first


def test_a_model_that_answers_again_after_its_rest_is_first_choice_again():
    first = Member('gemini-a', rate_limited(10.0), '{"a": "1"}')
    second = Member('gemini-b', '{"a": "2"}')
    failover, clock = chain(first, second)
    assert generate(failover) == '{"a": "2"}'
    clock.wait(11)
    assert generate(failover) == '{"a": "1"}' and failover.resting(first) == 0
    assert generate(failover) == '{"a": "1"}'  # and the rest and the growth are forgotten


def test_a_failure_of_one_answer_is_handed_over_but_does_not_make_the_model_rest():
    first = Member('gemini-a', ModelUnavailable('cut_off', 'too long'))
    second = Member('gemini-b', '{"a": "2"}')
    failover, _ = chain(first, second)
    generate(failover)
    generate(failover)
    assert len(first.calls) == 2 and len(second.calls) == 2  # asked first every time: the next question may suit it


def test_a_busy_spell_is_a_short_rest_that_grows_while_it_goes_on_and_other_failures_rest_longer():
    flaky = Member('gemini-a', busy())
    slow = Member('gemini-s', ModelUnavailable('timeout', 'slow'))
    stuck = Member('gemini-x', ModelUnavailable('bad_model', 'no such model'))
    other = Member('gemini-b', '{"a": "ok"}')
    failover, clock = chain(flaky, slow, stuck, other)
    generate(failover)
    assert BUSY_FIRST - 1 < failover.resting(flaky) <= BUSY_FIRST  # busy: a few seconds, because it is usually over by then
    assert BACKOFF_FIRST - 1 < failover.resting(slow) <= BACKOFF_FIRST
    assert failover.resting(stuck) == BACKOFF_CAP  # trying again will not help until somebody changes the setting
    clock.wait(BUSY_FIRST + 1)
    generate(failover)
    assert 2 * BUSY_FIRST - 1 < failover.resting(flaky) <= 2 * BUSY_FIRST  # the second busy answer in a row: twice as long
    for _ in range(10):
        clock.wait(BACKOFF_CAP + 1)
        generate(failover)
    assert failover.resting(flaky) <= BACKOFF_CAP


def test_when_every_model_fails_the_busy_spell_is_what_is_raised_and_the_soonest_rest_is_the_wait():
    first = Member('gemini-a', rate_limited(20.0))
    second = Member('gemini-b', busy())
    failover, clock = chain(first, second)
    with pytest.raises(ModelUnavailable) as caught:
        generate(failover)
    failure = caught.value
    assert failure.kind == 'overloaded'  # a busy spell passes, and a used-up allowance of one model says nothing about the others
    assert 'gemini-a rate_limited' in failure.detail and 'gemini-b overloaded' in failure.detail  # what each one said
    assert failure.tried == (('gemini-a', 'rate_limited'), ('gemini-b', 'overloaded'))
    assert failure.retry_after == BUSY_FIRST  # the second model's rest ends first
    with pytest.raises(ModelUnavailable) as resting:  # asked again at once: nobody is called
        generate(failover)
    assert resting.value.kind == 'overloaded' and 0 < resting.value.retry_after <= BUSY_FIRST
    assert len(first.calls) == 1 and len(second.calls) == 1
    clock.wait(BUSY_FIRST + 1)
    with pytest.raises(ModelUnavailable):
        generate(failover)
    assert len(second.calls) == 2 and len(first.calls) == 1  # the one whose rest was over was tried; the other still rests


def test_a_model_that_raises_an_ordinary_error_is_one_more_failure_not_a_crash():
    first = Member('gemini-a', RuntimeError('socket closed'))
    second = Member('gemini-b', '{"a": "ok"}')
    failover, _ = chain(first, second)
    assert generate(failover) == '{"a": "ok"}' and failover.resting(first) > 0


def test_a_plain_text_answer_is_given_the_name_of_the_model_that_wrote_it():
    failover, _ = chain(Member('gemini-a', '{"a": "x"}'), Member('gemini-b', '{"a": "y"}'))
    assert generate(failover).model == 'gemini-a'


def test_the_chain_is_named_after_its_first_model_and_lists_them_all():
    failover, _ = chain(Member('gemini-a', ''), Member('gemini-b', ''))
    assert failover.name == 'gemini-a' and failover.names == ['gemini-a', 'gemini-b']
    with pytest.raises(ValueError):
        Failover([])


# ---------------------------------------------------------------- the time allowed


def test_a_model_that_may_be_followed_by_another_does_not_use_up_all_the_time():
    first, second, last = Member('gemini-a', busy()), Member('gemini-b', busy()), Member('gemini-c', '{"a": "ok"}')
    failover, _ = chain(first, second, last)
    assert generate(failover, timeout_s=60.0) == '{"a": "ok"}'
    assert first.calls[0]['timeout_s'] == pytest.approx(36.0) and second.calls[0]['timeout_s'] == pytest.approx(36.0)
    assert last.calls[0]['timeout_s'] == pytest.approx(60.0)  # nobody comes after the last one: it may use all that is left


def test_a_model_that_hangs_leaves_time_for_the_next_and_a_model_with_no_time_left_is_not_started():
    clock = Clock()
    slow = Member('gemini-a', ModelUnavailable('timeout', 'slow'), clock=clock, takes=25.0)
    next_ = Member('gemini-b', '{"a": "ok"}')
    failover, _ = chain(slow, next_, clock=clock)
    assert generate(failover, timeout_s=60.0) == '{"a": "ok"}' and next_.calls[0]['timeout_s'] == pytest.approx(35.0)
    # and when the first one used the time up, the others get no try
    clock2 = Clock()
    slow2 = Member('gemini-a', ModelUnavailable('timeout', 'slow'), clock=clock2, takes=29.0)
    other = Member('gemini-b', '{"a": "late"}')
    failover2, _ = chain(slow2, other, clock=clock2)
    with pytest.raises(ModelUnavailable) as caught:
        generate(failover2, timeout_s=30.0)
    assert caught.value.kind == 'timeout' and not other.calls


def test_a_model_that_is_resting_does_not_take_a_share_of_the_time():
    first, second = Member('gemini-a', '{"a": "ok"}'), Member('gemini-b', '{"a": "other"}')
    failover, clock = chain(first, second)
    failover._resting_until[id(second)] = clock() + 10  # the second one failed a moment ago
    failover._last[id(second)] = busy()
    generate(failover, timeout_s=60.0)
    assert first.calls[0]['timeout_s'] == pytest.approx(60.0) and not second.calls  # nobody could take over: all the time


# ---------------------------------------------------------------- the service around them


def waiting_service(*replies, **options):
    naps: list[float] = []
    model = Member('gemini-a', *replies)
    return model, ModelService(model, clock=Clock(), sleep=naps.append, retry_wait=4.0, **options), naps


def test_the_service_hands_back_which_model_wrote_the_answer_and_remembers_it():
    model = Member('gemini-3.5-flash-lite', '{"a": "x"}')
    service = ModelService(model, clock=Clock())
    first = service.call(system='s', prompt='p', schema=SCHEMA, cache=True)
    again = service.call(system='s', prompt='p', schema=SCHEMA, cache=True)
    assert len(model.calls) == 1 and service.cache_hits == 1
    for answer in (first, again):
        assert isinstance(answer, Answer) and answer.model == 'gemini-3.5-flash-lite' and json.loads(answer) == {'a': 'x'}
    assert service.name == 'gemini-3.5-flash-lite'


def test_a_model_that_sends_back_plain_text_is_the_services_own_model():
    plain = SimpleNamespace(name='gemini-test', generate=lambda *a, **k: '{"a": "x"}')
    answer = ModelService(plain, clock=Clock()).call(system='s', prompt='p', schema=SCHEMA)
    assert answer.model == 'gemini-test'


def test_the_second_model_answers_a_report_without_the_service_resting_or_repeating():
    first, second = Member('gemini-a', busy()), Member('gemini-b', '{"a": "from b"}')
    failover, clock = chain(first, second)
    naps: list[float] = []
    service = ModelService(failover, clock=clock, sleep=naps.append, retry_wait=4.0)
    answer = service.call(system='s', prompt='p', schema=SCHEMA, retries=2)
    assert json.loads(answer) == {'a': 'from b'} and answer.model == 'gemini-b'
    assert naps == [] and service.repeats == 0 and service.resting_for() == 0 and service.last_failure is None


def test_when_every_model_is_busy_the_report_waits_a_few_seconds_and_tries_them_all_again():
    first, second = Member('gemini-a', busy(), '{"a": "later"}'), Member('gemini-b', busy())
    failover, clock = chain(first, second)
    service = ModelService(failover, clock=clock, sleep=clock.wait, retry_wait=4.0)
    answer = service.call(system='s', prompt='p', schema=SCHEMA, retries=2)
    assert answer.model == 'gemini-a' and len(first.calls) == 2 and len(second.calls) == 1  # b rested: a answered the repeat first
    assert service.repeats == 1 and service.resting_for() == 0


def test_a_report_repeats_up_to_the_number_asked_with_a_longer_wait_each_time_and_then_the_service_rests():
    first, second = Member('gemini-a', busy()), Member('gemini-b', busy())
    failover, clock = chain(first, second)
    naps: list[float] = []

    def sleep(seconds):
        naps.append(seconds)
        clock.wait(seconds)

    service = ModelService(failover, clock=clock, sleep=sleep, retry_wait=4.0)
    with pytest.raises(ModelUnavailable) as caught:
        service.call(system='s', prompt='p', schema=SCHEMA, retries=2, timeout_s=60.0)
    assert caught.value.kind == 'overloaded' and naps == [4.0, 8.0] and service.repeats == 2
    assert len(first.calls) == 3 and len(second.calls) == 3
    assert service.resting_for() > 0  # one failure counted, once: everything else is refused for now
    with pytest.raises(ModelUnavailable):
        service.call(system='s', prompt='p', schema=SCHEMA, retries=2)
    assert len(first.calls) == 3


def test_the_repeats_stay_inside_the_time_the_caller_allows():
    model, service, naps = waiting_service(busy())
    with pytest.raises(ModelUnavailable):
        service.call(system='s', prompt='p', schema=SCHEMA, retries=3, timeout_s=5.0)  # 4 s of waiting and 3 s to try do not fit in 5 s
    assert naps == [] and len(model.calls) == 1


def test_a_rate_limit_that_is_over_in_a_few_seconds_is_waited_out_once_when_the_call_may_repeat():
    model, service, naps = waiting_service(rate_limited(3.0), '{"a": "back"}')
    assert json.loads(service.call(system='s', prompt='p', schema=SCHEMA, retries=1)) == {'a': 'back'}
    assert naps == [3.5] and len(model.calls) == 2 and service.repeats == 1 and service.resting_for() == 0


@pytest.mark.parametrize(('failure', 'retries'), [(rate_limited(30.0), 1), (rate_limited(None), 1), (rate_limited(3.0), 0)])
def test_a_long_or_unknown_wait_is_not_waited_out_and_neither_is_one_when_the_call_may_not_repeat(failure, retries):
    model, service, naps = waiting_service(failure)
    with pytest.raises(ModelUnavailable):
        service.call(system='s', prompt='p', schema=SCHEMA, retries=retries)
    assert naps == [] and len(model.calls) == 1 and service.resting_for() > 0


def test_a_test_that_removed_the_usual_wait_removes_this_one_too():
    naps: list[float] = []
    model = Member('gemini-a', rate_limited(3.0), '{"a": "back"}')
    service = ModelService(model, clock=Clock(), sleep=naps.append, retry_wait=0.0)
    service.call(system='s', prompt='p', schema=SCHEMA, retries=1)
    assert naps == [0.0] and len(model.calls) == 2


# ---------------------------------------------------------------- building the chain


def models(service):
    model = service.model
    return model.names if isinstance(model, Failover) else [model.name]


def test_model_names_are_split_at_commas_semicolons_and_spaces_and_none_is_used_twice():
    assert models_in('a, b  c;d,,a') == ['a', 'b', 'c', 'd']
    assert models_in('  ') == [] and models_in('one') == ['one']


def test_no_key_means_no_model_one_name_means_that_model_and_several_mean_a_chain():
    assert build_service('', 'gemini-a').model is None and build_service('  ', ['gemini-a', 'gemini-b']).model is None
    one = build_service(KEY, 'gemini-a')
    assert isinstance(one.model, GeminiModel) and one.name == 'gemini-a'
    several = build_service(KEY, 'gemini-a, gemini-b gemini-a', thinking='low', per_minute=5, timeout_s=30)
    assert isinstance(several.model, Failover) and models(several) == ['gemini-a', 'gemini-b'] and several.name == 'gemini-a'
    assert all(isinstance(m, GeminiModel) and m._thinking == 'LOW' for m in several.model.members)
    assert (several.per_minute, several.timeout_s) == (5, 30)
    assert models(build_service(KEY, ['x', 'y', 'x'])) == ['x', 'y']
    assert build_service(KEY, '').model is None  # no name at all: nothing to ask


def test_the_settings_name_your_model_first_and_then_the_fallbacks_without_repeating_any():
    assert Settings().gemini_models == ['gemini-3.5-flash-lite', *GEMINI_FALLBACK_MODELS.split(',')]
    assert Settings(gemini_model='gemini-3.8-flash').gemini_models[0] == 'gemini-3.8-flash'
    assert Settings(gemini_model='a, b', gemini_fallback='b, c').gemini_models == ['a', 'b', 'c']
    assert Settings(gemini_model='a', gemini_fallback='none').gemini_models == ['a']
    assert Settings(gemini_model='a', gemini_fallback=' Off ').gemini_models == ['a']
    assert Settings(gemini_model=GEMINI_FALLBACK_MODELS.split(',')[0]).gemini_models == GEMINI_FALLBACK_MODELS.split(',')


def test_the_service_for_the_settings_takes_the_models_in_that_order(monkeypatch):
    settings = Settings(gemini_api_key=KEY, gemini_model='gemini-x', gemini_fallback='gemini-y', gemini_per_minute=3, gemini_cache=0,
                        gemini_timeout_s=20, gemini_chat_limit=2, gemini_thinking='minimal')
    service = gemini.service_from_settings(settings)
    assert models(service) == ['gemini-x', 'gemini-y']
    assert (service.per_minute, service.cache_size, service.timeout_s, service.chat_limit) == (3, 0, 20.0, 2)
    assert KEY not in repr(settings)  # printing the settings never shows the key
    assert not gemini.service_from_settings(Settings()).available


def test_the_environment_names_the_models(monkeypatch, tmp_path):
    monkeypatch.setattr('app.core.config.BACKEND_DIR', tmp_path)  # no .env file here
    monkeypatch.setenv('GEMINI_MODEL', ' gemini-x ,gemini-z')
    monkeypatch.setenv('GEMINI_FALLBACK_MODELS', 'gemini-y')
    settings = read_settings()
    assert settings.gemini_model == 'gemini-x ,gemini-z' and settings.gemini_models == ['gemini-x', 'gemini-z', 'gemini-y']
    monkeypatch.setenv('GEMINI_FALLBACK_MODELS', '')
    monkeypatch.setenv('GEMINI_MODEL', '')
    assert read_settings().gemini_models == Settings().gemini_models  # nothing set: the defaults


# ---------------------------------------------------------------- thinking is sent only where it is understood


class FakeClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[object] = []
        self.contents: list[object] = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append(config)
        self.contents.append(contents)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class ApiError(Exception):
    def __init__(self, code, status='', message=''):
        super().__init__(f'{code} {status}. {message}')
        self.code, self.status, self.message, self.details = code, status, message, None


GOOD = SimpleNamespace(candidates=[SimpleNamespace(finish_reason='STOP')], prompt_feedback=None, text='{"a":"x"}')


def run(model, client):
    model._client = client
    return model.generate('s', 'p', SCHEMA, temperature=0.2, max_tokens=50, timeout_s=5)


def test_a_thinking_level_is_sent_to_the_models_that_understand_it_and_not_to_the_older_ones():
    pytest.importorskip('google.genai')
    for name, sent in (('gemini-3.5-flash-lite', True), ('gemini-3.8-flash', True), ('gemini-2.5-flash', False), ('gemini-2.5-flash-lite', False)):
        client = FakeClient(GOOD)
        run(GeminiModel(KEY, name, thinking='minimal'), client)
        assert (client.calls[0].thinking_config is not None) is sent, name


def test_a_model_that_refuses_the_thinking_level_is_asked_again_without_it_and_never_sent_it_again():
    pytest.importorskip('google.genai')
    refusal = ApiError(400, 'INVALID_ARGUMENT', 'Thinking level MINIMAL is not supported by this model')
    model = GeminiModel(KEY, 'gemini-3.8-flash', thinking='minimal')
    client = FakeClient(refusal, GOOD)
    assert run(model, client) == '{"a":"x"}'
    assert [c.thinking_config is not None for c in client.calls] == [True, False]
    client2 = FakeClient(GOOD)
    run(model, client2)
    assert client2.calls[0].thinking_config is None  # remembered


def test_a_refusal_that_is_not_about_thinking_is_not_asked_again():
    pytest.importorskip('google.genai')
    model = GeminiModel(KEY, 'gemini-3.8-flash', thinking='minimal')
    client = FakeClient(ApiError(400, 'INVALID_ARGUMENT', 'Unknown name "foo" at generation_config'), GOOD)
    with pytest.raises(ModelUnavailable) as caught:
        run(model, client)
    assert caught.value.kind == 'bad_request' and len(client.calls) == 1 and model._takes_thinking


# ---------------------------------------------------------------- more patience: Google's busy spells come and go


def test_a_busy_model_rests_only_as_long_as_a_busy_spell_lasts():
    flaky, other = Member('gemini-a', busy()), Member('gemini-b', '{"a": "ok"}')
    failover, clock = chain(flaky, other)
    for _ in range(8):
        clock.wait(BUSY_CAP + 1)
        generate(failover)
        assert failover.resting(flaky) <= BUSY_CAP  # a rest that grew to minutes would make every pass go by without asking it
    assert len(flaky.calls) == 8


def test_a_model_is_never_given_more_than_the_cap_however_much_time_is_left():
    first, last = Member('gemini-a', busy()), Member('gemini-b', '{"a": "ok"}')
    failover, _ = chain(first, last)
    generate(failover, timeout_s=400.0)
    assert first.calls[0]['timeout_s'] == TRY_CAP and last.calls[0]['timeout_s'] == TRY_CAP


def test_models_that_do_not_exist_do_not_hide_that_the_others_are_only_busy():
    gone = Member('gemini-old', ModelUnavailable('bad_model', 'models/gemini-old is not found'))
    failover, _ = chain(gone, Member('gemini-a', busy()), Member('gemini-b', busy()))
    with pytest.raises(ModelUnavailable) as caught:
        generate(failover)
    assert caught.value.kind == 'overloaded'  # worth waiting out: the service repeats it, and does not rest for minutes
    assert caught.value.tried == (('gemini-old', 'bad_model'), ('gemini-a', 'overloaded'), ('gemini-b', 'overloaded'))
    assert 0 < caught.value.retry_after <= BUSY_FIRST  # the busy ones are asked again soon, whatever the missing one's rest
    nothing, _ = chain(Member('gemini-x', ModelUnavailable('bad_model', 'no')), Member('gemini-y', ModelUnavailable('bad_model', 'no')))
    with pytest.raises(ModelUnavailable) as none_left:
        generate(nothing)
    assert none_left.value.kind == 'bad_model'  # when none of them exist, that is what is said


def test_the_report_keeps_asking_with_longer_waits_and_gets_its_answer_when_google_recovers():
    first = Member('gemini-a', *[busy()] * 5, '{"a": "at last"}')
    second = Member('gemini-b', busy())
    failover, clock = chain(first, second)
    naps: list[float] = []

    def sleep(seconds):
        naps.append(seconds)
        clock.wait(seconds)

    service = ModelService(failover, clock=clock, sleep=sleep, retry_wait=4.0)
    answer = service.call(system='s', prompt='p', schema=SCHEMA, retries=8, timeout_s=150.0)
    assert json.loads(answer) == {'a': 'at last'} and answer.model == 'gemini-a'
    assert naps == [4.0, 8.0, 12.0, 16.0, 20.0] and service.repeats == 5
    assert service.last_failure is None and service.resting_for() == 0  # a repeat that works leaves no trace
    assert len(second.calls) == 5  # and each time the other model had its turn as well


def test_the_waits_between_repeats_stop_growing_at_the_cap():
    first, second = Member('gemini-a', busy()), Member('gemini-b', busy())
    failover, clock = chain(first, second)
    naps: list[float] = []

    def sleep(seconds):
        naps.append(seconds)
        clock.wait(seconds)

    service = ModelService(failover, clock=clock, sleep=sleep, retry_wait=4.0)
    with pytest.raises(ModelUnavailable):
        service.call(system='s', prompt='p', schema=SCHEMA, retries=8, timeout_s=400.0)
    assert naps == [4.0, 8.0, 12.0, 16.0, 20.0, 20.0, 20.0, 20.0]


def test_a_busy_spell_that_never_ends_is_given_up_at_the_time_limit_and_the_service_rests_only_briefly():
    first, second = Member('gemini-a', busy()), Member('gemini-b', busy())
    failover, clock = chain(first, second)
    service = ModelService(failover, clock=clock, sleep=clock.wait, retry_wait=4.0)
    started = clock()
    with pytest.raises(ModelUnavailable) as caught:
        service.call(system='s', prompt='p', schema=SCHEMA, retries=100, timeout_s=60.0)
    assert caught.value.kind == 'overloaded' and clock() - started <= 60.0
    assert service.repeats == 4  # waits of 4, 8, 12 and 16 seconds fit; a fifth of 20 does not
    assert 0 < service.resting_for() <= BUSY_CAP  # the next request, a moment later, is not turned away for a quarter of an hour


def test_the_log_says_what_google_said_when_a_model_does_not_exist_and_not_the_busy_message_that_is_always_the_same(caplog):
    gone = Member('gemini-old', ModelUnavailable('bad_model', f'models/gemini-old is not found for API version v1beta {KEY}'))
    failover, _ = chain(gone, Member('gemini-a', busy()), Member('gemini-b', '{"a": "ok"}'))
    with caplog.at_level('WARNING', logger='kiro.llm'):
        generate(failover)
    assert 'gemini-old could not answer (bad_model: models/gemini-old is not found for API version v1beta [key]); trying the next one' in caplog.text
    assert 'gemini-a could not answer (overloaded); trying the next one' in caplog.text and 'high demand' not in caplog.text
    assert KEY not in caplog.text


def test_a_failure_with_nothing_to_say_is_logged_without_an_empty_explanation(caplog):
    failover, _ = chain(Member('gemini-a', ModelUnavailable('timeout')), Member('gemini-b', '{"a": "ok"}'))
    with caplog.at_level('WARNING', logger='kiro.llm'):
        generate(failover)
    assert 'gemini-a could not answer (timeout); trying the next one' in caplog.text


def test_the_last_log_line_of_a_failed_report_lists_what_each_model_said(caplog):
    failover, clock = chain(Member('gemini-a', busy()), Member('gemini-b', ModelUnavailable('bad_model', 'no')))
    service = ModelService(failover, clock=clock, sleep=clock.wait)
    with caplog.at_level('WARNING', logger='kiro.llm'), pytest.raises(ModelUnavailable):
        service.call(system='s', prompt='p', schema=SCHEMA)
    assert 'model call failed (overloaded): gemini-a overloaded, gemini-b bad_model' in caplog.text


# ---------------------------------------------------------------- the models the key has


def named(name):
    return Member(name, '{"a": "x"}')


def test_models_the_key_does_not_have_are_dropped_and_a_few_more_flash_models_are_added():
    members = [named('gemini-a'), named('gemini-gone'), named('gemma-4-x')]
    offered = [
        'gemini-a', 'gemma-4-x', 'gemini-9-flash', 'gemini-9-flash-lite', 'gemini-9-flash-preview', 'gemini-9-pro',
        'gemini-flash-latest', 'gemini-9-flash-image', 'gemma-3-27b-it', 'gemma-4-12b-it', 'gemini-embedding-001',
    ]
    fitted = gemini.fit_to_key(members, offered, named)
    # the asked-for models that exist, in order; then stable before preview and Flash-Lite before Flash; no Pro (slow, and little or no free allowance), no
    # alias of another model, nothing that makes pictures or embeddings, and no Gemma before the fourth (they take no JSON schema)
    assert [m.name for m in fitted] == ['gemini-a', 'gemma-4-x', 'gemini-9-flash-lite', 'gemini-9-flash', 'gemma-4-12b-it']
    assert fitted[0] is members[0]  # the models that were kept are the same ones: what they remember is not lost


def test_nothing_changes_when_the_list_is_empty_and_the_keys_own_models_replace_a_list_that_has_none_of_the_asked_ones():
    members = [named('gemini-a'), named('gemini-b')]
    assert gemini.fit_to_key(members, [], named) == members
    assert gemini.fit_to_key(members, ['something-else'], named, extras=0) == members  # nothing to put in their place: they are tried as they are
    assert [m.name for m in gemini.fit_to_key(members, ['gemini-9-flash'], named)] == ['gemini-9-flash']


def test_no_more_models_are_added_when_none_are_wanted_but_the_missing_ones_are_still_dropped():
    fitted = gemini.fit_to_key([named('gemini-a'), named('gemini-gone')], ['gemini-a', 'gemini-9-flash'], named, extras=0)
    assert [m.name for m in fitted] == ['gemini-a']


def test_the_models_are_fitted_to_the_key_once_before_the_first_request():
    first, gone = named('gemini-a'), Member('gemini-gone', ModelUnavailable('bad_model', 'no'))
    asked: list[list[str]] = []

    def adjust(current):
        asked.append([m.name for m in current])
        return [m for m in current if m.name != 'gemini-gone']

    failover = Failover([gone, first], clock=Clock(), adjust=adjust)
    assert not failover.adjusted
    assert generate(failover).model == 'gemini-a'
    assert not gone.calls  # never asked: Google does not list it for this key
    assert failover.adjusted and failover.names == ['gemini-a'] and failover.name == 'gemini-a'
    generate(failover)
    assert asked == [['gemini-gone', 'gemini-a']]  # once


def test_when_the_list_cannot_be_fetched_the_models_are_used_as_they_are_and_it_is_asked_for_again_later():
    clock = Clock()
    asked: list[float] = []

    def adjust(current):
        asked.append(clock())

    member = named('gemini-a')
    failover = Failover([member], clock=clock, adjust=adjust)
    generate(failover)
    generate(failover)
    assert len(asked) == 1 and not failover.adjusted and len(member.calls) == 2  # the answers did not wait for it
    clock.wait(gemini.LIST_RETRY + 1)
    generate(failover)
    assert len(asked) == 2


def test_a_check_that_raises_is_the_same_as_one_that_found_nothing_out(caplog):
    def adjust(current):
        raise RuntimeError(f'boom {KEY}')

    failover = Failover([named('gemini-a')], clock=Clock(), adjust=adjust)
    with caplog.at_level('WARNING', logger='kiro.llm'):
        assert generate(failover) == '{"a": "x"}'
    assert not failover.adjusted and 'could not be checked against the key' in caplog.text and KEY not in caplog.text


def test_a_failover_with_no_check_counts_as_fitted_already():
    assert Failover([named('gemini-a')]).adjusted


def test_building_the_service_with_discovery_fits_the_models_to_the_key_before_the_first_question(monkeypatch):
    monkeypatch.setattr(gemini, 'offered_models', lambda key, **kw: ['gemini-a', 'gemini-9-flash'])
    service = build_service(KEY, ['gemini-a', 'gemini-gone'], discover=3)
    assert isinstance(service.model, Failover) and not service.model.adjusted and models(service) == ['gemini-a', 'gemini-gone']
    service.model.fit()
    assert models(service) == ['gemini-a', 'gemini-9-flash'] and service.model.adjusted
    assert all(isinstance(m, GeminiModel) for m in service.model.members)
    assert build_service(KEY, ['gemini-a', 'gemini-gone']).model.adjusted  # no list was asked for: there is nothing to wait for
    assert isinstance(build_service(KEY, 'gemini-a', discover=3).model, GeminiModel)  # one model, as asked: nothing takes over


def test_a_list_google_refuses_is_logged_without_the_key_and_the_models_are_asked_as_they_are(monkeypatch, caplog):
    def refuse(key, **kw):
        raise ModelUnavailable('bad_key', f'API key not valid: {KEY}')

    monkeypatch.setattr(gemini, 'offered_models', refuse)
    service = build_service(KEY, ['gemini-a', 'gemini-b'], discover=3)
    with caplog.at_level('WARNING', logger='kiro.llm'):
        service.model.fit()
    assert models(service) == ['gemini-a', 'gemini-b'] and not service.model.adjusted
    assert 'could not get the list of Gemini models' in caplog.text and KEY not in caplog.text


def test_the_service_for_the_settings_asks_for_the_list_only_when_the_settings_say_so():
    assert gemini.service_from_settings(Settings(gemini_api_key=KEY)).model.adjusted  # a plain Settings(): nothing asks Google anything
    assert not gemini.service_from_settings(Settings(gemini_api_key=KEY, gemini_discover=True)).model.adjusted
    assert isinstance(gemini.service_from_settings(Settings(gemini_api_key=KEY, gemini_discover=True, gemini_fallback='none')).model, GeminiModel)


def test_the_environment_switches_the_list_off_and_the_default_patience_is_two_and_a_half_minutes(monkeypatch, tmp_path):
    assert Settings().gemini_discover_extras is None
    assert Settings(gemini_discover=True).gemini_discover_extras == gemini.EXTRA_MODELS
    assert Settings(gemini_discover=True, gemini_fallback='none').gemini_discover_extras == 0  # "none" means only the model asked for
    monkeypatch.setattr('app.core.config.BACKEND_DIR', tmp_path)  # no .env file here
    monkeypatch.delenv('GEMINI_DISCOVER', raising=False)
    monkeypatch.delenv('GEMINI_TIMEOUT_SECONDS', raising=False)
    settings = read_settings()
    assert settings.gemini_discover and settings.gemini_timeout_s == 150 == Settings().gemini_timeout_s
    for value in ('0', 'off', 'No', 'false'):
        monkeypatch.setenv('GEMINI_DISCOVER', value)
        assert not read_settings().gemini_discover, value
    monkeypatch.setenv('GEMINI_DISCOVER', 'yes')
    assert read_settings().gemini_discover


def test_the_default_models_are_ones_the_key_was_not_refused_and_gemma_4_is_served_by_the_same_api():
    assert GEMINI_FALLBACK_MODELS.split(',') == ['gemini-3.1-flash-lite', 'gemma-4-31b-it', 'gemma-4-26b-a4b-it']
    assert not any(name.startswith('gemini-2') for name in GEMINI_FALLBACK_MODELS.split(','))  # a key was told that these do not exist


class Api:
    closed = False


class LazyList:
    """What Google's library does: the list is fetched page by page as it is read, by an object that the client closes when it closes."""

    def __init__(self, api, items):
        self.api, self.items = api, items

    def list(self):
        def pages():
            for item in self.items:
                if self.api.closed:
                    raise RuntimeError('Cannot send a request, as the client has been closed.')
                yield item

        return pages()


class ClosingClient:
    """Like the library's client: it closes itself when nothing refers to it any more, and so does the list it hands out."""

    def __init__(self, api_key, http_options=None, items=()):
        self.api_key, self.http_options = api_key, http_options
        self._api = Api()
        self.models = LazyList(self._api, items)

    def close(self):
        self._api.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()


def test_the_list_of_models_keeps_those_that_write_text_and_drops_the_models_prefix(monkeypatch):
    genai = pytest.importorskip('google.genai')
    items = [
        SimpleNamespace(name='models/gemini-3.5-flash-lite', supported_actions=['generateContent', 'countTokens']),
        SimpleNamespace(name='models/gemma-4-31b-it', supported_actions=['generateContent']),
        SimpleNamespace(name='models/gemini-embedding-001', supported_actions=['embedContent']),
        SimpleNamespace(name='models/gemini-3.5-flash-tts', supported_actions=['generateContent']),
        SimpleNamespace(name='models/text-bison-001', supported_actions=['generateContent']),
        SimpleNamespace(name='models/gemini-2.0-no-actions-listed', supported_actions=None),
    ]
    made = []

    def client(api_key, http_options=None):
        made.append(ClosingClient(api_key, http_options, items))
        return made[-1]

    monkeypatch.setattr(genai, 'Client', client)
    # the list is read while the client is open: a client that was let go of first would have closed it (the library does that)
    assert gemini.offered_models(KEY) == ['gemini-2.0-no-actions-listed', 'gemini-3.5-flash-lite', 'gemma-4-31b-it']
    assert made[0].api_key == KEY and made[0].http_options.timeout == 10_000  # a quick request: it must not hold up the first answer for long
    assert made[0]._api.closed  # and it is closed when done


def test_a_list_that_google_refuses_is_one_model_unavailable_without_the_key(monkeypatch):
    genai = pytest.importorskip('google.genai')

    class Refusing(ClosingClient):
        def __init__(self, api_key, http_options=None):
            super().__init__(api_key, http_options)
            self.models = SimpleNamespace(list=self.refuse)

        def refuse(self):
            raise ApiError(403, 'PERMISSION_DENIED', f'API key not valid. {KEY}')

    monkeypatch.setattr(genai, 'Client', Refusing)
    with pytest.raises(ModelUnavailable) as caught:
        gemini.offered_models(KEY)
    assert caught.value.kind == 'bad_key' and KEY not in caught.value.detail


# ---------------------------------------------------------------- a model that takes no JSON schema is asked in plain text


def test_a_model_that_refuses_a_json_schema_is_asked_again_in_plain_text_and_afterwards_asked_that_way_at_once():
    pytest.importorskip('google.genai')
    refusal = ApiError(400, 'INVALID_ARGUMENT', 'JSON mode is not enabled for models/gemma-4-31b-it')
    model = GeminiModel(KEY, 'gemma-4-31b-it')
    client = FakeClient(refusal, GOOD)
    assert run(model, client) == '{"a":"x"}'
    first, second = client.calls
    assert first.response_mime_type == 'application/json' and first.system_instruction == 's' and first.response_json_schema == SCHEMA
    assert second.response_mime_type is None and second.system_instruction is None and second.response_json_schema is None
    assert client.contents[0] == 'p'
    assert client.contents[1].startswith('s\n\np\n\n') and '"type": "object"' in client.contents[1] and 'no code fence' in client.contents[1]
    assert model._plain
    again = FakeClient(GOOD)
    run(model, again)
    assert len(again.calls) == 1 and again.calls[0].response_mime_type is None and 'JSON schema' in again.contents[0]


def test_a_refusal_about_separate_instructions_is_answered_with_plain_text_too():
    pytest.importorskip('google.genai')
    model = GeminiModel(KEY, 'gemma-4-31b-it')
    client = FakeClient(ApiError(400, 'INVALID_ARGUMENT', 'Developer instruction is not enabled for models/gemma-4-31b-it'), GOOD)
    assert run(model, client) == '{"a":"x"}' and model._plain and len(client.calls) == 2


def test_plain_text_is_tried_once_and_when_that_is_refused_too_the_refusal_is_raised_and_nothing_is_remembered():
    pytest.importorskip('google.genai')
    model = GeminiModel(KEY, 'gemma-4-31b-it')
    client = FakeClient(ApiError(400, 'INVALID_ARGUMENT', 'JSON mode is not enabled'), ApiError(400, 'INVALID_ARGUMENT', 'The prompt is too long'))
    with pytest.raises(ModelUnavailable) as caught:
        run(model, client)
    assert caught.value.kind == 'bad_request' and len(client.calls) == 2 and not model._plain


def test_a_model_that_refuses_the_thinking_level_and_then_the_schema_has_both_taken_away():
    pytest.importorskip('google.genai')
    model = GeminiModel(KEY, 'gemma-4-31b-it', thinking='minimal')
    client = FakeClient(
        ApiError(400, 'INVALID_ARGUMENT', 'Thinking level MINIMAL is not supported'),
        ApiError(400, 'INVALID_ARGUMENT', 'JSON mode is not enabled'),
        GOOD,
    )
    assert run(model, client) == '{"a":"x"}'
    assert [(c.thinking_config is not None, c.response_mime_type is not None) for c in client.calls] == [(True, True), (False, True), (False, False)]


def test_a_busy_answer_is_not_asked_again_in_plain_text():
    pytest.importorskip('google.genai')
    model = GeminiModel(KEY, 'gemma-4-31b-it')
    client = FakeClient(ApiError(503, 'UNAVAILABLE', 'This model is currently experiencing high demand. Try the JSON again later.'))
    with pytest.raises(ModelUnavailable) as caught:
        run(model, client)
    assert caught.value.kind == 'overloaded' and len(client.calls) == 1 and not model._plain


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('{"a": "x"}', '{"a": "x"}'),
        ('  {"a": "x"}\n', '{"a": "x"}'),
        ('```json\n{"a": "x"}\n```', '{"a": "x"}'),
        ('```\n{"a": "x"}\n```', '{"a": "x"}'),
        ('Here is the JSON you asked for:\n```json\n{"a": "x"}\n```\nI hope it helps.', '{"a": "x"}'),
        ('Sure! {"a": {"b": "x"}} Done.', '{"a": {"b": "x"}}'),
        ('no braces at all', 'no braces at all'),
    ],
)
def test_the_json_is_found_in_an_answer_that_has_a_fence_or_a_sentence_around_it(text, expected):
    assert gemini.unwrap_json(text) == expected
