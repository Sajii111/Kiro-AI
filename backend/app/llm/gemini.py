"""Talking to Gemini: a small interface, the real implementation, and the care that keeps a free key from running out.

Three layers, so that each can be tested and explained on its own:

  TextModel      what the rest of the app needs from any language model: give it instructions, a question and a JSON
                 schema, get JSON text back. Tests plug in a fake one, so no test ever touches the network.
  GeminiModel    the real TextModel, using Google's `google-genai` library. It is imported only when a key is set, and it
                 turns every way a call can fail into one error, `ModelUnavailable`, with a reason.
  Failover       several Gemini models behind one, on the same key. Google's "high demand" and its free allowances are
                 per model, so when the first model is busy or used up the next one is tried at once, and the one that
                 failed is left alone for a while. The first time it is used it also asks Google which models the key
                 may use: a name that the key does not have is dropped (it would only cost a failed request on every
                 pass), and a few more Flash models from Google's own list are added at the end.
  ModelService   what the routes call. It adds the care a free key needs: calls are counted per minute, a rate-limit or
                 server error pauses all calls for a while (a longer pause each time it repeats), and an identical
                 request is answered from memory. A call that is allowed to (the report's) repeats, after a few seconds,
                 when Google says it is busy: Google's busy spells come and go in minutes, and a report is worth waiting
                 for. When it cannot answer it raises `ModelUnavailable`, and the caller writes the words from the
                 knowledge base instead. A reading and a chat always finish.

The key is read once from the environment (backend/.env). It is never logged, never put in an error message and never
sent anywhere except to Google in the request header.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger('kiro.llm')

#: how long to wait after a failure, in seconds: it doubles each time the failures go on, up to the cap
BACKOFF_FIRST = 15.0
BACKOFF_CAP = 300.0

#: how long a model that failed because Google was busy (or the connection dropped) is left alone the first time: such a spell is
#: usually over in seconds, so it is a short rest that doubles while the failures go on (any other failure waits BACKOFF_FIRST)
BUSY_FIRST = 3.0

#: the longest such a rest grows to. Google answers "high demand" within a second or two, so a model that was left alone for longer
#: than the waits between two tries would only make a try pass over it
BUSY_CAP = 10.0

#: how long a call that is allowed to repeat waits before it does (Google calls its busy spells "usually temporary"); each repeat
#: waits a little longer, up to RETRY_CAP
RETRY_WAIT = 4.0
RETRY_CAP = 20.0

#: how long a rate limit's own "try again in N seconds" is waited out inside a call that may repeat, instead of giving up on it
SHORT_WAIT = 12.0

#: when there is less than this many seconds left, another try is not started
MIN_TRY = 3.0

#: while another model could still take over, the model that is tried may use this share of the time that is left, so that one
#: that hangs does not use up the time the next one needs
TURN_SHARE = 0.6

#: the most one model may take to answer one request, whatever time is left: an answer for a report comes in 10 to 30 seconds, so a
#: model that has not answered by then is stuck, and the others should have their turn
TRY_CAP = 75.0

#: how many more Flash models from Google's list for the key are added after the ones that were asked for
EXTRA_MODELS = 3

#: after Google's list of models could not be fetched, how long until it is asked for again
LIST_RETRY = 60.0

#: parts of a model's name that say it is not for writing text (it makes speech, pictures, embeddings, live audio...)
NOT_FOR_TEXT = ('embedding', 'tts', 'image', 'live', 'audio', 'robotics', 'computer-use', 'aqa', 'imagen', 'veo', 'learnlm')

#: words in Google's refusal (an HTTP 400) that say the model does not take the way the question was put: a JSON schema, a JSON
#: answer, or instructions apart from the question (Gemma models said so). The question is then asked once more as plain text.
PLAIN_HINTS = ('json', 'schema', 'mime', 'instruction', 'structured', 'response')

#: what each kind of failure says to the person, finishing the sentence "Gemini was not used because <this>, so the app's own wording was used."
REASONS = {
    'no_key': 'Gemini is not set up on this computer (there is no key in backend/.env)',
    'rate_limited': 'Gemini’s free allowance is used up for now',
    'busy': 'Gemini was asked for too many answers in a minute',
    'overloaded': 'Gemini is very busy right now',
    'timeout': 'Gemini took too long to answer',
    'error': 'Gemini could not be reached',
    'bad_key': 'Gemini did not accept the key in backend/.env',
    'bad_model': 'Gemini does not know the model name in backend/.env',
    'bad_request': 'Gemini did not accept the request',
    'region': 'Gemini is not offered from this location without billing',
    'blocked': 'Gemini declined to answer',
    'cut_off': 'Gemini’s answer was cut off',
    'empty': 'Gemini gave an empty answer',
    'bad_output': 'Gemini’s answer was not in the form that was asked for',
    'chat_limit': 'this chat has used its share of Gemini answers',
}

#: failures that say the SERVICE is not usable right now (so every call waits), as opposed to one request going wrong
SERVICE_FAILURES = frozenset({'rate_limited', 'overloaded', 'timeout', 'error', 'bad_key', 'bad_model', 'region'})

#: failures that often pass within seconds, so a call that is allowed to repeat does once, before it gives up. A rate limit is
#: not one of them (Google says how long to wait, and the service waits), and neither is a timeout (a second one doubles the wait).
TRANSIENT = frozenset({'overloaded', 'error'})


class ModelUnavailable(Exception):
    """The model gave no usable answer this time. `kind` is why, as a word the callers can act on (see REASONS)."""

    def __init__(self, kind: str, detail: str = '', retry_after: float | None = None, tried: tuple[tuple[str, str], ...] = ()):
        super().__init__(f'{kind}: {detail}' if detail else kind)
        self.kind = kind
        self.detail = detail
        self.retry_after = retry_after
        #: when several models were asked: (model, what it said) for each, in the order they were asked
        self.tried = tried

    @property
    def reason(self) -> str:
        return REASONS.get(self.kind, 'Gemini could not answer')

    @property
    def clause(self) -> str:
        """The reason, to carry on a sentence ("... because <clause>"): "Gemini" keeps its capital letter, the rest do not."""
        text = self.reason
        return text if text.startswith('Gemini') else text[:1].lower() + text[1:]


class Answer(str):
    """The JSON text of an answer, which also knows which Gemini model wrote it (`model`). It is a plain string everywhere else, so
    nothing that only wants the text needs to know."""

    model: str

    def __new__(cls, text: str, model: str = ''):
        self = super().__new__(cls, text)
        self.model = model
        return self


class TextModel(Protocol):
    name: str

    def generate(self, system: str, prompt: str, schema: dict, *, temperature: float, max_tokens: int, timeout_s: float) -> str:
        """JSON text that follows `schema`. Raises ModelUnavailable."""
        ...


# ------------------------------------------------------------------ keeping the key out of every message

KEY_SHAPE = re.compile(r'AIza[0-9A-Za-z_\-]{20,}')


def redact(text: str, key: str = '', limit: int = 300) -> str:
    """Text that is safe to log or show: the key (and anything shaped like a Google API key) is replaced."""
    text = str(text)
    if key:
        text = text.replace(key, '[key]')
    return KEY_SHAPE.sub('[key]', text)[:limit]


def retry_seconds(exc: Exception) -> float | None:
    """How long Google asks us to wait, when its error says so: a "retryDelay": "34s" among the error's details, or the
    words "Please retry in 34.5s" in its message. Never more than the back-off cap."""
    details = getattr(exc, 'details', None)
    error = details.get('error', details) if isinstance(details, dict) else None
    for item in (error.get('details') or []) if isinstance(error, dict) else []:
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)s\s*', str(item.get('retryDelay', ''))) if isinstance(item, dict) else None
        if match:
            return min(float(match.group(1)), BACKOFF_CAP)
    match = re.search(r'retry in (\d+(?:\.\d+)?)\s*s', str(getattr(exc, 'message', '') or exc), re.IGNORECASE)
    return min(float(match.group(1)), BACKOFF_CAP) if match else None


def classify(exc: Exception, key: str = '') -> ModelUnavailable:
    """Turns any failure of a call into a ModelUnavailable with a kind, without ever carrying the key."""
    code = getattr(exc, 'code', None)
    status = str(getattr(exc, 'status', '') or '').upper()
    message = redact(getattr(exc, 'message', None) or exc, key)
    low = message.lower()
    if code == 429 or status == 'RESOURCE_EXHAUSTED':
        return ModelUnavailable('rate_limited', message, retry_seconds(exc))
    if code in (401, 403) or 'api key' in low or status in ('UNAUTHENTICATED', 'PERMISSION_DENIED'):
        return ModelUnavailable('bad_key', message)
    if code == 404 or status == 'NOT_FOUND':
        return ModelUnavailable('bad_model', message)
    if status == 'FAILED_PRECONDITION' or 'location is not supported' in low:
        return ModelUnavailable('region', message)  # "User location is not supported", or the free tier is closed in this country
    if code == 400 or status == 'INVALID_ARGUMENT':
        return ModelUnavailable('bad_request', message)  # reached Google, and Google refused what was asked (a schema or a setting)
    kind = type(exc).__name__.lower()
    if 'timeout' in kind or 'timed out' in low or code == 504:
        return ModelUnavailable('timeout', message)
    if code == 503 or status == 'UNAVAILABLE':
        return ModelUnavailable('overloaded', message)  # "This model is currently experiencing high demand": a busy spell, not a broken connection
    return ModelUnavailable('error', message or type(exc).__name__)


# ------------------------------------------------------------------ the real model


class GeminiModel:
    """Gemini through Google's `google-genai` library. One call, no hidden retries: the service decides when to wait."""

    def __init__(self, api_key: str, name: str, thinking: str = ''):
        self.name = name
        self._key = api_key
        #: the thinking level asked for (MINIMAL, LOW, ...), sent only to the models that understand it: the Gemini 3 ones. A
        #: model that refuses it anyway is asked again without it, and never sent it again.
        self._thinking = thinking.strip().upper()
        self._takes_thinking = not name.lower().startswith(('gemini-1', 'gemini-2'))
        #: True once this model has answered a plain-text question after refusing a JSON schema or separate instructions (the
        #: Gemma models are served by the same API, but did not always take them): it is then asked that way at once
        self._plain = False
        self._client = None

    def client(self):
        if self._client is None:
            # imported here: the library only matters once a key is set
            from google import genai

            self._client = genai.Client(api_key=self._key)
        return self._client

    def generate(self, system: str, prompt: str, schema: dict, *, temperature: float, max_tokens: int, timeout_s: float) -> str:
        from google.genai import types

        options = types.HttpOptions(timeout=int(timeout_s * 1000), retry_options=types.HttpRetryOptions(attempts=1))

        def config_for(thinking: bool, plain: bool):
            fields = {'temperature': temperature, 'max_output_tokens': max_tokens, 'http_options': options}
            if not plain:
                fields.update(system_instruction=system, response_mime_type='application/json', response_json_schema=schema)
            config = types.GenerateContentConfig(**fields)
            if thinking:
                config.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel(self._thinking))
            return config

        thinking = bool(self._thinking) and self._takes_thinking
        plain, fell_back = self._plain, False
        while True:
            contents = plain_prompt(system, prompt, schema) if plain else prompt
            try:
                response = self.client().models.generate_content(model=self.name, contents=contents, config=config_for(thinking, plain))
                text = text_of(response)
            except ModelUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - the library, the network, a timeout: all of them become one error, with the key removed
                refused = classify(exc, self._key)
                said = refused.detail.lower()
                if refused.kind == 'bad_request' and thinking and 'thinking' in said:
                    self._takes_thinking = False  # this model does not take that setting: ask again without it, now and from now on
                    thinking = False
                elif refused.kind == 'bad_request' and not plain and any(word in said for word in PLAIN_HINTS):
                    plain = fell_back = True  # it does not take a schema or separate instructions: put everything in the question
                else:
                    raise refused from None
                continue
            if fell_back:
                self._plain = True
                log.warning('Gemini model %s does not take a JSON schema or separate instructions; it is asked in plain text from now on', self.name)
            return text


