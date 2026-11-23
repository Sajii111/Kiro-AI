"""Sessions and accounts: GET /session, POST /auth/signup|signin|guest|signout, and the guest import."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.core.errors import ApiError
from app.core.security import burn_time, hash_password, new_id, verify_password
from app.deps import (
    COOKIE_GUEST,
    COOKIE_USER,
    clear_cookie,
    json_response,
    no_content,
    set_cookie,
    settings_of,
    store_of,
)
from app.schemas import (
    DataCounts,
    GuestSession,
    RestoreResult,
    SignInInput,
    SignUpInput,
    UserInfo,
    UserSession,
)
from app.store.memory import Account
from app.validation import (
    PROFILE_NAME_MAX,
    validate_display_name,
    validate_email,
    validate_password,
)

router = APIRouter()

#: The guest cookie lives this much longer than the guest session. If the browser threw the cookie away at the very moment
#: the session ended, the next GET /session would arrive with no cookie at all and the server could not say "your guest
#: session ended" (guestExpired). The cookie holds only a random token, and the data behind it is already deleted.
GUEST_COOKIE_GRACE_SECONDS = 24 * 3600


def user_session(account: Account) -> UserSession:
    return UserSession(user=UserInfo(id=account.id, email=account.email, displayName=account.display_name))


@router.get('/session')
async def get_session(request: Request):
    """Called on every page load. Never answers 401."""
    store, settings = store_of(request), settings_of(request)
    user_token = request.cookies.get(COOKIE_USER)
    guest_token = request.cookies.get(COOKIE_GUEST)
    account = store.account_for(user_token)
    guest = store.guest_for(guest_token)

    if account:
        body = RestoreResult(session=user_session(account))
    elif guest:
        body = RestoreResult(session=GuestSession(guestId=guest.id, expiresAt=guest.expires_at))
    else:
        # a guest cookie with no live session behind it means the session ended since the last visit: say so, once
        body = RestoreResult(session=None, guestExpired=True if guest_token else None)

    response = json_response(body)
    # cookies that no longer lead anywhere are cleared, so this is only said once
    if user_token and not account:
        clear_cookie(response, settings, COOKIE_USER)
    if guest_token and not guest:
        clear_cookie(response, settings, COOKIE_GUEST)
    return response


@router.post('/auth/signup')
async def sign_up(body: SignUpInput, request: Request):
    store, settings = store_of(request), settings_of(request)
    problem = validate_email(body.email) or validate_password(body.password) or validate_display_name(body.displayName)
    if problem:
        raise ApiError('invalid', problem)
    taken = ApiError('invalid', 'There is already an account with that email. Try signing in instead.')
    if store.find_account(body.email):
        raise taken
    salt, password_hash = await run_in_threadpool(hash_password, body.password)
    if store.find_account(body.email):  # someone else may have signed up with it while the password was being hashed
        raise taken
    account = store.add_account(body.email, body.displayName, salt, password_hash)
    store.end_sign_in(request.cookies.get(COOKIE_USER))
    token = store.start_sign_in(account.id)
    response = json_response(user_session(account))
    set_cookie(response, settings, COOKIE_USER, token, settings.signin_days * 86_400)
    return response


@router.post('/auth/signin')
async def sign_in(body: SignInInput, request: Request):
    store, settings = store_of(request), settings_of(request)
    problem = validate_email(body.email)
    if problem:
        raise ApiError('invalid', problem)
    account = store.find_account(body.email)
    if account:
        ok = await run_in_threadpool(verify_password, body.password, account.salt, account.password_hash)
    else:
        await run_in_threadpool(burn_time, body.password)  # an unknown email must not answer faster than a wrong password
        ok = False
    if not account or not ok:
        raise ApiError('unauthorised', 'That email and password do not match. Please try again.')
    # a new sign-in replaces the old one; a guest session, if there is one, is left alone so it can be imported
    store.end_sign_in(request.cookies.get(COOKIE_USER))
    token = store.start_sign_in(account.id)
    response = json_response(user_session(account))
    set_cookie(response, settings, COOKIE_USER, token, settings.signin_days * 86_400)
    return response


@router.post('/auth/guest')
async def start_guest(request: Request):
    store, settings = store_of(request), settings_of(request)
    # a fresh guest session starts empty, and whoever was signed in on this browser is signed out
    store.end_guest_by_token(request.cookies.get(COOKIE_GUEST))
    store.end_sign_in(request.cookies.get(COOKIE_USER))
    token, guest = store.start_guest()
    response = json_response(GuestSession(guestId=guest.id, expiresAt=guest.expires_at))
    set_cookie(response, settings, COOKIE_GUEST, token, settings.guest_minutes * 60 + GUEST_COOKIE_GRACE_SECONDS)
    clear_cookie(response, settings, COOKIE_USER)
    return response


@router.post('/auth/signout')
async def sign_out(request: Request):
    store, settings = store_of(request), settings_of(request)
    store.end_sign_in(request.cookies.get(COOKIE_USER))
    store.end_guest_by_token(request.cookies.get(COOKIE_GUEST))  # a guest's data goes straight away
    response = no_content()
    clear_cookie(response, settings, COOKIE_USER)
    clear_cookie(response, settings, COOKIE_GUEST)
    return response


@router.get('/auth/guest/summary')
async def guest_summary(request: Request):
    """What the guest session still attached to this browser holds, or null when there is nothing to offer."""
    guest = store_of(request).guest_for(request.cookies.get(COOKIE_GUEST))
    if not guest:
        return json_response(None)
    counts = guest.bucket.counts()
    if counts.profiles + counts.readings + counts.conversations == 0:
        return json_response(None)
    return json_response(counts)


@router.post('/auth/guest/import')
async def import_guest(request: Request):
    store, settings = store_of(request), settings_of(request)
    account = store.account_for(request.cookies.get(COOKIE_USER))
    if not account:
        raise ApiError('unauthorised', 'Sign in first, then import the guest session.')
    guest_token = request.cookies.get(COOKIE_GUEST)
    guest = store.guest_for(guest_token)
    if not guest:
        if guest_token:
            raise ApiError('expired', 'That guest session has ended, so there is nothing to import.')
        raise ApiError('not_found', 'There is no guest session to import.')

    source = guest.bucket
    target = store.bucket_of_user(account.id)
    if len(target.profiles) + len(source.profiles) > settings.max_profiles:
        raise ApiError(
            'invalid',
            f'An account can hold {settings.max_profiles} hand profiles, and importing would go over that. '
            'Delete a profile you no longer need first, or choose not to import.',
        )

    counts: DataCounts = source.counts()
    # fresh ids, so nothing can collide with what the account already holds
    profile_ids: dict[str, str] = {}
    reading_ids: dict[str, str] = {}
    convo_ids: dict[str, str] = {}
    taken = {p.name.lower() for p in target.profiles}
    for p in source.profiles:
        name, n = p.name, 2
        while name.lower() in taken:
            suffix = f' {n}'
            name = f'{p.name[: PROFILE_NAME_MAX - len(suffix)]}{suffix}'
            n += 1
        taken.add(name.lower())
        profile_ids[p.id] = new_id('prf')
        target.profiles.append(p.model_copy(update={'id': profile_ids[p.id], 'name': name}))
    for r in source.readings:
        reading_ids[r.id] = new_id('rd')
        target.readings.append(r.model_copy(update={'id': reading_ids[r.id], 'profileId': profile_ids.get(r.profileId, r.profileId)}))
    for c in source.conversations:
        convo_ids[c.id] = new_id('cnv')
        target.conversations.append(
            c.model_copy(update={'id': convo_ids[c.id], 'readingId': reading_ids.get(c.readingId, c.readingId), 'profileId': profile_ids.get(c.profileId, c.profileId)})
        )
    for m in source.messages:
        target.messages.append(m.model_copy(update={'id': new_id('msg'), 'conversationId': convo_ids.get(m.conversationId, m.conversationId)}))

    store.end_guest(guest.id)
    response = json_response(counts)
    clear_cookie(response, settings, COOKIE_GUEST)
    return response


@router.delete('/auth/guest')
async def discard_guest(request: Request):
    store, settings = store_of(request), settings_of(request)
    store.end_guest_by_token(request.cookies.get(COOKIE_GUEST))
    response = no_content()
    clear_cookie(response, settings, COOKIE_GUEST)
    return response
