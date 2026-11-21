"""What every route needs: who is calling, the settings, the store, and a way to answer in JSON.

Who is calling is decided here and nowhere else, from the two cookies:

    kiro_session   a signed-in account
    kiro_guest     a guest session

Both are httpOnly, so page scripts can never read them. A signed-in account wins when both are present (a person who
signs in keeps their guest cookie for a while, so the website can offer to import it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.core.clock import now_ms
from app.core.config import Settings
from app.core.errors import ApiError
from app.store.memory import Account, Bucket, GuestSession, MemoryStore

COOKIE_USER = 'kiro_session'
COOKIE_GUEST = 'kiro_guest'


@dataclass(frozen=True)
class Caller:
    """Whoever sent the request, and the one bucket of data they can reach."""

    kind: Literal['user', 'guest']
    bucket: Bucket
    account: Account | None = None
    guest: GuestSession | None = None


def store_of(request: Request) -> MemoryStore:
    return request.app.state.store


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def require_caller(request: Request) -> Caller:
    """The caller of a route that needs a session. 401 when there is none, 410 when a guest session has ended."""
    store = store_of(request)
    account = store.account_for(request.cookies.get(COOKIE_USER))
    if account:
        return Caller('user', store.bucket_of_user(account.id), account=account)
    guest_token = request.cookies.get(COOKIE_GUEST)
    guest = store.guest_for(guest_token)
    if guest:
        return Caller('guest', guest.bucket, guest=guest)
    if guest_token:
        raise ApiError('expired', 'Your guest session has ended and its data has been deleted. Please start again.')
    raise ApiError('unauthorised', 'Please sign in, or continue as a guest, to do that.')


def still_alive(store: MemoryStore, caller: Caller) -> bool:
    """False when a guest session ended while a slow piece of work (a reading, a chat answer) was running. Its data is gone by
    then, so saving the result would leave a stranger's photos-derived text in memory with nobody to delete it."""
    if caller.guest is None:
        return True
    return store.guests.get(caller.guest.id) is caller.guest and caller.guest.expires_at > now_ms()


# ------------------------------------------------------------------ answering


def dump(value):
    """A model, or a list of models, as plain JSON-ready data."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, list):
        return [dump(v) for v in value]
    return value


def json_response(value, status: int = 200) -> JSONResponse:
    return JSONResponse(dump(value), status_code=status)


def no_content() -> Response:
    return Response(status_code=204)


def set_cookie(response: Response, settings: Settings, key: str, value: str, max_age_s: int) -> None:
    response.set_cookie(key, value, max_age=max_age_s, httponly=True, samesite='lax', secure=settings.cookie_secure, path='/')


def clear_cookie(response: Response, settings: Settings, key: str) -> None:
    response.delete_cookie(key, path='/', httponly=True, samesite='lax', secure=settings.cookie_secure)
