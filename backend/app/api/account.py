"""Account data: GET /account/export, DELETE /account/data, and GET /health."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.clock import iso
from app.deps import json_response, require_caller
from app.schemas import ConversationWithMessages, ExportBundle, Health
from app.store.build import storage_name

router = APIRouter()

VERSION = '0.1.0'


@router.get('/account/export')
async def export_data(request: Request):
    """Everything the caller holds, as one document. It contains no photos, because none are kept."""
    bucket = require_caller(request).bucket
    return json_response(
        ExportBundle(
            exportedAt=iso(),
            profiles=[bucket.as_profile(p) for p in bucket.profiles],
            readings=list(bucket.readings),
            conversations=[ConversationWithMessages(**c.model_dump(), messages=bucket.messages_of(c.id)) for c in bucket.conversations],
        )
    )


@router.delete('/account/data')
async def delete_all_data(request: Request):
    """Deletes every profile, reading, conversation and message of the caller. The account itself stays."""
    return json_response(require_caller(request).bucket.clear())


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