def unwrap_json(text: str) -> str:
    """The JSON in a model's answer. A model that was asked for JSON in words, not through a schema, may put it in a code fence or
    say a sentence before it; this takes the fenced part, or else what lies between the first "{" and the last "}". Text with no
    braces is returned as it is (and fails to parse, as it should)."""
    body = text.strip()
    fenced = re.search(r'```(?:json)?\s*(.*?)\s*```', body, re.DOTALL | re.IGNORECASE)
    if fenced:
        body = fenced.group(1)
    if not body.startswith('{') and '{' in body and '}' in body:
        body = body[body.index('{') : body.rindex('}') + 1]
    return body


def plain_prompt(system: str, prompt: str, schema: dict) -> str:
    """The question for a model that takes no separate instructions and no JSON schema: everything goes in one text, and the
    answer is asked for as JSON in words."""
    return (
        f'{system}\n\n{prompt}\n\n'
        'Answer with one JSON object and nothing else: no explanation before or after it and no code fence. '
        f'It must follow this JSON schema:\n{json.dumps(schema, ensure_ascii=False)}'
    )


def text_of(response) -> str:
    """The JSON text of a response, or a ModelUnavailable saying why there is none."""
    candidates = getattr(response, 'candidates', None) or []
    reason = str(getattr(candidates[0], 'finish_reason', '') or '') if candidates else ''
    reason = reason.rsplit('.', 1)[-1].upper()
    if reason == 'MAX_TOKENS':
        raise ModelUnavailable('cut_off', 'the answer reached the length limit')
    if reason in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII', 'RECITATION', 'MODEL_ARMOR'):
        raise ModelUnavailable('blocked', reason.lower())
    feedback = getattr(response, 'prompt_feedback', None)
    if feedback is not None and getattr(feedback, 'block_reason', None):
        raise ModelUnavailable('blocked', str(feedback.block_reason))
    text = getattr(response, 'text', None)
    if not text or not str(text).strip():
        raise ModelUnavailable('empty', 'no text in the answer')
    return str(text)


