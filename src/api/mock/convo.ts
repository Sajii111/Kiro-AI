// SAMPLE BACKEND ONLY. Shared helpers for profiles and chat, used by the API and the sample-data loader.

import { ApiError } from '../errors'
import type { HandProfile, Message } from '../types'
import { answer, type ChatContext } from './chat'
import { newId, openProfileId, type StoredProfile, type StoreData } from './store'

/** A stored profile plus the counts the screens show. A locked profile that is not open shows no counts. */
export function toProfile(d: StoreData, p: StoredProfile, openId: string | null = openProfileId()): HandProfile {
  const lock = d.locks.find((k) => k.profileId === p.id) ?? null
  const locked = !!lock && p.id !== openId
  const mine = locked ? [] : d.readings.filter((r) => r.profileId === p.id)
  const last = mine.reduce<string | null>((a, r) => (!a || r.createdAt > a ? r.createdAt : a), null)
  return {
    ...p,
    readingCount: mine.length,
    lastReadingAt: last,
    lock: lock ? { side: lock.side, createdAt: lock.createdAt, samples: lock.samples, engineVersion: MOCK_ENGINE } : null,
    locked,
    open: p.id === openId,
  }
}

export const MOCK_ENGINE = 'sample lock (thumbnails)'

/**
 * Adds a question and its answer to a conversation. The answer is built only from this conversation's reading,
 * its report and its earlier messages, which is what the real server attaches to every question.
 */
export function postMessage(d: StoreData, conversationId: string, text: string): { user: Message; assistant: Message } {
  const convo = d.conversations.find((c) => c.id === conversationId)
  if (!convo) throw new ApiError('not_found', 'That chat could not be found.')
  const reading = d.readings.find((r) => r.id === convo.readingId)
  const profile = d.profiles.find((p) => p.id === convo.profileId)
  if (!reading || !profile) throw new ApiError('not_found', 'The reading for this chat could not be found.')

  const ctx: ChatContext = {
    reading,
    profile: toProfile(d, profile),
    otherProfiles: d.profiles.filter((p) => p.id !== profile.id).map((p) => toProfile(d, p)),
    history: d.messages.filter((m) => m.conversationId === conversationId),
  }
  const a = answer(text, ctx)
  const t0 = Date.now()
  const user: Message = { id: newId('msg'), conversationId, role: 'user', text, createdAt: new Date(t0).toISOString() }
  const assistant: Message = {
    id: newId('msg'),
    conversationId,
    role: 'assistant',
    text: a.text,
    createdAt: new Date(t0 + 1).toISOString(),
    ...(a.refs ? { refs: a.refs } : {}),
    ...(a.flags ? { flags: a.flags } : {}),
  }
  d.messages.push(user, assistant)
  convo.updatedAt = assistant.createdAt
  convo.messageCount += 2
  if (convo.title === 'New chat') convo.title = text.length > 48 ? `${text.slice(0, 47).trimEnd()}…` : text
  return { user, assistant }
}
