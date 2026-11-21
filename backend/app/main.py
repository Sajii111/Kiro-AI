"""The FastAPI application: the API under /v1, and the built website served from the same address.

One address means no CORS and no third-party-cookie problem (see docs/API_CONTRACT.md, section 10, Layout A).

Run it with `run.bat` (Windows), or by hand:   python -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import account, chat, photos, profiles, readings, session
from app.core.config import Settings, read_settings
from app.core.errors import ApiError
from app.cv.hand import HandFinder, build_finder
from app.llm.gemini import ModelService, service_from_settings
from app.store.build import build_store
from app.store.persist import StorageUnavailable

log = logging.getLogger('kiro')

#: What the browser may load. The website needs only itself, data: and blob: pictures (processing previews are data
#: URLs, photos are shown from blob: URLs), inline styles, and bundled fonts.
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)

#: at most this many readings are worked on at once; the rest wait their turn
MAX_PARALLEL_READINGS = 3

SWEEP_SECONDS = 30


# ------------------------------------------------------------------ plain-ASGI middleware (it must not buffer streams)


class BodyTooLarge(Exception):
    pass


def _too_large_message(limit: int) -> str:
    return f'That upload is too large. The two photos together must be under {limit // (1024 * 1024)} MB.'


class LimitBody:
    """Refuses a request body over the limit, by its Content-Length first and by counting bytes when there is none."""

    def __init__(self, app: ASGIApp, limit: int):
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http' or scope['method'] in ('GET', 'HEAD', 'OPTIONS') or not scope['path'].startswith('/v1'):
            await self.app(scope, receive, send)
            return

        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        async def refuse() -> None:
            response = JSONResponse(
                {'error': {'code': 'invalid', 'message': _too_large_message(self.limit)}},
                status_code=422,
                headers={'Cache-Control': 'no-store', 'Connection': 'close'},
            )
            await response(scope, receive, send)

        declared = dict(scope['headers']).get(b'content-length')
        if declared and declared.isdigit() and int(declared) > self.limit:
            await refuse()
            return

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > self.limit:
                    raise BodyTooLarge()
            return message

        try:
            await self.app(scope, counting_receive, tracked_send)
        except BodyTooLarge:
            if not started:
                await refuse()


class SecurityHeaders:
    """Headers that belong on every response: nothing from /v1 may be cached, and the website carries a CSP."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        is_api = scope['path'].startswith('/v1')

        async def with_headers(message: Message) -> None:
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                headers.setdefault('X-Content-Type-Options', 'nosniff')
                headers.setdefault('Referrer-Policy', 'no-referrer')
                if is_api:
                    headers.setdefault('Cache-Control', 'no-store')  # everything here is personal
                else:
                    headers.setdefault('Content-Security-Policy', CSP)
            await send(message)

        await self.app(scope, receive, with_headers)


async def save_changes(store) -> None:
    """Writes what changed to the online database, when the server has one (a memory-only store has nothing to do)."""
    flush = getattr(store, 'flush', None)
    if flush is not None:
        await flush()


class SaveAfterChanges:
    """After every request that can change something has been answered in full (a streamed reading included), the changes
    are written to the online database. Answering first keeps the page fast; a failed write is tried again on the next one."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http' or scope['method'] in ('GET', 'HEAD', 'OPTIONS') or not scope['path'].startswith('/v1'):
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            await save_changes(scope['app'].state.store)


# ------------------------------------------------------------------ errors, always in the one body the website reads


def error_response(code: str, message: str, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        {'error': {'code': code, 'message': message}},
        status_code=status,
        headers={'Cache-Control': 'no-store', **(headers or {})},
    )


STATUS_CODES = {400: 'invalid', 401: 'unauthorised', 403: 'forbidden', 404: 'not_found', 410: 'expired', 422: 'invalid'}

SENTENCES = {
    404: 'That address does not exist.',
    405: 'That is not something this address can do.',
    415: 'That kind of request is not supported.',
}


def friendly_validation_message(exc: RequestValidationError) -> str:
    kinds = {str(e.get('type', '')) for e in exc.errors()}
    if kinds & {'string_too_long', 'too_long'}:
        return 'That is too long. Please shorten it and try again.'
    if kinds & {'missing', 'json_invalid', 'model_attributes_type', 'dict_type'}:
        return 'Something is missing from that request. Please fill in everything and try again.'
    return 'Something in that request was not right. Please check it and try again.'


def add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return error_response(exc.code, exc.message, exc.status, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError):
        return error_response('invalid', friendly_validation_message(exc), 422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = STATUS_CODES.get(exc.status_code, 'processing_failed')
        message = SENTENCES.get(exc.status_code) or ('That did not work. Please try again.' if exc.status_code < 500 else 'The server had a problem. Please try again in a moment.')
        return error_response(code, message, exc.status_code)

    @app.exception_handler(StorageUnavailable)
    async def storage_down(request: Request, exc: StorageUnavailable):
        log.error('the database could not be used on %s %s: %s', request.method, request.url.path, exc)
        return error_response('processing_failed', 'The account database could not be reached just now. Please try again in a moment.', 503)

    @app.exception_handler(Exception)
    async def crash(request: Request, exc: Exception):
        log.exception('unhandled error on %s %s', request.method, request.url.path)  # the path only: never a body, never a photo
        return error_response('processing_failed', 'The server had a problem. Nothing was lost that was already saved. Please try again in a moment.', 500)


# ------------------------------------------------------------------ the website

#: Content types for what the build makes. Left alone, Python asks the operating system, and on Windows a registry entry
#: left behind by another program can make it call a .js file "text/plain", which the browser then refuses to run.
MEDIA_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json',
    '.map': 'application/json',
    '.webmanifest': 'application/manifest+json',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
    '.gif': 'image/gif',
    '.ico': 'image/x-icon',
    '.woff2': 'font/woff2',
    '.woff': 'font/woff',
    '.ttf': 'font/ttf',
    '.wasm': 'application/wasm',
    '.txt': 'text/plain; charset=utf-8',
}

NOT_BUILT = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kiro AI: website not built yet</title>
<body style="font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;line-height:1.5">
<h1>The server is running, but the website has not been built yet.</h1>
<p>The API is up at <code>/v1</code>. To see the website here too, build it once (in the folder that holds <code>package.json</code>):</p>
<pre style="background:#f3f0f7;padding:1rem;border-radius:.5rem">npm install
npm run build:server</pre>
<p>Then refresh this page. (<code>run.bat</code> does this for you the first time.)</p>
</body>"""


