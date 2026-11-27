"""Reading a multipart upload, entirely in memory. A photo is never written to disk by this server.

Starlette normally hands large uploads to a temporary file once they pass 1 MB. `create_app` raises that limit to the
size of the biggest request the server accepts, so every photo stays in RAM and nothing ever reaches the disk.
"""

from __future__ import annotations

from fastapi import Request
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings
from app.core.errors import ApiError


async def read_form(request: Request, max_files: int = 4, max_fields: int = 8) -> FormData:
    try:
        return await request.form(max_files=max_files, max_fields=max_fields)
    except StarletteHTTPException as exc:
        # a broken or oversized multipart body
        raise ApiError('invalid', 'That upload could not be read. Please choose the photo again and try again.') from exc
    except Exception as exc:
        raise ApiError('invalid', 'That upload could not be read. Please choose the photo again and try again.') from exc


def flag(form: FormData, name: str) -> bool:
    """A yes/no form field: "1", "true" or "yes". Anything else, or no field, is no."""
    value = form.get(name)
    return isinstance(value, str) and value.strip().lower() in ('1', 'true', 'yes')


async def take_photo(form: FormData, field: str, label: str, settings: Settings) -> bytes:
    """The bytes of one uploaded photo, or a plain sentence saying what is wrong with the request."""
    upload = form.get(field)
    if not isinstance(upload, UploadFile):
        raise ApiError('invalid', f'The {label} photo is missing. Please add it and try again.')
    data = await upload.read()
    if not data:
        raise ApiError('invalid', f'The {label} photo is empty. Please choose it again.')
    if len(data) > settings.max_photo_bytes:
        raise ApiError('invalid', f'The {label} photo is larger than {settings.max_photo_bytes // (1024 * 1024)} MB. Please choose a smaller one.')
    return data
