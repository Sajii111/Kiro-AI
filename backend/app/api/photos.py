"""POST /photos/validate: check one photo and discard it straight away."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.api.uploads import flag, read_form, take_photo
from app.core.errors import ApiError
from app.cv.images import check_photo
from app.deps import json_response, require_caller, settings_of

router = APIRouter()


@router.post('/photos/validate')
async def validate_photo(request: Request):
    require_caller(request)
    settings = settings_of(request)
    form = await read_form(request)
    try:
        side = form.get('side')
        if side not in ('left', 'right'):
            raise ApiError('invalid', 'Please say which hand this photo is of (left or right).')
        data = await take_photo(form, 'photo', side, settings)
        sample = flag(form, 'sample')
    finally:
        await form.close()
    checked = await run_in_threadpool(check_photo, data, side, settings.max_pixels, request.app.state.finder, sample)
    del data  # the photo is not needed again: only the answer leaves this function
    return json_response(checked.result)
