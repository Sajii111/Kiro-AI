"""Hand profiles: GET/POST /profiles, PATCH/DELETE /profiles/{id}."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.clock import iso
from app.core.errors import ApiError, not_found
from app.core.security import new_id
from app.deps import json_response, require_caller, settings_of, store_of
from app.locks import current_open, log_event, require_reach, set_open
from app.schemas import (
    NewProfileInput,
    PasswordInput,
    RenameProfileInput,
    StoredProfile,
)
from app.store.memory import Bucket
from app.validation import PROFILE_NAME_MAX, validate_profile_name

router = APIRouter()


def check_name(bucket: Bucket, name: str, ignore_id: str | None = None) -> None:
    problem = validate_profile_name(name)
    if problem:
        raise ApiError('invalid', problem)
    clean = name.strip().lower()
    if any(p.id != ignore_id and p.name.lower() == clean for p in bucket.profiles):
        raise ApiError('invalid', f'You already have a profile called “{name.strip()}”. Please choose a different name.')


@router.get('/profiles')
async def list_profiles(request: Request):
    """Every profile of the caller, oldest first. A locked profile is listed (its name and its lock) without its counts."""
    caller = require_caller(request)
    bucket = caller.bucket
    open_id = current_open(request, caller)
    return json_response(sorted((bucket.as_profile(p, open_id) for p in bucket.profiles), key=lambda p: p.createdAt))


@router.post('/profiles')
async def create_profile(body: NewProfileInput, request: Request):
    caller = require_caller(request)
    bucket = caller.bucket
    check_name(bucket, body.name)
    if body.owner == 'other' and not body.consent:
        raise ApiError('invalid', 'Please confirm that this person has agreed to you uploading their palms.')
    limit = settings_of(request).max_profiles
    if len(bucket.profiles) >= limit:
        raise ApiError('invalid', f'That is the most hand profiles one account can hold ({limit}). Delete one you no longer need first.')
    profile = StoredProfile(
        id=new_id('prf'),
        name=body.name.strip(),
        owner=body.owner,
        consent=True if body.owner == 'self' else body.consent,
        createdAt=iso(),
    )
    bucket.profiles.append(profile)
    return json_response(bucket.as_profile(profile, current_open(request, caller)), status=201)


@router.patch('/profiles/{profile_id}')
async def rename_profile(profile_id: str, body: RenameProfileInput, request: Request):
    caller = require_caller(request)
    bucket = caller.bucket
    profile = bucket.profile(profile_id)
    if not profile:
        raise not_found('hand profile')
    open_id = current_open(request, caller)
    require_reach(bucket, profile_id, open_id)
    check_name(bucket, body.name, ignore_id=profile_id)
    profile.name = body.name.strip()[:PROFILE_NAME_MAX]
    return json_response(bucket.as_profile(profile, open_id))


@router.delete('/profiles/{profile_id}')
async def delete_profile(profile_id: str, request: Request, body: PasswordInput | None = None):
    """Cascades: the profile, its readings, their conversations and every message in them, and its palm lock. A locked
    profile is deleted only while it is open (its palm was shown) or with the account password."""
    from app.api.locks import (
        check_password,  # here, so the two route files do not import each other at load time
    )

    caller = require_caller(request)
    bucket = caller.bucket
    profile = bucket.profile(profile_id)
    if not profile:
        raise not_found('hand profile')
    open_id = current_open(request, caller)
    if bucket.lock_of(profile_id) is not None:
        via = 'palm' if open_id == profile_id else await check_password(caller, (body.password if body else '').strip())
        log_event(bucket, profile, 'profile_deleted', 'Locked profile deleted' + (' while it was open.' if via == 'palm' else ' with the account password.'), via=via)
    if open_id == profile_id:
        set_open(store_of(request), caller, None)
    return json_response(bucket.drop_profile(profile_id))
