"""Settings, read once when the server starts.

They come from environment variables. A file called `backend/.env` is read too (see `.env.example`); a real
environment variable always wins over the file. Nothing secret is needed to run the photo analysis. The Gemini key, which
makes the language model write the reports and the chat, lives only in `backend/.env`; the Firebase credentials arrive in a
later phase and will live only in `backend/secrets/`. Neither is ever printed, logged or committed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.llm.gemini import EXTRA_MODELS, models_in

BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend
PROJECT_DIR = BACKEND_DIR.parent  # the folder that holds package.json and src/


def read_env_text(path: Path) -> str:
    """The text of a settings file, however Windows saved it. A byte-order mark at the start (some editors add one) would stick to
    the first name and hide it, so that line's setting would be silently ignored; and PowerShell's ">" writes UTF-16."""
    data = path.read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16', errors='replace')
    return data.decode('utf-8-sig', errors='replace')


def load_env_file(path: Path) -> None:
    """Reads KEY=VALUE lines from a file into the environment. Missing file: nothing happens."""
    if not path.is_file():
        return
    for raw in read_env_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        else:
            value = re.split(r'\s#', value, maxsplit=1)[0].rstrip()  # "KEY=value  # a note" keeps only the value
        os.environ.setdefault(key.strip(), value)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, '').strip() or default)
    except ValueError:
        return default


#: the models tried after the one in GEMINI_MODEL when that one is busy or used up. Google's "high demand" and its free allowances
#: belong to each model, so every one of these is another chance on the same key. The two Gemma 4 models are served by the same
#: Gemini API and the same key, and they are busy at other times than the Gemini ones. (The Gemini 2.5 models are not listed:
#: Google had stopped offering them to at least one key, and a request to a model that is not offered only fails.) Models that
#: the key cannot use are dropped when Google's list is fetched (GEMINI_DISCOVER), and `run.bat gemini --probe` says which work.
GEMINI_FALLBACK_MODELS = 'gemini-3.1-flash-lite,gemma-4-31b-it,gemma-4-26b-a4b-it'


@dataclass(frozen=True)
class Settings:
    #: "development", "production" or "test"
    env: str = 'development'
    host: str = '127.0.0.1'
    port: int = 8000
    #: where the built website is (the folder `npm run build:server` makes)
    site_dir: Path = PROJECT_DIR / 'dist-server'
    #: how long a guest session lasts, in minutes
    guest_minutes: int = 120
    #: how long a sign-in lasts, in days
    signin_days: int = 14
    #: send the session cookies only over HTTPS (on in production)
    cookie_secure: bool = False
    #: the biggest photo accepted. The browser already keeps photos under this.
    max_photo_bytes: int = 15 * 1024 * 1024
    #: the most pixels a photo may have once decoded (a small file can still hold a huge picture)
    max_pixels: int = 24_000_000
    #: a short pause between the steps of a reading so each one is readable on screen (0 in tests)
    stage_pause_ms: int = 450
    #: how many hand profiles one account (or guest session) may hold
    max_profiles: int = 12
    #: how photos are analysed. "real": find the hand with the hand model and trace the creases (the server will not start
    #: without the model). "sample": never look at the photo, use the sample finder (what the tests use). "auto": real when
    #: the model is installed, otherwise sample. Only `read_settings` says "auto"; a plain Settings() is "sample".
    analysis_mode: str = 'sample'
    #: the MediaPipe hand model file (`run.bat models` downloads it)
    hand_model: Path = BACKEND_DIR / 'models' / 'hand_landmarker.task'
    #: the Gemini key from Google AI Studio. Empty: the fixed wording writes every report and answer. Hidden from repr(), so a
    #: log line or a traceback that prints the settings never shows it.
    gemini_api_key: str = field(default='', repr=False)
    #: which Gemini model writes the words: one, or several separated by commas (the first is tried first). A Flash-Lite model:
    #: quick, and free of charge on Google's free tier.
    gemini_model: str = 'gemini-3.5-flash-lite'
    #: more Gemini models, tried after those when they are busy ("high demand" is per model) or their free allowance is used up.
    #: "none" tries only gemini_model.
    gemini_fallback: str = GEMINI_FALLBACK_MODELS
    #: optional: how much the model may think before answering (MINIMAL, LOW, MEDIUM or HIGH). Empty leaves the model's own default.
    gemini_thinking: str = ''
    #: the longest the report may wait for Gemini, in seconds, the models that take turns and the repeats included. Google's busy
    #: spells ("high demand") pass in a minute or two, and a report is worth the wait. A chat answer waits half as long, at most 45 s.
    gemini_timeout_s: int = 150
    #: how many Gemini-written chat answers one session may have; after that the fixed wording answers
    gemini_chat_limit: int = 40
    #: the most calls to Gemini in one minute, so a free key's per-minute allowance is not used up
    gemini_per_minute: int = 12
    #: how many identical report requests are remembered, so the same findings are not paid for twice (0: none)
    gemini_cache: int = 32
    #: ask Google which models the key may use (one quick request, the first time a question is asked): the models that it does not
    #: have are left out, and a few more Flash models from the list are added after the others. Off in a plain Settings(), so no
    #: test asks Google anything; `read_settings` turns it on unless GEMINI_DISCOVER says no.
    gemini_discover: bool = False
    #: where accounts and everything they own are kept. "memory": in this server's memory only (lost when it stops). "firestore":
    #: also in the Cloud Firestore database of the project whose service account key is `firebase_key` (the server will not
    #: start without it). "auto": Firestore when the key file is there, memory otherwise. Guest sessions are never saved.
    #: Only `read_settings` says "auto"; a plain Settings() is "memory", which is what the tests use.
    storage: str = 'memory'
    #: the service account key the Firebase console makes (Project settings > Service accounts). Never commit it.
    firebase_key: Path = BACKEND_DIR / 'secrets' / 'firebase-service-account.json'
    #: which of the project's Firestore databases: "(default)" unless it was given its own name when it was created
    firestore_database: str = '(default)'

    @property
    def max_request_bytes(self) -> int:
        """The biggest request body accepted: two photos and a little for the form fields."""
        return 2 * self.max_photo_bytes + 1024 * 1024

    @property
    def gemini_fallbacks_off(self) -> bool:
        """True when GEMINI_FALLBACK_MODELS says "none": only the model in `gemini_model` is to be asked."""
        return self.gemini_fallback.strip().lower() in ('none', 'off', 'no', '-')

    @property
    def gemini_models(self) -> list[str]:
        """Every Gemini model that may write the words, in the order they are tried: the ones in `gemini_model`, then the fallbacks
        (unless they are switched off with "none"), none twice."""
        fallback = '' if self.gemini_fallbacks_off else self.gemini_fallback
        return list(dict.fromkeys([*models_in(self.gemini_model), *models_in(fallback)]))

    @property
    def gemini_discover_extras(self) -> int | None:
        """What to do with Google's list of models for the key (see `build_service`): None to never ask for it, otherwise how many
        more models to add from it. No more are added when the fallbacks are switched off: "none" means only the model asked for."""
        if not self.gemini_discover:
            return None
        return 0 if self.gemini_fallbacks_off else EXTRA_MODELS

    def with_(self, **changes) -> Settings:
        return replace(self, **changes)


def read_settings() -> Settings:
    load_env_file(BACKEND_DIR / '.env')
    env = os.environ.get('APP_ENV', 'development').strip().lower() or 'development'
    secure_default = '1' if env == 'production' else '0'
    site = os.environ.get('SITE_DIR', '').strip()
    mode = os.environ.get('ANALYSIS_MODE', 'auto').strip().lower()
    model = os.environ.get('HAND_MODEL', '').strip()
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    storage = os.environ.get('STORAGE', 'auto').strip().lower()
    firebase_key = os.environ.get('FIREBASE_KEY', '').strip()
    database = os.environ.get('FIRESTORE_DATABASE', '').strip()
    return Settings(
        env=env,
        host=os.environ.get('HOST', '127.0.0.1').strip() or '127.0.0.1',
        port=_int('PORT', 8000),
        site_dir=Path(site) if site else PROJECT_DIR / 'dist-server',
        guest_minutes=max(1, _int('GUEST_SESSION_MINUTES', 120)),
        signin_days=max(1, _int('SIGNIN_DAYS', 14)),
        cookie_secure=os.environ.get('COOKIE_SECURE', secure_default).strip().lower() in ('1', 'true', 'yes'),
        max_photo_bytes=max(1024, _int('MAX_PHOTO_MB', 15) * 1024 * 1024),
        max_pixels=max(1_000_000, _int('MAX_PIXELS', 24_000_000)),
        stage_pause_ms=max(0, _int('STAGE_PAUSE_MS', 450)),
        analysis_mode=mode if mode in ('auto', 'real', 'sample') else 'auto',
        hand_model=Path(model) if model else BACKEND_DIR / 'models' / 'hand_landmarker.task',
        gemini_api_key=key,
        gemini_model=os.environ.get('GEMINI_MODEL', '').strip() or 'gemini-3.5-flash-lite',
        gemini_fallback=os.environ.get('GEMINI_FALLBACK_MODELS', '').strip() or GEMINI_FALLBACK_MODELS,
        gemini_thinking=os.environ.get('GEMINI_THINKING', '').strip(),
        gemini_timeout_s=max(5, _int('GEMINI_TIMEOUT_SECONDS', 150)),
        gemini_chat_limit=max(0, _int('GEMINI_CHAT_LIMIT', 40)),
        gemini_per_minute=max(1, _int('GEMINI_MAX_PER_MINUTE', 12)),
        gemini_cache=max(0, _int('GEMINI_CACHE_SIZE', 32)),
        gemini_discover=os.environ.get('GEMINI_DISCOVER', '1').strip().lower() not in ('0', 'false', 'no', 'off'),
        storage=storage if storage in ('auto', 'memory', 'firestore') else 'auto',
        firebase_key=Path(firebase_key) if firebase_key else BACKEND_DIR / 'secrets' / 'firebase-service-account.json',
        firestore_database=database or '(default)',
    )
