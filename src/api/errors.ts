// One error type for everything the API layer can say no to, so screens can show a plain message.

export type ApiErrorCode =
  | 'not_found'
  | 'forbidden'
  | 'invalid'
  | 'unauthorised'
  | 'expired'
  | 'processing_failed'
  | 'network'

/**
 * Sent on `window` when the server says the session is over (a 401 or 410 on an ordinary call, for example
 * a cookie that ran out in the middle of a visit), so the app can look the session up again and show sign-in.
 */
export const SESSION_LOST_EVENT = 'kiro:session-lost'

export class ApiError extends Error {
  code: ApiErrorCode
  constructor(code: ApiErrorCode, message: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
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