def add_site(app: FastAPI, site_dir: Path) -> None:
    root = site_dir.resolve()

    @app.get('/{path:path}', include_in_schema=False)
    async def website(path: str):
        index = root / 'index.html'
        if not index.is_file():
            return HTMLResponse(NOT_BUILT, status_code=503, headers={'Cache-Control': 'no-store'})
        if path:
            candidate = (root / path).resolve()
            # a real file inside the build folder (the check keeps ../ tricks out)
            if candidate.is_relative_to(root) and candidate.is_file():
                headers = {'Cache-Control': 'public, max-age=31536000, immutable'} if path.startswith('assets/') else {'Cache-Control': 'no-cache'}
                return FileResponse(candidate, media_type=MEDIA_TYPES.get(candidate.suffix.lower()), headers=headers)
            if path.startswith('assets/'):
                return PlainTextResponse('That file is not in this build. Reload the page.', status_code=404, headers={'Cache-Control': 'no-store'})
        # every other address is a page of the website itself (client-side routes): hand over the app
        return FileResponse(index, media_type=MEDIA_TYPES['.html'], headers={'Cache-Control': 'no-cache'})


# ------------------------------------------------------------------ the app


def create_app(settings: Settings | None = None, finder: HandFinder | None = None, llm: ModelService | None = None) -> FastAPI:
    """`finder` is the hand finder real analysis uses. Left out, the settings decide (see `analysis_mode`): the tests leave
    it out and get the sample finder, a test of the real analysis passes a stand-in finder of its own.

    `llm` is the language-model service that writes real reports and chat answers (llm/gemini.py). Left out, the settings
    decide: with a GEMINI_API_KEY it talks to Gemini, without one the fixed wording writes everything. The tests leave it
    out (no key, so nothing ever reaches the network) or pass a service around a fake model."""
    settings = settings or read_settings()
    if finder is None:
        finder = build_finder(settings.analysis_mode, settings.hand_model)
    if llm is None:
        llm = service_from_settings(settings)
    # Keep uploaded photos in memory: Starlette would otherwise spill anything over 1 MB to a temporary file.
    MultiPartParser.spool_max_size = settings.max_request_bytes

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async def sweeper() -> None:
            while True:
                await asyncio.sleep(SWEEP_SECONDS)
                gone = app.state.store.sweep()
                if gone:
                    log.info('guest sessions ended: %d', gone)
                await save_changes(app.state.store)

        app.state.reading_slots = asyncio.Semaphore(MAX_PARALLEL_READINGS)
        task = asyncio.create_task(sweeper())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await save_changes(app.state.store)
            close = getattr(app.state.finder, 'close', None)
            if close:
                close()  # release the hand model while Python is still fully running

    production = settings.env == 'production'
    app = FastAPI(
        title='Kiro AI',
        version='0.1.0',
        docs_url=None if production else '/v1/docs',
        redoc_url=None,
        openapi_url=None if production else '/v1/openapi.json',
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.finder = finder
    app.state.llm = llm
    app.state.store = build_store(settings)
    app.state.reading_slots = asyncio.Semaphore(MAX_PARALLEL_READINGS)

    app.add_middleware(SaveAfterChanges)
    app.add_middleware(LimitBody, limit=settings.max_request_bytes)
    app.add_middleware(SecurityHeaders)
    add_error_handlers(app)

    for module in (session, profiles, photos, readings, chat, account):
        app.include_router(module.router, prefix='/v1')

    @app.api_route('/v1/{rest:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], include_in_schema=False)
    async def unknown_api(rest: str):
        raise ApiError('not_found', 'That address does not exist.')

    add_site(app, settings.site_dir)
    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """`app.main:app` (what uvicorn is asked for) is made the first time it is wanted, not when this file is imported:
    making it loads the hand model, which importing `create_app` for a test should not do."""
    global _app
    if name == 'app':
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
