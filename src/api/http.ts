// The real thing: the same Api, answered by the FastAPI backend at VITE_API_URL.
// Switched on with VITE_USE_MOCK=false. Every endpoint, request and response is described in docs/API_CONTRACT.md.
//
// The browser holds no secrets: the server keeps the session in an httpOnly cookie, and the language-model
// key lives only on the server. Ownership of every profile, reading and chat is checked server-side.

import { API_URL } from '../config'
import { ApiError, isAbort, PROFILE_LOCKED_EVENT, SESSION_LOST_EVENT, type ApiErrorCode, type ApiErrorDetails } from './errors'
import { readEventStream } from './sse'
import type {
  Api,
  AuthApi,
  Conversation,
  ConversationWithMessages,
  DataCounts,
  DeleteSummary,
  Attempt,
  ExportBundle,
  HandProfile,
  Message,
  PalmLockInfo,
  PalmResult,
  ProcessingEvent,
  Reading,
  ReadingSummary,
  RestoreResult,
  Session,
  UnlockEvent,
  ValidationResult,
} from './types'

const BASE = `${API_URL}/v1`

const STATUS_CODE: Record<number, ApiErrorCode> = {
  400: 'invalid',
  401: 'unauthorised',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  410: 'expired',
  422: 'invalid',
  423: 'locked',
  429: 'locked_out',
  503: 'unavailable',
}

type ErrorBody = { error?: { code?: ApiErrorCode; message?: string } & ApiErrorDetails } | null

async function fail(res: Response, path: string): Promise<never> {
  const body = (await res.json().catch(() => null)) as ErrorBody
  const code = body?.error?.code ?? STATUS_CODE[res.status] ?? 'processing_failed'
  // Away from sign-in itself, 401 and 410 mean "your session is over": let the app look it up again and show sign-in.
  if ((res.status === 401 || res.status === 410) && !path.startsWith('/auth/') && path !== '/session') {
    window.dispatchEvent(new Event(SESSION_LOST_EVENT))
  }
  // A profile that locked itself again (left alone too long): let the app show it locked.
  if (code === 'locked') window.dispatchEvent(new CustomEvent(PROFILE_LOCKED_EVENT, { detail: body?.error?.profileId ?? null }))
  const details: ApiErrorDetails = {}
  if (body?.error?.photos) details.photos = body.error.photos
  if (body?.error?.lockedUntil) details.lockedUntil = body.error.lockedUntil
  if (body?.error?.profileId) details.profileId = body.error.profileId
  throw new ApiError(code, body?.error?.message ?? (res.status >= 500 ? 'The server had a problem. Please try again in a moment.' : 'That did not work. Please try again.'), details)
}

/** A palm attempt (an unlock or a Palm lab test): a stream of steps, then the result. */
async function palmAttempt(path: string, form: FormData, onEvent: (event: UnlockEvent) => void, signal?: AbortSignal): Promise<PalmResult> {
  const res = await send('POST', path, form, signal)
  if (!res.ok) await fail(res, path)
  if (!res.body) throw new ApiError('processing_failed', 'The server did not send any progress. Nothing was decided. Please try again.')
  let result: PalmResult | null = null
  await readEventStream(res.body, (name, data) => {
    if (name === 'stage') onEvent(data as UnlockEvent)
    else if (name === 'result') result = data as PalmResult
    else if (name === 'error') {
      const e = data as { code?: ApiErrorCode; message?: string }
      throw new ApiError(e.code ?? 'processing_failed', e.message ?? 'The attempt could not be finished. Please try again.')
    }
  })
  if (!result) throw new ApiError('processing_failed', 'The attempt did not finish. Nothing was decided. Please try again.')
  return result
}

