"""Account data: GET /account/export, DELETE /account/data, and GET /health."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.clock import iso
from app.deps import json_response, require_caller
from app.locks import can_reach, current_open
from app.schemas import ConversationWithMessages, ExportBundle, Health, PasswordInput
from app.store.build import storage_name

router = APIRouter()

VERSION = '0.1.0'


@router.get('/account/export')
async def export_data(request: Request):
    """Everything the caller holds, as one document. It contains no photos, because none are kept, and no palm templates.
    A locked profile is listed by name, without its readings and chats: unlock it first to take those too."""
    caller = require_caller(request)
    bucket = caller.bucket
    open_id = current_open(request, caller)
    return json_response(
        ExportBundle(
            exportedAt=iso(),
            profiles=[bucket.as_profile(p, open_id) for p in bucket.profiles],
            readings=[r for r in bucket.readings if can_reach(bucket, r.profileId, open_id)],
            conversations=[
                ConversationWithMessages(**c.model_dump(), messages=bucket.messages_of(c.id)) for c in bucket.conversations if can_reach(bucket, c.profileId, open_id)
            ],
        )
    )


@router.delete('/account/data')
async def delete_all_data(request: Request, body: PasswordInput | None = None):
    """Deletes every profile, reading, conversation and message of the caller, every palm lock and the attempt log. The
    account itself stays. With a locked profile that is not open, the account password is needed."""
    from app.api.locks import check_password

    caller = require_caller(request)
    bucket = caller.bucket
    open_id = current_open(request, caller)
    if any(not can_reach(bucket, p.id, open_id) for p in bucket.profiles):
        await check_password(caller, (body.password if body else '').strip())
    request.app.state.store.open_profiles.pop(caller.session_key, None)
    return json_response(bucket.clear())


@router.get('/health')
async def health(request: Request):
    """For a quick look (and for the smoke check): is the server up, which kind of analysis is it running, and who writes the words?"""
    llm = request.app.state.llm
    return json_response(
        Health(
            ok=True,
            service='kiro-ai',
            version=VERSION,
            analysis='real' if request.app.state.finder is not None else 'sample',
            writer='gemini' if llm.available else 'knowledge-base',
            writerModel=llm.name,
            storage=storage_name(request.app.state.store),
        )
    )
