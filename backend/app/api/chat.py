"""Chat: conversations and messages.

One conversation belongs to one reading, which belongs to one profile. On every message the SERVER builds the context
(that reading, its report, this conversation's earlier messages, the caller's other profile names). The browser only
ever sends the question.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.core.clock import iso, now_ms
from app.core.errors import ApiError, not_found
from app.core.security import new_id
from app.deps import json_response, require_caller, still_alive, store_of
from app.llm.chat import ChatContext
from app.llm.chat_llm import respond
from app.schemas import (
    Conversation,
    ConversationWithMessages,
    DataCounts,
    Message,
    MessagePair,
    SendMessageInput,
)
from app.validation import MESSAGE_MAX

router = APIRouter()

TITLE_MAX = 48


@router.get('/conversations')
async def list_conversations(request: Request, readingId: str | None = None, profileId: str | None = None):
    """Most recently updated first. Both filters are optional."""
    bucket = require_caller(request).bucket
    rows = [
        c
        for c in reversed(bucket.conversations)
        if (not readingId or c.readingId == readingId) and (not profileId or c.profileId == profileId)
    ]
    return json_response(sorted(rows, key=lambda c: c.updatedAt, reverse=True))


@router.post('/readings/{reading_id}/conversations')
async def create_conversation(reading_id: str, request: Request):
    bucket = require_caller(request).bucket
    reading = bucket.reading(reading_id)
    if not reading:
        raise not_found('reading')
    now = iso()
    convo = Conversation(id=new_id('cnv'), readingId=reading.id, profileId=reading.profileId, title='New chat', createdAt=now, updatedAt=now, messageCount=0)
    bucket.conversations.append(convo)
    return json_response(convo, status=201)


@router.get('/conversations/{conversation_id}')
async def get_conversation(conversation_id: str, request: Request):
    bucket = require_caller(request).bucket
    convo = bucket.conversation(conversation_id)
    if not convo:
        raise not_found('chat')
    return json_response(ConversationWithMessages(**convo.model_dump(), messages=bucket.messages_of(conversation_id)))


@router.post('/conversations/{conversation_id}/messages')
async def send_message(conversation_id: str, body: SendMessageInput, request: Request):
    caller = require_caller(request)
    bucket = caller.bucket
    convo = bucket.conversation(conversation_id)
    if not convo:
        raise not_found('chat')
    text = body.text.strip()
    if not text:
        raise ApiError('invalid', 'Please type a question first.')
    if len(text) > MESSAGE_MAX:
        raise ApiError('invalid', f'Please keep your question under {MESSAGE_MAX} characters.')
    reading = bucket.reading(convo.readingId)
    profile = bucket.profile(convo.profileId)
    if not reading or not profile:
        raise not_found('reading for this chat')

    context = ChatContext(
        reading=reading,
        profile=bucket.as_profile(profile),
        other_profiles=[bucket.as_profile(p) for p in bucket.profiles if p.id != profile.id],
        history=bucket.messages_of(conversation_id),
    )
    # Gemini may take a while to answer, so this runs in a worker thread: the server keeps answering other people meanwhile.
    # `context` only reads from the store; what the answer changes (the counter, the messages) is done back here.
    response = await run_in_threadpool(respond, text, context, request.app.state.llm, bucket.model_replies)
    bucket.model_replies += response.model_calls  # the model was asked, whatever happens to its answer now

    # The answer took a while, and the world may have moved on: the guest session may have ended, or the chat (or the reading or
    # the profile it belongs to, which takes its chats with it) may have been deleted in another tab. Then nothing is saved.
    # (Checking here is enough: from this line to the end of the function nothing waits, so nothing else can change the data.)
    if not still_alive(store_of(request), caller):
        raise ApiError('expired', 'Your guest session ended while the answer was being written, so nothing was saved. Please start again.')
    if bucket.conversation(conversation_id) is not convo:
        raise ApiError('not_found', 'That chat was deleted while the answer was being written, so nothing was saved.')

    reply = response.answer
    t0 = now_ms()
    user = Message(id=new_id('msg'), conversationId=conversation_id, role='user', text=text, createdAt=iso(t0))
    assistant = Message(
        id=new_id('msg'),
        conversationId=conversation_id,
        role='assistant',
        text=reply.text,
        createdAt=iso(t0 + 1),
        refs=reply.refs,
        flags=reply.flags,
        source=response.source,
        note=response.note,
    )
    bucket.messages.extend([user, assistant])
    convo.updatedAt = assistant.createdAt
    convo.messageCount += 2
    if convo.title == 'New chat':
        convo.title = f'{text[: TITLE_MAX - 1].rstrip()}…' if len(text) > TITLE_MAX else text
    return json_response(MessagePair(user=user, assistant=assistant))


@router.delete('/conversations/{conversation_id}')
async def delete_conversation(conversation_id: str, request: Request):
    bucket = require_caller(request).bucket
    if not bucket.conversation(conversation_id):
        raise not_found('chat')
    conversations, messages = bucket.drop_conversations({conversation_id})
    return json_response(DataCounts(profiles=0, readings=0, conversations=conversations, messages=messages))