# ------------------------------------------------------------------ several models behind one

#: failures that no amount of waiting will fix until a person changes something: their model rests for the longest time
STUCK = frozenset({'bad_key', 'bad_model', 'region'})


def models_in(text: str) -> list[str]:
    """"a, b  c" as ['a', 'b', 'c']: model names are separated by commas, semicolons or spaces, and none is used twice."""
    return list(dict.fromkeys(name for name in re.split(r'[,;\s]+', text.strip()) if name))


def offered_models(api_key: str, *, timeout_s: float = 10.0) -> list[str]:
    """The models Google lists for this key that can write text (Gemini and Gemma ones, names only, sorted). Raises
    ModelUnavailable when Google cannot be asked. It is one quick request, and it is not a request for an answer."""
    from google import genai
    from google.genai import types

    names: set[str] = set()
    try:
        options = types.HttpOptions(timeout=int(timeout_s * 1000), retry_options=types.HttpRetryOptions(attempts=1))
        # the client must stay referred to while the list is read: the library closes a client that nothing refers to any more, and the
        # list is fetched page by page as it is read (`genai.Client(...).models.list()` on its own fails with "the client has been closed")
        with genai.Client(api_key=api_key, http_options=options) as client:
            for model in client.models.list():
                name = str(getattr(model, 'name', '') or '').removeprefix('models/')
                actions = getattr(model, 'supported_actions', None)
                if name.startswith(('gemini', 'gemma')) and (not actions or 'generateContent' in actions) and not any(w in name for w in NOT_FOR_TEXT):
                    names.add(name)
    except Exception as exc:  # noqa: BLE001 - the library and the network raise many kinds of error; each becomes one, with the key removed
        raise classify(exc, api_key) from None
    return sorted(names)


