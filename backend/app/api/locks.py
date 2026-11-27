"""Palm locks (ICA 02): opening and closing profiles, locking one with a palm, unlocking it, testing a verification, the
attempt log, and how the lock decides.

    POST   /profiles/{id}/open      open a profile without a lock (the one the website works in)
    POST   /profiles/close          close the open profile (a locked one locks again)
    POST   /profiles/{id}/lock      lock a profile with 3-5 photos of one palm (multipart: side, consent, photo0..photo4)
    DELETE /profiles/{id}/lock      take the lock off: with the profile open, or with the account password
    POST   /profiles/{id}/unlock    one photo against the lock, as a stream of steps and a result; success opens the profile
    POST   /palm-lock/test          the same for a typed user ID, without opening anything (the Palm lab's test)
    GET    /palm-lock               how the lock decides: threshold, methods, calibration, rules (read-only)
    GET    /activity                the attempt log, newest first

Photos are read in memory, used once and dropped; a template is kept only sealed (encrypted) with the server's key. The
attempt log holds numbers and words, never a picture.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator

import cv2
import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.uploads import flag, read_form, take_photo
from app.core.clock import iso, now_ms
from app.core.config import Settings
from app.core.errors import ApiError, not_found
from app.core.security import new_id, verify_password
from app.cv.biometric import visuals
from app.cv.biometric.config import DEFAULT, ENGINE_VERSION, config_hash
from app.cv.biometric.engine import (
    OUTCOME_TITLES,
    Decision,
    EnrolProblem,
    Extraction,
    Problem,
    auth_photo_problem,
    enrol,
    extract,
    extract_from_image,
    invalid,
    verify,
)
from app.cv.biometric.match import Calibration
from app.cv.biometric.template import TemplateError, TemplateOutdated, seal, unseal
from app.cv.images import check_photo
from app.cv.pipeline import preview
from app.deps import Caller, dump, json_response, require_caller, settings_of, store_of
from app.locks import (
    FAILURES,
    LOCKOUT_MS,
    WINDOW_MS,
    PalmService,
    after_failure,
    current_open,
    locked_out_until,
    lockout_error,
    log_event,
    require_reach,
    set_open,
)
from app.schemas import (
    PalmLockInfo,
    PalmMethod,
    PalmPolicy,
    PalmResult,
    PasswordInput,
    StoredLock,
    StoredProfile,
    UnlockEvent,
)
from app.store.memory import MemoryStore

log = logging.getLogger('kiro.locks')

router = APIRouter()

PING_SECONDS = 10

METHODS = (
    ('crease', 'Crease map', 'Where the palm\'s creases run (a valley filter at three scales), compared as softened maps at small shifts and as direction histograms in an 8 x 8 grid.'),
    ('compcode', 'Competitive code', 'The strongest line direction in each 4 x 4 block, from six Gabor filters, compared by angular distance at small shifts.'),
    ('lbp', 'Local binary patterns (spare)', 'Skin texture histograms in a 4 x 4 grid, compared by chi-square distance. Shown for comparison; it does not decide.'),
)


def palm(request: Request) -> PalmService:
    return request.app.state.palm


def sse(event: str, data) -> str:
    return f'event: {event}\ndata: {json.dumps(dump(data), separators=(",", ":"), ensure_ascii=False)}\n\n'


async def check_password(caller: Caller, password: str) -> str:
    """'password' when the account password is right; a plain refusal otherwise (403, not 401: the person stays signed in)."""
    if caller.account is None:
        raise ApiError('forbidden', 'Only an account has a password.')
    if not password:
        raise ApiError('forbidden', 'Type your account password to do this without the palm.')
    ok = await run_in_threadpool(verify_password, password, caller.account.salt, caller.account.password_hash)
    if not ok:
        raise ApiError('forbidden', 'That password is not right. Please try again.')
    return 'password'


def profile_or_404(caller: Caller, profile_id: str) -> StoredProfile:
    profile = caller.bucket.profile(profile_id)
    if profile is None:
        raise not_found('hand profile')
    return profile


# ------------------------------------------------------------------ opening and closing


@router.post('/profiles/close')
async def close_profile(request: Request):
    caller = require_caller(request)
    set_open(store_of(request), caller, None)
    return json_response({'openProfileId': None})


@router.post('/profiles/{profile_id}/open')
async def open_profile(profile_id: str, request: Request):
    caller = require_caller(request)
    profile = profile_or_404(caller, profile_id)
    require_reach(caller.bucket, profile_id, current_open(request, caller))
    set_open(store_of(request), caller, profile.id)
    return json_response(caller.bucket.as_profile(profile, profile.id))


# ------------------------------------------------------------------ locking


def photo_features(data: bytes, side: str, max_pixels: int, finder) -> Extraction | Problem:
    """One enrolment photo: the photo checks (stricter than a reading's), then the palm lock's features."""
    checked = check_photo(data, side, max_pixels, finder)  # type: ignore[arg-type]
    return extract(checked, DEFAULT)


@router.post('/profiles/{profile_id}/lock')
async def add_lock(profile_id: str, request: Request):
    caller = require_caller(request)
    if caller.kind != 'user':
        raise ApiError('forbidden', 'Create an account or sign in to lock a profile with a palm. A guest session is temporary, and its lock would go with it.')
    settings, store, service = settings_of(request), store_of(request), palm(request)
    finder = request.app.state.finder
    cal = service.require(finder)
    bucket = caller.bucket
    profile = profile_or_404(caller, profile_id)
    require_reach(bucket, profile_id, current_open(request, caller))

    most, need = DEFAULT.match.enrol_max, DEFAULT.match.enrol_min
    form = await read_form(request, max_files=most + 1, max_fields=most + 6)
    try:
        side = form.get('side')
        if side not in ('left', 'right'):
            raise ApiError('invalid', 'Please say which hand locks this profile (left or right).')
        if not flag(form, 'consent'):
            who = 'you agree' if profile.owner == 'self' else f'{profile.name} has agreed'
            raise ApiError('invalid', f'Please confirm that {who} to their palm being used as a lock. Only encrypted numbers are kept, never the photos.')
        photos: list[bytes] = []
        for i in range(most + 1):
            if form.get(f'photo{i}') is None:
                break
            photos.append(await take_photo(form, f'photo{i}', f'photo {i + 1}', settings))
    finally:
        await form.close()
    if not need <= len(photos) <= most:
        raise ApiError('invalid', f'Locking a profile takes {need} to {most} photos of the same palm. {len(photos)} {"was" if len(photos) == 1 else "were"} sent.')

    started = time.perf_counter()
    results = await asyncio.gather(*(run_in_threadpool(photo_features, data, side, settings.max_pixels, finder) for data in photos))
    del photos
    problems = [{'index': i, 'code': r.code, 'message': r.message} for i, r in enumerate(results) if isinstance(r, Problem)]
    if problems:
        count = len(problems)
        raise ApiError(
            'invalid',
            f'{count} of the photos could not be used for the lock. Take {"it" if count == 1 else "them"} again and try once more.',
            extra={'photos': problems},
        )
    extractions = [r for r in results if isinstance(r, Extraction)]
    template = await run_in_threadpool(enrol, extractions, side, cal)
    if isinstance(template, EnrolProblem):
        extra = {'photos': [{'index': template.photo, 'code': template.code, 'message': template.message}]} if template.photo is not None else None
        raise ApiError('invalid', template.message, extra=extra)
    sealed = (await run_in_threadpool(seal, template, service.key)).decode('ascii')

    if bucket.profile(profile_id) is not profile:  # deleted in another tab while the photos were being worked on
        raise ApiError('not_found', 'That hand profile was deleted while the lock was being made, so no lock was saved.')
    replaced = bucket.lock_of(profile_id) is not None
    bucket.set_lock(
        StoredLock(
            profileId=profile.id,
            side=side,  # type: ignore[arg-type]
            createdAt=iso(),
            samples=len(extractions),
            engineVersion=ENGINE_VERSION,
            configHash=config_hash(DEFAULT),
            sealed=sealed,
        )
    )
    duration = round((time.perf_counter() - started) * 1000)
    log_event(
        bucket,
        profile,
        'lock_replaced' if replaced else 'lock_added',
        f'Palm lock {"replaced" if replaced else "set up"} with {len(extractions)} photos of the {side} hand.',
        hand=side,
        durationMs=duration,
        calibrated=cal.calibrated,
    )
    # the palm has just been shown, so the profile is open (unless a reading for another profile is still running)
    if store.busy.get(caller.session_key, 0) == 0:
        set_open(store, caller, profile.id)
    return json_response(bucket.as_profile(profile, current_open(request, caller)), status=201)


@router.delete('/profiles/{profile_id}/lock')
async def remove_lock(profile_id: str, request: Request, body: PasswordInput | None = None):
    """With the profile open (its palm was shown in this session) the lock just comes off. Otherwise the account password is
    needed instead of the palm, and the attempt log says which it was."""
    caller = require_caller(request)
    bucket = caller.bucket
    profile = profile_or_404(caller, profile_id)
    if bucket.lock_of(profile_id) is None:
        raise ApiError('invalid', f'“{profile.name}” has no palm lock to take off.')
    is_open = current_open(request, caller) == profile_id
    via = 'palm' if is_open else await check_password(caller, (body.password if body else '').strip())
    bucket.drop_lock(profile_id)
    log_event(bucket, profile, 'lock_removed', 'Palm lock taken off' + (' while the profile was open.' if via == 'palm' else ' with the account password.'), via=via)
    return json_response(bucket.as_profile(profile, current_open(request, caller)))


# ------------------------------------------------------------------ unlocking and testing


def mark_up(extraction: Extraction) -> dict[str, np.ndarray]:
    pics = visuals.steps(extraction)
    side = 200
    creases = cv2.resize(pics['creases'], (side, side), interpolation=cv2.INTER_NEAREST)
    code = cv2.resize(pics['code'], (side, side), interpolation=cv2.INTER_NEAREST)
    gap = np.full((side, 6, 3), 255, np.uint8)
    return {
        'roi': cv2.resize(pics['roi'], (side, side), interpolation=cv2.INTER_CUBIC),
        'prep': cv2.resize(pics['contrast'], (side, side), interpolation=cv2.INTER_CUBIC),
        'features': np.hstack([creases, gap, code]),
    }


#: which step an invalid photo stopped at
PROBLEM_STAGE = {'too_flat': 'prep'}


async def stream_attempt(
    *,
    store: MemoryStore,
    caller: Caller,
    settings: Settings,
    service: PalmService,
    cal: Calibration,
    finder,
    slots: asyncio.Semaphore,
    profile: StoredProfile,
    lock: StoredLock,
    data: bytes,
    kind: str,
) -> AsyncIterator[str]:
    """The steps of one palm attempt as server-sent events (`stage`), then `result`, or `error` when the attempt could not be
    made at all. The attempt is logged before its result is sent, so a result on screen is always in the log too.

    `durationMs` is the time the work itself took: the short pauses between steps (there so a person can follow them) are
    not counted."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    cancel = threading.Event()
    pause = min(settings.stage_pause_ms, 350) / 1000
    side = lock.side

    def post(what: str, payload: object) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (what, payload))
        except RuntimeError:
            pass

    def emit(stage: str, state: str, detail: str | None = None, picture: np.ndarray | None = None, ms: float | None = None) -> None:
        post('stage', UnlockEvent(stage=stage, state=state, detail=detail, preview=preview(picture) if picture is not None else None, ms=ms))  # type: ignore[arg-type]

    def rest() -> None:
        if pause and cancel.wait(pause):
            raise InterruptedError

    def work() -> None:
        spent = 0.0
        try:
            emit('checks', 'running')
            t = time.perf_counter()
            checked = check_photo(data, side, settings.max_pixels, finder)
            problem = auth_photo_problem(checked)
            ms = (time.perf_counter() - t) * 1000
            spent += ms
            if problem:
                emit('checks', 'failed', problem.message, ms=ms)
                post('done', (problem, spent))
                return
            assert checked.analysis is not None and checked.hand is not None
            emit('checks', 'done', f'The photo passed the checks: one {side} palm, flat and in view', checked.work, ms)
            rest()
            emit('roi', 'running')
            result = extract_from_image(checked.analysis, checked.hand.points, side, DEFAULT)
            if isinstance(result, Problem):
                stage = PROBLEM_STAGE.get(result.code, 'roi')
                if stage == 'prep':
                    emit('roi', 'done', 'The square from the middle of the palm')
                emit(stage, 'failed', result.message)
                post('done', (result, spent))
                return
            spent += sum(result.timings.values())
            pics = mark_up(result)
            t_ = result.timings
            emit('roi', 'done', f'A {DEFAULT.roi.size} x {DEFAULT.roi.size} square from the middle of the palm, {result.roi.inside:.0%} on the hand', pics['roi'], t_['roi'])
            rest()
            emit('prep', 'running')
            emit('prep', 'done', 'Green channel, light blur, CLAHE, shading taken out, normalised', pics['prep'], t_['prep'])
            rest()
            emit('features', 'running')
            emit('features', 'done', 'A: the crease map · B: the competitive code', pics['features'], t_['crease'] + t_['compcode'] + t_['lbp'])
            rest()
            emit('match', 'running')
            t = time.perf_counter()
            try:
                template = unseal(lock.sealed.encode('ascii'), service.key, DEFAULT)
            except TemplateOutdated:
                post('fatal', 'This palm lock was made by an older version of the palm lock, so it cannot be compared fairly. Take the lock off with your account password and set it up again.')
                return
            except TemplateError:
                post('fatal', 'This palm lock could not be opened with the server\'s key (the key was changed). Take the lock off with your account password and set it up again.')
                return
            decision = verify(template, result, cal, DEFAULT)
            ms = (time.perf_counter() - t) * 1000
            spent += ms
            post('decided', (decision, spent, ms))
        except InterruptedError:
            pass
        except Exception:
            log.exception('palm attempt failed')
            post('crash', None)

    try:
        async with slots:
            future = loop.run_in_executor(None, work)
            decision: Decision | None = None
            spent = 0.0
            while decision is None:
                try:
                    what, payload = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
                except TimeoutError:
                    yield ': ping\n\n'
                    continue
                if what == 'stage':
                    yield sse('stage', payload)
                elif what == 'done':
                    problem, spent = payload  # type: ignore[misc]
                    decision = invalid(problem, cal)
                elif what == 'decided':
                    decision, spent, match_ms = payload  # type: ignore[misc]
                    detail = f'Score {decision.score:.2f} against the threshold {decision.threshold:.2f}' if decision.score is not None else None
                    yield sse('stage', UnlockEvent(stage='match', state='done' if decision.outcome == 'success' else 'failed', detail=detail, ms=match_ms))
                elif what == 'fatal':
                    yield sse('stage', UnlockEvent(stage='match', state='failed', detail='The lock could not be read'))
                    yield sse('error', {'code': 'processing_failed', 'message': payload})
                    return
                else:
                    yield sse('error', {'code': 'processing_failed', 'message': 'The attempt could not be finished. Nothing was decided and the photo was thrown away. Please try again.'})
                    return
            await future

        bucket = caller.bucket
        current_lock = bucket.lock_of(profile.id)
        if bucket.profile(profile.id) is not profile or current_lock is None:
            yield sse('error', {'code': 'not_found', 'message': 'The profile or its lock was removed during the attempt, so nothing was decided.'})
            return
        at_now = now_ms()
        attempt_id = new_id('att')
        reason = decision.reason
        locked_until = None
        log_event(
            bucket,
            profile,
            kind,  # type: ignore[arg-type]
            reason,
            id=attempt_id,
            at=iso(at_now),
            outcome=decision.outcome,
            score=decision.score,
            threshold=decision.threshold,
            methods=decision.methods or None,
            problem=decision.problem,
            hand=side,
            durationMs=round(spent),
            calibrated=decision.calibrated,
        )
        if decision.outcome == 'failed':
            locked_until = after_failure(bucket, current_lock, at_now)
        opened = False
        if decision.outcome == 'success':
            current_lock.lockedUntil = None
            if kind == 'unlock':
                set_open(store, caller, profile.id)
                opened = True
        result = PalmResult(
            attemptId=attempt_id,
            profileId=profile.id,
            outcome=decision.outcome,
            title=OUTCOME_TITLES[decision.outcome],
            score=decision.score,
            threshold=decision.threshold,
            methods=decision.methods,
            raw=decision.raw,
            reason=reason,
            problem=decision.problem,
            hand=side,  # type: ignore[arg-type]
            durationMs=round(spent),
            at=iso(at_now),
            calibrated=decision.calibrated,
            engineVersion=decision.engine_version,
            opened=opened,
            bestSample=decision.best_sample,
            lockedUntil=locked_until,
        )
        yield sse('result', result)
    finally:
        cancel.set()


