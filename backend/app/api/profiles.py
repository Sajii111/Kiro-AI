"""Hand profiles: GET/POST /profiles, PATCH/DELETE /profiles/{id}."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.clock import iso
from app.core.errors import ApiError, not_found
from app.core.security import new_id
from app.deps import json_response, require_caller, settings_of
from app.schemas import NewProfileInput, RenameProfileInput, StoredProfile
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
    """Every profile of the caller, oldest first."""
    bucket = require_caller(request).bucket
    return json_response(sorted((bucket.as_profile(p) for p in bucket.profiles), key=lambda p: p.createdAt))


@router.post('/profiles')
async def create_profile(body: NewProfileInput, request: Request):
    bucket = require_caller(request).bucket
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
    return json_response(bucket.as_profile(profile), status=201)


@router.patch('/profiles/{profile_id}')
async def rename_profile(profile_id: str, body: RenameProfileInput, request: Request):
    bucket = require_caller(request).bucket
    profile = bucket.profile(profile_id)
    if not profile:
        raise not_found('hand profile')
    check_name(bucket, body.name, ignore_id=profile_id)
    profile.name = body.name.strip()[:PROFILE_NAME_MAX]
    return json_response(bucket.as_profile(profile))


@router.delete('/profiles/{profile_id}')
async def delete_profile(profile_id: str, request: Request):
    """Cascades: the profile, its readings, their conversations and every message in them."""
    bucket = require_caller(request).bucket
    if not bucket.profile(profile_id):
        raise not_found('hand profile')
    return json_response(bucket.drop_profile(profile_id))
