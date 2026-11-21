"""One error type for everything the API says no to, in the one body the website expects:

    {"error": {"code": "invalid", "message": "Keep it to 24 characters or fewer."}}

`message` is a plain sentence the website shows to the person as it is.
"""

from __future__ import annotations

from typing import Literal

ErrorCode = Literal['invalid', 'unauthorised', 'forbidden', 'not_found', 'expired', 'processing_failed']

STATUS_OF: dict[str, int] = {
    'invalid': 422,
    'unauthorised': 401,
    'forbidden': 403,
    'not_found': 404,
    'expired': 410,
    'processing_failed': 500,
}


class ApiError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, status: int | None = None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or STATUS_OF[code]
        self.headers = headers or {}

    def body(self) -> dict:
        return {'error': {'code': self.code, 'message': self.message}}


def not_found(what: str) -> ApiError:
    """404 both for ids that do not exist and for ids that belong to someone else, so nobody can probe for records."""
    return ApiError('not_found', f'That {what} could not be found.')
