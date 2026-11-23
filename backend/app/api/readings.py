"""Readings: POST /readings (a server-sent-events stream), GET /readings, GET/DELETE /readings/{id}.

How the stream is built:

  1. Before the first byte, ordinary JSON errors: not signed in (401), unknown profile (404), a missing or bad photo (422).
     Both photos are checked again here, whatever the browser said.
  2. The image work runs in a worker thread and reports each step into a queue. The response reads the queue and writes
     one event per step. A comment line (": ping") goes out when a step is slow, so proxies keep the connection open.
  3. The reading is saved FIRST; only then is the `reading` event sent. So the website never shows a reading that was
     not stored, and an `error` always means that nothing was saved.
  4. If the browser goes away, the worker is told to stop and nothing is saved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData

from app.api.uploads import flag, read_form, take_photo
from app.core.config import Settings
from app.core.errors import ApiError, not_found
from app.core.security import new_id
from app.cv.images import CheckedPhoto, check_photo
from app.cv.pipeline import Cancelled, run_reading
from app.deps import (
    Caller,
    dump,
    json_response,
    require_caller,
    settings_of,
    still_alive,
    store_of,
)
from app.llm.gemini import ModelService
from app.llm.report import count_statuses, headline_for
from app.schemas import (
    DataCounts,
    ProcessingEvent,
    Reading,
    ReadingSummary,
    RenameReadingInput,
)
from app.store.memory import Bucket, MemoryStore
from app.validation import clean_reading_name, validate_reading_name

log = logging.getLogger('kiro.readings')

router = APIRouter()

#: seconds of silence before a ": ping" comment goes out
PING_SECONDS = 10

#: shown when a step could not be completed: says what was and was not saved
FAILED_TEXT = 'We could not finish working on these photos. Nothing was saved and your photos were thrown away. Please try again.'


def sse(event: str, data) -> str:
    """One server-sent event: a name, one line of JSON, and a blank line."""
    return f'event: {event}\ndata: {json.dumps(dump(data), separators=(",", ":"), ensure_ascii=False)}\n\n'


def report_detail(reading: Reading) -> str:
    """The line shown under the last step: who wrote the words."""
    if reading.meta.mock:
        return 'Sample report written from the results'
    if reading.meta.provider == 'gemini':
        return 'Report written by Gemini from the results, every part checked'
    return 'Report written from the results'


async def stream_reading(
    *,
    store: MemoryStore,
    caller: Caller,
    settings: Settings,
    slots: asyncio.Semaphore,
    profile_id: str,
    photos: dict[str, CheckedPhoto],
    llm: ModelService | None = None,
    name: str | None = None,
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    cancel = threading.Event()
    reading_id = new_id('rd')
    current: str | None = None  # the step that is running, so a failure can be pinned on it

    def post(kind: str, payload: object) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))
        except RuntimeError:  # the server is shutting down and nobody is listening
            pass

    def emit(stage: str, state: str, detail: str | None, previews) -> None:
        post('stage', ProcessingEvent(stage=stage, state=state, detail=detail, previews=previews))  # type: ignore[arg-type]

    def work() -> None:
        try:
            reading = run_reading(reading_id, profile_id, photos, emit, cancel, settings.stage_pause_ms, llm=llm)  # type: ignore[arg-type]
            if name:  # the person's own label for it: added after the words are written, so it never goes near Gemini
                reading = reading.model_copy(update={'name': name})
            post('done', reading)
        except Cancelled:
            pass  # the browser went away: nothing to say and nobody to say it to
        except Exception as exc:
            log.exception('reading failed')
            post('crash', exc)

    try:
        async with slots:
            future = loop.run_in_executor(None, work)
            reading: Reading | None = None
            while reading is None:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
                except TimeoutError:
                    yield ': ping\n\n'
                    continue
                if kind == 'stage':
                    event: ProcessingEvent = payload  # type: ignore[assignment]
                    current = event.stage if event.state == 'running' else None
                    yield sse('stage', event)
                elif kind == 'done':
                    reading = payload  # type: ignore[assignment]
                else:  # a crash in the worker
                    if current:
                        yield sse('stage', ProcessingEvent(stage=current, state='failed', detail='The step could not be completed'))  # type: ignore[arg-type]
                    yield sse('error', {'code': 'processing_failed', 'message': FAILED_TEXT})
                    return
            await future

        # Save first, then say so. The person (or the profile) may have gone while the work was running.
        problem = None
        if not still_alive(store, caller):
            problem = {'code': 'expired', 'message': 'Your guest session ended before the reading finished, so nothing was saved. Please start again.'}
        elif caller.bucket.profile(profile_id) is None:
            problem = {'code': 'not_found', 'message': 'That hand profile was deleted while the reading was being made, so nothing was saved.'}
        if problem:
            yield sse('stage', ProcessingEvent(stage='reading', state='failed', detail='The reading could not be saved'))
            yield sse('error', problem)
            return

        caller.bucket.readings.append(reading)
        yield sse('stage', ProcessingEvent(stage='reading', state='done', detail=report_detail(reading)))
        yield sse('reading', reading)
    finally:
        # runs on a normal end, on an error, and when the browser disconnects: either way the worker stops
        cancel.set()


def reading_name_in(form: FormData) -> str | None:
    """The optional `name` field of a new reading, cleaned. None when there is none. A name that breaks the rules is refused with
    the sentence to show."""
    value = form.get('name')
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError('invalid', 'The name of a reading must be text.')
    problem = validate_reading_name(value)
    if problem:
        raise ApiError('invalid', problem)
    return clean_reading_name(value) or None


@router.post('/readings')
async def create_reading(request: Request):
    caller = require_caller(request)
    settings, store = settings_of(request), store_of(request)

    form = await read_form(request)
    try:
        profile_id = str(form.get('profileId') or '')
        if not profile_id or not caller.bucket.profile(profile_id):
            raise not_found('hand profile')
        name = reading_name_in(form)  # said before any photo is looked at, so a bad name costs nothing
        raw = {side: await take_photo(form, side, side, settings) for side in ('left', 'right')}
        samples = {side: flag(form, f'{side}Sample') for side in ('left', 'right')}
    finally:
        await form.close()

    # check both photos again here: the browser's checks cannot be trusted
    finder = request.app.state.finder
    left, right = await asyncio.gather(*(run_in_threadpool(check_photo, raw[side], side, settings.max_pixels, finder, samples[side]) for side in ('left', 'right')))
    del raw
    photos = {'left': left, 'right': right}
    for side in ('left', 'right'):
        if not photos[side].ok:
            raise ApiError('invalid', f'The {side} photo did not pass the checks. {photos[side].first_problem()}')

    body = stream_reading(
        store=store, caller=caller, settings=settings, slots=request.app.state.reading_slots, profile_id=profile_id, photos=photos, llm=request.app.state.llm, name=name
    )
    return StreamingResponse(
        body,
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-store, no-cache, no-transform', 'X-Accel-Buffering': 'no'},
    )


# ------------------------------------------------------------------ the rest


def summary_of(bucket: Bucket, r: Reading, names: dict[str, str]) -> ReadingSummary:
    """What a list shows about one reading. `names` maps a profile's id to its name."""
    hands = {'left': r.hands.left, 'right': r.hands.right}
    return ReadingSummary(
        id=r.id,
        profileId=r.profileId,
        profileName=names.get(r.profileId, 'Unknown'),
        name=r.name,
        createdAt=r.createdAt,
        counts=count_statuses(hands),
        headline=headline_for(hands),
        conversationCount=sum(1 for c in bucket.conversations if c.readingId == r.id),
    )


