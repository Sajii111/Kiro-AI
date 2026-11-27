"""One error type for everything the API says no to, in the one body the website expects:

    {"error": {"code": "invalid", "message": "Keep it to 24 characters or fewer."}}

`message` is a plain sentence the website shows to the person as it is.
"""

from __future__ import annotations

from typing import Literal

ErrorCode = Literal['invalid', 'unauthorised', 'forbidden', 'not_found', 'expired', 'processing_failed', 'locked', 'locked_out', 'conflict', 'unavailable']

STATUS_OF: dict[str, int] = {
    'invalid': 422,
    'unauthorised': 401,
    'forbidden': 403,
    'not_found': 404,
    'expired': 410,
    'processing_failed': 500,
    #: the hand profile is locked with a palm and is not open in this session: unlock it first
    'locked': 423,
    #: too many failed palm attempts on this profile: try again later
    'locked_out': 429,
    #: not now: something else is still running (a reading, while switching profiles)
    'conflict': 409,
    #: the server cannot do this at all right now (the palm lock without its hand model)
    'unavailable': 503,
}


class ApiError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, status: int | None = None, headers: dict[str, str] | None = None, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or STATUS_OF[code]
        self.headers = headers or {}
        #: more fields for the error body, next to code and message (which photo of a palm lock was the trouble, until when a
        #: profile is locked out)
        self.extra = extra or {}

    def body(self) -> dict:
        return {'error': {'code': self.code, 'message': self.message, **self.extra}}


def not_found(what: str) -> ApiError:
    """404 both for ids that do not exist and for ids that belong to someone else, so nobody can probe for records."""
    return ApiError('not_found', f'That {what} could not be found.')