def worth_adding(name: str) -> bool:
    """Whether a model from Google's list is one to add behind the models that were asked for: a Flash or Flash-Lite model (quick,
    and with a free allowance of its own), or a Gemma 4 model (served by the same API, and busy at other times than Gemini)."""
    low = name.lower()
    if any(word in low for word in NOT_FOR_TEXT) or '-latest' in low:  # an alias answers from the same place as the model it names
        return False
    if low.startswith('gemma-'):
        return low.startswith('gemma-4')  # the Gemma models before it take neither instructions nor a JSON schema
    return low.startswith('gemini-') and 'flash' in low


def fit_to_key(members: list[TextModel], offered: list[str], make: Callable[[str], TextModel], *, extras: int = EXTRA_MODELS) -> list[TextModel]:
    """The models to use, given the models Google lists for this key: those that were asked for and are on the list, in their
    order, then up to `extras` more from the list (stable before preview, Flash-Lite before Flash). A model that is not on the list is
    dropped, because every request to it would fail first. Nothing changes when the list is empty or none of the models fits."""
    if not offered:
        return list(members)
    listed = set(offered)
    kept = [m for m in members if m.name in listed]
    gone = [m.name for m in members if m.name not in listed]
    if gone:
        log.warning('Gemini models that this key cannot use, so they are not asked: %s', ', '.join(gone))
    asked = {m.name for m in members}

    def rank(name: str) -> tuple[bool, int, str]:
        return (any(word in name for word in ('preview', 'exp')), 0 if 'lite' in name else 1, name)

    added = sorted((n for n in offered if n not in asked and worth_adding(n)), key=rank)[: max(0, extras)]
    if added:
        log.info('Gemini models added from the list Google gives this key: %s', ', '.join(added))
    return [*kept, *(make(name) for name in added)] or list(members)