async function send(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  try {
    return await fetch(`${BASE}${path}`, {
      method,
      credentials: 'include',
      signal,
      headers: body !== undefined && !isForm ? { 'Content-Type': 'application/json' } : undefined,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    })
  } catch (e) {
    if (isAbort(e)) throw e
    throw new ApiError('network', 'We could not reach the server. Check your connection and try again.')
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await send(method, path, body)
  if (!res.ok) await fail(res, path)
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

const auth: AuthApi = {
  restore: () => call<RestoreResult>('GET', '/session'),
  signUp: (input) => call<Session>('POST', '/auth/signup', input),
  signIn: (input) => call<Session>('POST', '/auth/signin', input),
  startGuest: () => call<Session>('POST', '/auth/guest'),
  signOut: () => call<void>('POST', '/auth/signout'),
  guestSummary: () => call<DataCounts | null>('GET', '/auth/guest/summary'),
  importGuest: () => call<DataCounts>('POST', '/auth/guest/import'),
  discardGuest: () => call<void>('DELETE', '/auth/guest'),
}

export const httpApi: Api = {
  auth,

  accountStorage: () =>
    call<{ storage?: string }>('GET', '/health').then(
      (health) => (health.storage === 'firestore' ? 'firestore' : 'memory'),
      () => 'memory' as const,
    ),

  listProfiles: () => call<HandProfile[]>('GET', '/profiles'),
  createProfile: (input) => call<HandProfile>('POST', '/profiles', input),
  renameProfile: (id, name) => call<HandProfile>('PATCH', `/profiles/${encodeURIComponent(id)}`, { name }),
  deleteProfile: (id, password) => call<DeleteSummary>('DELETE', `/profiles/${encodeURIComponent(id)}`, password ? { password } : undefined),

  openProfile: (id) => call<HandProfile>('POST', `/profiles/${encodeURIComponent(id)}/open`),
  closeProfile: () => call<void>('POST', '/profiles/close'),
  lockProfile(id, input) {
    const form = new FormData()
    form.set('side', input.side)
    if (input.consent) form.set('consent', '1')
    input.photos.forEach((photo, i) => form.set(`photo${i}`, photo, `palm-${i + 1}.jpg`))
    return call<HandProfile>('POST', `/profiles/${encodeURIComponent(id)}/lock`, form)
  },
  removeLock: (id, password) => call<HandProfile>('DELETE', `/profiles/${encodeURIComponent(id)}/lock`, password ? { password } : undefined),
  unlockProfile(id, photo, onEvent, signal) {
    const form = new FormData()
    form.set('photo', photo, 'palm.jpg')
    return palmAttempt(`/profiles/${encodeURIComponent(id)}/unlock`, form, onEvent, signal)
  },
  testVerification(userId, photo, onEvent, signal) {
    const form = new FormData()
    form.set('profileId', userId)
    form.set('photo', photo, 'palm.jpg')
    return palmAttempt('/palm-lock/test', form, onEvent, signal)
  },
  palmLockInfo: () => call<PalmLockInfo>('GET', '/palm-lock'),
  listActivity: (profileId) => call<Attempt[]>('GET', `/activity${profileId ? `?profileId=${encodeURIComponent(profileId)}` : ''}`),

  validatePhoto(side, photo, options) {
    const form = new FormData()
    form.set('side', side)
    form.set('photo', photo, `${side}.jpg`)
    if (options?.sample) form.set('sample', '1')
    return call<ValidationResult>('POST', '/photos/validate', form)
  },

  async createReading(input, onEvent, signal) {
    const form = new FormData()
    form.set('profileId', input.profileId)
    if (input.name) form.set('name', input.name)
    form.set('left', input.left, 'left.jpg')
    form.set('right', input.right, 'right.jpg')
    if (input.leftSample) form.set('leftSample', '1')
    if (input.rightSample) form.set('rightSample', '1')
    const res = await send('POST', '/readings', form, signal)
    if (!res.ok) await fail(res, '/readings')
    if (!res.body) throw new ApiError('processing_failed', 'The server did not send any progress. Nothing was saved. Please try again.')
    let reading: Reading | null = null
    await readEventStream(res.body, (name, data) => {
      if (name === 'stage') onEvent(data as ProcessingEvent)
      else if (name === 'reading') reading = data as Reading
      else if (name === 'error') {
        const e = data as { code?: ApiErrorCode; message?: string }
        throw new ApiError(e.code ?? 'processing_failed', e.message ?? 'We could not finish the reading. Please try again.')
      }
    })
    if (!reading) throw new ApiError('processing_failed', 'The reading did not finish. Nothing was saved. Please try again.')
    return reading
  },

  listReadings: (profileId) => call<ReadingSummary[]>('GET', `/readings${profileId ? `?profileId=${encodeURIComponent(profileId)}` : ''}`),
  getReading: (id) => call<Reading>('GET', `/readings/${encodeURIComponent(id)}`),
  renameReading: (id, name) => call<ReadingSummary>('PATCH', `/readings/${encodeURIComponent(id)}`, { name }),
  deleteReading: (id) => call<DeleteSummary>('DELETE', `/readings/${encodeURIComponent(id)}`),

  listConversations(filter) {
    const q = new URLSearchParams()
    if (filter?.readingId) q.set('readingId', filter.readingId)
    if (filter?.profileId) q.set('profileId', filter.profileId)
    const s = q.toString()
    return call<Conversation[]>('GET', `/conversations${s ? `?${s}` : ''}`)
  },
  createConversation: (readingId) => call<Conversation>('POST', `/readings/${encodeURIComponent(readingId)}/conversations`),
  getConversation: (id) => call<ConversationWithMessages>('GET', `/conversations/${encodeURIComponent(id)}`),
  sendMessage: (conversationId, text) => call<{ user: Message; assistant: Message }>('POST', `/conversations/${encodeURIComponent(conversationId)}/messages`, { text }),
  deleteConversation: (id) => call<DeleteSummary>('DELETE', `/conversations/${encodeURIComponent(id)}`),

  exportData: () => call<ExportBundle>('GET', '/account/export'),
  deleteAllData: (password) => call<DeleteSummary>('DELETE', '/account/data', password ? { password } : undefined),
}