async def start_attempt(request: Request, caller: Caller, profile: StoredProfile, data: bytes, kind: str) -> StreamingResponse:
    service = palm(request)
    finder = request.app.state.finder
    cal = service.require(finder)
    lock = caller.bucket.lock_of(profile.id)
    if lock is None:
        raise ApiError('invalid', f'“{profile.name}” has no palm lock, so there is nothing to compare the photo with.')
    until = locked_out_until(lock)
    if until:
        raise lockout_error(lock, until)
    body = stream_attempt(
        store=store_of(request),
        caller=caller,
        settings=settings_of(request),
        service=service,
        cal=cal,
        finder=finder,
        slots=request.app.state.reading_slots,
        profile=profile,
        lock=lock,
        data=data,
        kind=kind,
    )
    return StreamingResponse(body, media_type='text/event-stream', headers={'Cache-Control': 'no-store, no-cache, no-transform', 'X-Accel-Buffering': 'no'})


@router.post('/profiles/{profile_id}/unlock')
async def unlock_profile(profile_id: str, request: Request):
    caller = require_caller(request)
    store = store_of(request)
    profile = profile_or_404(caller, profile_id)
    current = current_open(request, caller)
    if current != profile_id and store.busy.get(caller.session_key, 0) > 0:
        raise ApiError('conflict', 'A reading is still being made. Wait until it has finished, then switch profiles.')
    palm(request).require(request.app.state.finder)
    form = await read_form(request)
    try:
        data = await take_photo(form, 'photo', 'palm', settings_of(request))
    finally:
        await form.close()
    return await start_attempt(request, caller, profile, data, 'unlock')