class Failover:
    """Gemini models that take turns: the first that can answer does. Google's "high demand" and its free allowances belong to
    each model separately, so a model that is busy or used up is skipped at once, and left alone for a while (as long as Google
    asks for, or longer each time it fails again), so one that is down does not slow down every request. When none can answer,
    the failures are raised as one, with what each model said in its detail.

    `adjust`, when given, is called once, the first time a request comes: it gets the models and returns the ones to use (see
    fit_to_key), or None when it could not find out (it is then called again later). It must not raise, but if it does, that
    is a failure to find out, nothing more."""

    def __init__(
        self,
        members: list[TextModel],
        *,
        clock: Callable[[], float] = time.monotonic,
        adjust: Callable[[list[TextModel]], list[TextModel] | None] | None = None,
    ):
        if not members:
            raise ValueError('a Failover needs at least one model')
        self.members = list(members)
        self.clock = clock
        self._lock = threading.Lock()
        self._resting_until: dict[int, float] = {}
        self._last: dict[int, ModelUnavailable] = {}
        self._streak: dict[int, int] = {}
        self._adjust = adjust
        self._adjust_lock = threading.Lock()
        self._adjust_after = 0.0
        #: True once the models were fitted to what Google says the key may use
        self.adjusted = adjust is None
        #: how many times a model could not answer and the next one was tried (for the check script and the tests)
        self.handovers = 0

    @property
    def name(self) -> str:
        """The model that is tried first."""
        return self.members[0].name

    @property
    def names(self) -> list[str]:
        return [member.name for member in self.members]

    def resting(self, member: TextModel) -> float:
        """Seconds until this model is tried again, 0 when it is not resting."""
        with self._lock:
            return max(0.0, self._resting_until.get(id(member), 0.0) - self.clock())

    def fit(self) -> None:
        """Fits the models to what Google lists for the key, once. Never raises, and is quick: one request for a list."""
        if self.adjusted:
            return
        with self._adjust_lock:  # the other requests wait for the first one's answer instead of asking again
            if self.adjusted or self.clock() < self._adjust_after:
                return
            try:
                fitted = self._adjust(list(self.members)) if self._adjust else None
            except Exception as exc:  # noqa: BLE001 - this is a help, not a need: the models in the settings are used as they are
                log.warning('the Gemini models could not be checked against the key (%s)', redact(f'{type(exc).__name__}: {exc}', limit=160))
                fitted = None
            if fitted:
                with self._lock:
                    self.members = list(fitted)
                self.adjusted = True
            else:
                self._adjust_after = self.clock() + LIST_RETRY

    def generate(self, system: str, prompt: str, schema: dict, *, temperature: float, max_tokens: int, timeout_s: float) -> str:
        self.fit()
        deadline = self.clock() + timeout_s
        members = list(self.members)
        failures: list[ModelUnavailable] = []
        for index, member in enumerate(members):
            now = self.clock()
            with self._lock:
                resting = self._resting_until.get(id(member), 0.0) > now
                remembered = self._last.get(id(member))
                waiting = [m for m in members[index + 1 :] if self._resting_until.get(id(m), 0.0) <= now]
            if resting and remembered is not None:
                failures.append(remembered)
                continue
            left = deadline - now
            if failures and left < MIN_TRY:
                break  # not enough time left to give another model a fair try
            allowed = min(left * TURN_SHARE if waiting else left, TRY_CAP)  # a model that hangs must not use up the time the next one needs
            try:
                text = member.generate(
                    system, prompt, schema, temperature=temperature, max_tokens=max_tokens, timeout_s=max(1.0, allowed)
                )
            except ModelUnavailable as exc:
                failure = exc
            except Exception as exc:  # noqa: BLE001 - a model that did not turn its own failure into ModelUnavailable
                failure = classify(exc)
            else:
                with self._lock:
                    self._streak.pop(id(member), None)
                    self._resting_until.pop(id(member), None)
                    self._last.pop(id(member), None)
                return text if isinstance(text, Answer) else Answer(text, member.name)
            self._failed(member, failure)
            failures.append(failure)
            if waiting:
                with self._lock:
                    self.handovers += 1
            # what Google said is in the log (a model that does not exist says so there), except the busy message, which is always the same
            said = redact(f': {" ".join(failure.detail.split())}', limit=170) if failure.detail and failure.kind != 'overloaded' else ''
            log.warning('Gemini model %s could not answer (%s%s)%s', member.name, failure.kind, said, '; trying the next one' if waiting else '')
        raise self._summary(members, failures)

    def _failed(self, member: TextModel, failure: ModelUnavailable) -> None:
        """A model that is busy, used up or down rests; one answer that failed (cut off, empty, refused) does not."""
        if failure.kind not in SERVICE_FAILURES:
            return
        with self._lock:
            streak = self._streak[id(member)] = self._streak.get(id(member), 0) + 1
            if failure.kind in TRANSIENT:
                wait = failure.retry_after or min(BUSY_CAP, BUSY_FIRST * 2 ** (streak - 1))  # a busy spell: a short rest, as long as one lasts
            else:
                wait = failure.retry_after or min(BACKOFF_CAP, BACKOFF_FIRST * 2 ** (streak - 1))
            if failure.kind in STUCK:
                wait = BACKOFF_CAP  # trying again will not help until the file is fixed
            self._resting_until[id(member)] = self.clock() + min(wait, BACKOFF_CAP)
            self._last[id(member)] = failure

    def _summary(self, members: list[TextModel], failures: list[ModelUnavailable]) -> ModelUnavailable:
        """One failure for all of them. Its kind is the one that says what to do next: a busy spell is worth waiting out, however
        many of the other models do not exist or are used up. Otherwise, the first one's."""
        first = failures[0] if failures else ModelUnavailable('error', 'no model could be tried')
        pick = next((f for f in failures if f.kind in TRANSIENT), None) or next((f for f in failures if f.kind == 'rate_limited'), None) or first
        names = [member.name for member in members]
        detail = '; '.join(f'{name} {f.kind}: {f.detail}'.strip().rstrip(':') for name, f in zip(names, failures, strict=False))
        retry_after = pick.retry_after
        with self._lock:
            now = self.clock()
            waits = [self._resting_until.get(id(m), 0.0) - now for m in members]
        if pick.kind in SERVICE_FAILURES and all(w > 0 for w in waits):
            retry_after = min(waits)  # every model is resting: the soonest one is tried again first
        tried = tuple((name, f.kind) for name, f in zip(names, failures, strict=False))
        return ModelUnavailable(pick.kind, detail[:600], retry_after, tried)


