// One error type for everything the API layer can say no to, so screens can show a plain message.

export type ApiErrorCode =
  | 'not_found'
  | 'forbidden'
  | 'invalid'
  | 'unauthorised'
  | 'expired'
  | 'processing_failed'
  | 'network'
  /** the hand profile is locked with a palm and not open in this browser: unlock it first */
  | 'locked'
  /** too many failed palm attempts on this profile: try again later */
  | 'locked_out'
  /** not now: something else is running (a reading, while switching profiles) */
  | 'conflict'
  /** the server cannot do this at all right now (the palm lock without its hand model) */
  | 'unavailable'

/**
 * Sent on `window` when the server says the session is over (a 401 or 410 on an ordinary call, for example
 * a cookie that ran out in the middle of a visit), so the app can look the session up again and show sign-in.
 */
export const SESSION_LOST_EVENT = 'kiro:session-lost'

/**
 * Sent on `window` when the server says a profile is locked (an open profile left alone too long locks itself again), with the
 * profile's id in `detail`, so the app can show it locked and offer to unlock it.
 */
export const PROFILE_LOCKED_EVENT = 'kiro:profile-locked'

/** More that an error can carry besides its sentence. */
export type ApiErrorDetails = {
  /** for a palm lock that could not be made: which photos were the trouble (0-based) */
  photos?: { index: number; code: string; message: string }[]
  /** for a profile that is locked out: until when, in milliseconds since 1970 */
  lockedUntil?: number
  /** the profile the error is about */
  profileId?: string
}

export class ApiError extends Error {
  code: ApiErrorCode
  details: ApiErrorDetails
  constructor(code: ApiErrorCode, message: string, details: ApiErrorDetails = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.details = details
  }
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

/** The sentence to show a person for any caught error. */
export function errorMessage(error: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}
