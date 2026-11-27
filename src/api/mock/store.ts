// SAMPLE BACKEND ONLY. Where the sample backend keeps its data, inside this browser.
//
//   Guest session  -> sessionStorage (gone when the tab closes, and cleared when the guest session expires)
//   Signed-in user -> localStorage, one bucket per account
//
// Only structured findings, reports and chats are stored here. Photos are never written anywhere.

import { ApiError } from '../errors'
import type { Attempt, Conversation, DataCounts, HandProfile, HandSide, Message, Reading } from '../types'

export type StoredProfile = Omit<HandProfile, 'readingCount' | 'lastReadingAt' | 'lock' | 'locked' | 'open'>

/**
 * A palm lock of the sample backend. It keeps tiny grey thumbnails of the enrolment photos, which only tell the very same
 * photo apart from another: a stand-in for the real templates, which the server makes from the palm's creases.
 */
export type MockLock = {
  profileId: string
  side: HandSide
  createdAt: string
  samples: number
  prints: number[][]
  lockedUntil?: number
}

export type StoreData = {
  profiles: StoredProfile[]
  readings: Reading[]
  conversations: Conversation[]
  messages: Message[]
  locks: MockLock[]
  attempts: Attempt[]
}

export type Scope = { kind: 'guest' } | { kind: 'user'; userId: string }

const empty = (): StoreData => ({ profiles: [], readings: [], conversations: [], messages: [], locks: [], attempts: [] })

let current: Scope | null = null
const cache = new Map<string, StoreData>()

export const setScope = (scope: Scope | null) => {
  current = scope
  openState = null // a new session starts with every profile closed
}

// ------------------------------------------------------------------ the open profile (this tab only, like a server session)

let openState: { profileId: string; lastSeen: number } | null = null
export const IDLE_MS = 15 * 60_000

/** The profile open in this tab. A locked one left alone too long locks itself again. */
export function openProfileId(): string | null {
  if (!openState || !current) return null
  const d = dataFor(current)
  if (!d.profiles.some((p) => p.id === openState!.profileId)) return (openState = null)
  if (d.locks.some((k) => k.profileId === openState!.profileId) && Date.now() - openState.lastSeen > IDLE_MS) return (openState = null)
  openState.lastSeen = Date.now()
  return openState.profileId
}

export function setOpenProfile(profileId: string | null) {
  openState = profileId ? { profileId, lastSeen: Date.now() } : null
}
export const getScope = () => current

// the -v2 marks the shape of a reading with themes, hand shape and other creases; data from older builds is simply not loaded
const keyOf = (scope: Scope) => (scope.kind === 'guest' ? 'kiro-mock-guest-data-v2' : `kiro-mock-user-${scope.userId}-v2`)

function storageOf(scope: Scope): Storage | null {
  try {
    return scope.kind === 'guest' ? sessionStorage : localStorage
  } catch {
    return null
  }
}

function looksRight(x: unknown): x is StoreData {
  const d = x as Partial<StoreData> | null
  return !!d && Array.isArray(d.profiles) && Array.isArray(d.readings) && Array.isArray(d.conversations) && Array.isArray(d.messages)
}

export function dataFor(scope: Scope): StoreData {
  const key = keyOf(scope)
  const cached = cache.get(key)
  if (cached) return cached
  let loaded = empty()
  try {
    const raw = storageOf(scope)?.getItem(key)
    if (raw) {
      const parsed: unknown = JSON.parse(raw)
      // data saved before palm locks existed has no locks and no attempt log yet
      if (looksRight(parsed)) loaded = { ...parsed, locks: Array.isArray(parsed.locks) ? parsed.locks : [], attempts: Array.isArray(parsed.attempts) ? parsed.attempts : [] }
    }
  } catch {
    /* unreadable data starts fresh */
  }
  cache.set(key, loaded)
  return loaded
}

function persist(scope: Scope) {
  const key = keyOf(scope)
  try {
    storageOf(scope)?.setItem(key, JSON.stringify(cache.get(key) ?? empty()))
  } catch {
    /* storage full or blocked: the data still lives in memory for this visit */
  }
}

/** The data of whoever is using the app right now. */
export function data(): StoreData {
  if (!current) throw new ApiError('unauthorised', 'Please sign in, or continue as a guest, to do that.')
  return dataFor(current)
}

/** Changes the current data and saves it. */
export function mutate<T>(change: (d: StoreData) => T): T {
  const d = data()
  const result = change(d)
  persist(current!)
  return result
}

export function mutateScope<T>(scope: Scope, change: (d: StoreData) => T): T {
  const result = change(dataFor(scope))
  persist(scope)
  return result
}

export function clearScope(scope: Scope) {
  cache.set(keyOf(scope), empty())
  try {
    storageOf(scope)?.removeItem(keyOf(scope))
  } catch {
    /* ignore */
  }
}

export function countsOf(d: StoreData): DataCounts {
  return { profiles: d.profiles.length, readings: d.readings.length, conversations: d.conversations.length, messages: d.messages.length }
}

export function newId(prefix: string): string {
  const uuid = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  return `${prefix}_${uuid.replace(/-/g, '').slice(0, 16)}`
}

// ------------------------------------------------------------------ cascade deletes

/** Removes a conversation and its messages. Returns what went. */
export function dropConversations(d: StoreData, ids: Set<string>): { conversations: number; messages: number } {
  const messages = d.messages.filter((m) => ids.has(m.conversationId)).length
  const conversations = d.conversations.filter((c) => ids.has(c.id)).length
  d.messages = d.messages.filter((m) => !ids.has(m.conversationId))
  d.conversations = d.conversations.filter((c) => !ids.has(c.id))
  return { conversations, messages }
}

/** Removes readings, and with them their conversations, messages and derived findings. */
export function dropReadings(d: StoreData, ids: Set<string>): { readings: number; conversations: number; messages: number } {
  const readings = d.readings.filter((r) => ids.has(r.id)).length
  const convIds = new Set(d.conversations.filter((c) => ids.has(c.readingId)).map((c) => c.id))
  const gone = dropConversations(d, convIds)
  d.readings = d.readings.filter((r) => !ids.has(r.id))
  return { readings, ...gone }
}