# ------------------------------------------------------------------ the care a free key needs


class ModelService:
    """What the routes call. `model` is None when there is no key: every call then says so at once. The model may be one TextModel
    or several Gemini models behind one (Failover): the service neither knows nor cares."""

    def __init__(
        self,
        model: TextModel | None,
        *,
        per_minute: int = 12,
        cache_size: int = 32,
        max_parallel: int = 3,
        timeout_s: float = 150.0,
        chat_limit: int = 40,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        retry_wait: float | None = None,
    ):
        self.model = model
        self.per_minute = per_minute
        self.cache_size = cache_size
        #: the longest a report waits for the model (a chat answer waits half as long)
        self.timeout_s = timeout_s
        #: how many model-written chat answers one session may have
        self.chat_limit = chat_limit
        self.clock = clock
        self.sleep = sleep
        #: seconds a repeating call waits before its second try (read now, so a test can set the module's RETRY_WAIT to 0)
        self.retry_wait = RETRY_WAIT if retry_wait is None else retry_wait
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_parallel)
        self._recent: deque[float] = deque()  # when the last calls were made
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._blocked_until = 0.0
        self._failures = 0
        self.last_failure: ModelUnavailable | None = None
        self.calls = 0
        self.cache_hits = 0
        #: how many requests were repeated after a temporary failure
        self.repeats = 0

    # ---- what the app asks about the service
    @property
    def available(self) -> bool:
        """True when a model is configured at all (it may still be resting after a failure)."""
        return self.model is not None

    @property
    def name(self) -> str | None:
        return self.model.name if self.model else None

    def resting_for(self) -> float:
        """Seconds until calls are tried again after a failure, 0 when none is pending."""
        return max(0.0, self._blocked_until - self.clock())

    # ---- the call
    def call(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_s: float = 45.0,
        cache: bool = False,
        validate: Callable[[str], object] | None = None,
        retries: int = 0,
    ) -> str:
        """The model's JSON text. `validate`, when given, is called on the text first and may raise ModelUnavailable (say
        'bad_output'): an answer that cannot be used is then raised at once, is not remembered, and does not make the service rest.
        `retries` is how many times the request may be repeated, after a short wait, when Google says it is busy (a temporary
        failure, see TRANSIENT). A failure that is repeated and then passes leaves no trace; one that does not pass makes the
        service rest, once."""
        if self.model is None:
            raise ModelUnavailable('no_key')
        key = ''
        if cache and self.cache_size > 0:
            key = hashlib.sha256(json.dumps([self.model.name, system, prompt, schema, temperature], sort_keys=True).encode()).hexdigest()
            with self._lock:
                if key in self._cache:
                    self._cache.move_to_end(key)
                    self.cache_hits += 1
                    return self._cache[key]
        self._admit()
        if not self._slots.acquire(timeout=10):
            raise ModelUnavailable('busy', 'too many answers being written at once')
        try:
            text = self._answer(self._generate(system, prompt, schema, temperature, max_tokens, timeout_s, retries))
        finally:
            self._slots.release()
        if validate is not None:
            validate(text)  # raises ModelUnavailable for an unusable answer, before it can be remembered
        with self._lock:
            self._failures = 0
            self.last_failure = None
            if key:
                self._cache[key] = text
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        return text

    def _generate(self, system: str, prompt: str, schema: dict, temperature: float, max_tokens: int, timeout_s: float, retries: int) -> str:
        """One request to the model, repeated up to `retries` times (after a short wait, longer each time) while it fails in a way
        that tends to pass by itself: a busy spell, or a rate limit that says it is over in a few seconds. All of it, the repeats
        included, stays within `timeout_s`. Any other failure, or the last one, is recorded (the service rests) and raised."""
        deadline = self.clock() + timeout_s
        attempt = 0
        while True:
            left = timeout_s if attempt == 0 else max(1.0, deadline - self.clock())
            try:
                return self.model.generate(system, prompt, schema, temperature=temperature, max_tokens=max_tokens, timeout_s=left)
            except ModelUnavailable as exc:
                failure = exc
            except Exception as exc:  # noqa: BLE001 - a model that did not turn its own failure into ModelUnavailable
                failure = classify(exc)
            wait = self._wait_before_repeat(failure, attempt)
            if attempt >= retries or wait is None or self.clock() + wait + MIN_TRY > deadline:
                self._failed(failure)
                raise failure
            attempt += 1
            log.warning('model call failed (%s); trying again in %.0f s', failure.kind, wait)
            self.sleep(wait)
            self._admit()  # the repeat is a request too: it counts toward the minute's share, and is refused if the service began to rest meanwhile
            with self._lock:
                self.repeats += 1

    def _wait_before_repeat(self, failure: ModelUnavailable, attempt: int) -> float | None:
        """How long to wait before the next repeat of a request that failed (`attempt` repeats were made already), or None when
        it is not worth repeating."""
        if failure.kind in TRANSIENT:
            return min(self.retry_wait * (attempt + 1), RETRY_CAP)  # a busy spell: a little longer each time, up to a limit
        if failure.kind == 'rate_limited' and failure.retry_after is not None and 0 < failure.retry_after <= SHORT_WAIT:
            # "Please retry in 3.2s": a per-minute limit that is almost over. A test that removed the usual wait removes this one too.
            return 0.0 if self.retry_wait <= 0 else failure.retry_after + 0.5
        return None

    def _answer(self, text: str) -> Answer:
        """The text, knowing which model wrote it (a model that sends back plain text is the service's own model)."""
        return text if isinstance(text, Answer) else Answer(text, getattr(self.model, 'name', '') or '')

    def _admit(self) -> None:
        """Counts this call, or refuses it: the service is resting after a failure, or the minute's share is used."""
        with self._lock:
            now = self.clock()
            if now < self._blocked_until:
                last = self.last_failure
                raise ModelUnavailable(last.kind if last else 'rate_limited', last.detail if last else '', self._blocked_until - now)
            while self._recent and now - self._recent[0] >= 60.0:
                self._recent.popleft()
            if len(self._recent) >= self.per_minute:
                raise ModelUnavailable('busy', 'the per-minute share of answers is used', 60.0 - (now - self._recent[0]))
            self._recent.append(now)
            self.calls += 1

    def _failed(self, exc: ModelUnavailable) -> None:
        """A failed call. A problem with the service pauses every call (longer each time it repeats); a problem with one
        answer (blocked, cut off, empty) does not."""
        with self._lock:
            self.last_failure = exc
            if exc.kind in SERVICE_FAILURES:
                self._failures += 1
                if exc.kind in TRANSIENT:
                    wait = exc.retry_after or min(BUSY_CAP, BUSY_FIRST * 2 ** (self._failures - 1))  # a busy spell: the next request may try again soon
                else:
                    wait = exc.retry_after or min(BACKOFF_CAP, BACKOFF_FIRST * 2 ** (self._failures - 1))
                if exc.kind in STUCK:
                    wait = BACKOFF_CAP  # trying again will not help until the file is fixed
                self._blocked_until = self.clock() + min(wait, BACKOFF_CAP)
        if exc.tried:  # what each model said was logged as it said it: this is the whole
            log.warning('model call failed (%s): %s', exc.kind, ', '.join(f'{name} {kind}' for name, kind in exc.tried))
        else:
            log.warning('model call failed: %s', redact(f'{exc.kind} {exc.detail}', getattr(self.model, '_key', '')))


