"""Talking to Gemini: a small interface, the real implementation, and the care that keeps a free key from running out.

Three layers, so that each can be tested and explained on its own:

  TextModel      what the rest of the app needs from any language model: give it instructions, a question and a JSON
                 schema, get JSON text back. Tests plug in a fake one, so no test ever touches the network.
  GeminiModel    the real TextModel, using Google's `google-genai` library. It is imported only when a key is set, and it
                 turns every way a call can fail into one error, `ModelUnavailable`, with a reason.
  ModelService   what the routes call. It adds the care a free key needs: calls are counted per minute, a rate-limit or
                 server error pauses all calls for a while (a longer pause each time it repeats), and an identical
                 request is answered from memory. A call that is allowed to (the report's) repeats once, after a few
                 seconds, when Google says it is busy. When it cannot answer it raises `ModelUnavailable`, and the
                 caller writes the words from the knowledge base instead. A reading and a chat always finish.

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

#: how long a call that is allowed to repeat waits before it does (Google calls its busy spells "usually temporary")
RETRY_WAIT = 4.0

#: what each kind of failure says to the person, finishing the sentence "..., so the words come from the knowledge base."
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

    def __init__(self, kind: str, detail: str = '', retry_after: float | None = None):
        super().__init__(f'{kind}: {detail}' if detail else kind)
        self.kind = kind
        self.detail = detail
        self.retry_after = retry_after

    @property
    def reason(self) -> str:
        return REASONS.get(self.kind, 'Gemini could not answer')

    @property
    def clause(self) -> str:
        """The reason, to carry on a sentence ("... because <clause>"): "Gemini" keeps its capital letter, the rest do not."""
        text = self.reason
        return text if text.startswith('Gemini') else text[:1].lower() + text[1:]


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
        self._thinking = thinking.strip().upper()
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
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type='application/json',
            response_json_schema=schema,
            http_options=options,
        )
        if self._thinking:
            config.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel(self._thinking))
        try:
            response = self.client().models.generate_content(model=self.name, contents=prompt, config=config)
        except ModelUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - the library, the network, a timeout: all of them become one error, with the key removed
            raise classify(exc, self._key) from None
        return text_of(response)


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


# ------------------------------------------------------------------ the care a free key needs


class ModelService:
    """What the routes call. `model` is None when there is no key: every call then says so at once."""

    def __init__(
        self,
        model: TextModel | None,
        *,
        per_minute: int = 12,
        cache_size: int = 32,
        max_parallel: int = 3,
        timeout_s: float = 60.0,
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
            text = self._generate(system, prompt, schema, temperature, max_tokens, timeout_s, retries)
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
        """One request to the model, repeated up to `retries` times (after a short wait) while it fails in a way that tends to
        pass by itself. Any other failure, or the last one, is recorded (the service rests) and raised."""
        attempt = 0
        while True:
            try:
                return self.model.generate(system, prompt, schema, temperature=temperature, max_tokens=max_tokens, timeout_s=timeout_s)
            except ModelUnavailable as exc:
                failure = exc
            except Exception as exc:  # noqa: BLE001 - a model that did not turn its own failure into ModelUnavailable
                failure = classify(exc)
            if attempt >= retries or failure.kind not in TRANSIENT:
                self._failed(failure)
                raise failure
            attempt += 1
            log.warning('model call failed (%s); trying once more in %.0f s', failure.kind, self.retry_wait)
            self.sleep(self.retry_wait)
            self._admit()  # the repeat is a request too: it counts toward the minute's share, and is refused if the service began to rest meanwhile
            with self._lock:
                self.repeats += 1

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
                wait = exc.retry_after or min(BACKOFF_CAP, BACKOFF_FIRST * 2 ** (self._failures - 1))
                if exc.kind in ('bad_key', 'bad_model', 'region'):
                    wait = BACKOFF_CAP  # trying again will not help until the file is fixed
                self._blocked_until = self.clock() + min(wait, BACKOFF_CAP)
        log.warning('model call failed: %s', redact(f'{exc.kind} {exc.detail}', getattr(self.model, '_key', '')))


def build_service(
    api_key: str,
    model_name: str,
    *,
    thinking: str = '',
    per_minute: int = 12,
    cache_size: int = 32,
    timeout_s: float = 60.0,
    chat_limit: int = 40,
) -> ModelService:
    """The service for the server's settings: with a Gemini model when there is a key, with none when there is not."""
    model = GeminiModel(api_key, model_name, thinking) if api_key.strip() else None
    return ModelService(model, per_minute=per_minute, cache_size=cache_size, timeout_s=timeout_s, chat_limit=chat_limit)


def service_from_settings(settings) -> ModelService:
    """The service for the server's `Settings` (core/config.py)."""
    return build_service(
        settings.gemini_api_key,
        settings.gemini_model,
        thinking=settings.gemini_thinking,
        per_minute=settings.gemini_per_minute,
        cache_size=settings.gemini_cache,
        timeout_s=float(settings.gemini_timeout_s),
        chat_limit=settings.gemini_chat_limit,
    )
