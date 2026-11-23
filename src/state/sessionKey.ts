import type { Session } from '../api/types'

/** A stable text key for "who is this", so data can be reloaded when the person changes. Empty when signed out. */
export function sessionKey(session: Session | null): string {
  if (!session) return ''
  return session.kind === 'user' ? session.user.id : session.guestId
}