def build_service(
    api_key: str,
    model_name: str | list[str],
    *,
    thinking: str = '',
    per_minute: int = 12,
    cache_size: int = 32,
    timeout_s: float = 150.0,
    chat_limit: int = 40,
    discover: int | None = None,
) -> ModelService:
    """The service for one Gemini key: with a Gemini model when there is a key, with none when there is not. `model_name` is one
    model, or several (a list, or names separated by commas): they take turns, the first that can answer does.

    `discover` says what to do with the list of models that Google gives for the key (one quick request, made the first time a
    question is asked, and again later if it failed). None: never ask for it. A number: the models in `model_name` that the key
    does not have are dropped, and up to that many more Flash models from the list are added after them."""
    names = models_in(model_name) if isinstance(model_name, str) else list(dict.fromkeys(model_name))
    members: list[TextModel] = [GeminiModel(api_key, name, thinking) for name in names] if api_key.strip() else []
    model: TextModel | None = None
    if len(members) == 1:
        model = members[0]  # one model, as asked: there is nothing to take over, so there is nothing to fit either
    elif members:
        adjust = None
        if discover is not None:
            def adjust(current: list[TextModel]) -> list[TextModel] | None:
                try:
                    offered = offered_models(api_key)
                except ModelUnavailable as exc:
                    log.warning('could not get the list of Gemini models for this key (%s: %s); the models in the settings are asked as they are', exc.kind, redact(exc.detail, api_key, 160))
                    return None
                return fit_to_key(current, offered, lambda name: GeminiModel(api_key, name, thinking), extras=discover)

        model = Failover(members, adjust=adjust)
    return ModelService(model, per_minute=per_minute, cache_size=cache_size, timeout_s=timeout_s, chat_limit=chat_limit)


def service_from_settings(settings) -> ModelService:
    """The service for the server's `Settings` (core/config.py): every Gemini model in `settings.gemini_models` takes its turn."""
    return build_service(
        settings.gemini_api_key,
        settings.gemini_models,
        thinking=settings.gemini_thinking,
        per_minute=settings.gemini_per_minute,
        cache_size=settings.gemini_cache,
        timeout_s=float(settings.gemini_timeout_s),
        chat_limit=settings.gemini_chat_limit,
        discover=settings.gemini_discover_extras,
    )