@router.get('/readings')
async def list_readings(request: Request, profileId: str | None = None):
    """Newest first. A profile can hold any number of readings; the first item is its newest."""
    bucket = require_caller(request).bucket
    names = {p.id: p.name for p in bucket.profiles}
    rows = [summary_of(bucket, r, names) for r in reversed(bucket.readings) if not profileId or r.profileId == profileId]
    return json_response(sorted(rows, key=lambda s: s.createdAt, reverse=True))


@router.get('/readings/{reading_id}')
async def get_reading(reading_id: str, request: Request):
    reading = require_caller(request).bucket.reading(reading_id)
    if not reading:
        raise not_found('reading')
    return json_response(reading)


@router.patch('/readings/{reading_id}')
async def rename_reading(reading_id: str, body: RenameReadingInput, request: Request):
    """Gives a reading a new name, or takes its name away when the new one is empty. Answers with the row a list would show."""
    bucket = require_caller(request).bucket
    reading = bucket.reading(reading_id)
    if not reading:
        raise not_found('reading')
    problem = validate_reading_name(body.name)
    if problem:
        raise ApiError('invalid', problem)
    reading.name = clean_reading_name(body.name) or None
    return json_response(summary_of(bucket, reading, {p.id: p.name for p in bucket.profiles}))


@router.delete('/readings/{reading_id}')
async def delete_reading(reading_id: str, request: Request):
    bucket = require_caller(request).bucket
    if not bucket.reading(reading_id):
        raise not_found('reading')
    readings, conversations, messages = bucket.drop_readings({reading_id})
    return json_response(DataCounts(profiles=0, readings=readings, conversations=conversations, messages=messages))