@router.post('/palm-lock/test')
async def test_verification(request: Request):
    """The Palm lab's test: a typed user ID (a profile's ID) and one photo. Nothing is opened; the attempt is logged and counts
    toward the lockout like any other. An ID that is not a profile of this account is refused in plain words."""
    caller = require_caller(request)
    palm(request).require(request.app.state.finder)
    form = await read_form(request)
    try:
        typed = form.get('profileId')
        user_id = typed.strip() if isinstance(typed, str) else ''
        if not user_id:
            raise ApiError('invalid', 'Type the user ID of the profile to test against.')
        profile = caller.bucket.profile(user_id)
        if profile is None:
            raise ApiError('not_found', f'There is no hand profile with the user ID “{user_id[:60]}” in this account, so nothing was compared. Check the ID shown on the profile\'s palm lock.')
        data = await take_photo(form, 'photo', 'palm', settings_of(request))
    finally:
        await form.close()
    return await start_attempt(request, caller, profile, data, 'test')


# ------------------------------------------------------------------ reading about it


@router.get('/palm-lock')
async def palm_lock_info(request: Request):
    require_caller(request)
    service = palm(request)
    cal = service.calibration
    problem = service.ready(request.app.state.finder)
    weights = cal.weights if cal else {}
    return json_response(
        PalmLockInfo(
            available=problem is None,
            note=problem,
            engineVersion=ENGINE_VERSION,
            configHash=config_hash(DEFAULT),
            calibrated=bool(cal and cal.calibrated),
            threshold=cal.threshold if cal else 0.0,
            calibrationSource=cal.source if cal else '',
            measured=cal.measured if cal else {},
            methods=[PalmMethod(id=m, name=name, weight=weights.get(m, 0.0), description=text) for m, name, text in METHODS],
            policy=PalmPolicy(
                failures=FAILURES,
                windowMinutes=WINDOW_MS // 60_000,
                lockoutMinutes=LOCKOUT_MS // 60_000,
                idleMinutes=service.idle_ms // 60_000,
                enrolMin=DEFAULT.match.enrol_min,
                enrolMax=DEFAULT.match.enrol_max,
            ),
            roiSize=DEFAULT.roi.size,
        )
    )


@router.get('/activity')
async def activity(request: Request, profileId: str | None = None):
    """The attempt log, newest first: every palm attempt on every profile of the account (locked ones too: it is the account's
    own record) and every change to a lock."""
    bucket = require_caller(request).bucket
    rows = [a for a in reversed(bucket.attempts) if not profileId or a.profileId == profileId]
    return json_response(rows)
