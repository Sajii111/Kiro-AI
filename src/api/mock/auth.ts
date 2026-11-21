// SAMPLE BACKEND ONLY. Fake accounts that live in this browser, so sign-in, guest mode and the
// "import your guest session?" offer can be built and shown before a real server exists.
// No password is ever stored in plain text, and no real account is created anywhere.

import { GUEST_SESSION_MINUTES } from '../../config'
import { hashString } from '../../lib/rand'
import { validateDisplayName, validateEmail, validatePassword } from '../../lib/validate'
import { ApiError } from '../errors'
import type { AuthApi, DataCounts, RestoreResult, Session, UserInfo } from '../types'
import { clearScope, countsOf, dataFor, mutateScope, newId, setScope, type Scope } from './store'

const USERS_KEY = 'kiro-mock-users'
const SESSION_KEY = 'kiro-mock-session'
const GUEST_KEY = 'kiro-mock-guest'
const EXPIRED_KEY = 'kiro-mock-guest-expired'

type UserRecord = UserInfo & { secret: string }
type GuestMeta = { guestId: string; expiresAt: number }

const GUEST: Scope = { kind: 'guest' }

function read<T>(storage: Storage, key: string): T | null {
  try {
    const raw = storage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}
function write(storage: Storage, key: string, value: unknown) {
  try {
    storage.setItem(key, JSON.stringify(value))
  } catch {
    /* blocked storage: the visit still works, it just will not be remembered */
  }
}
const users = (): UserRecord[] => read<UserRecord[]>(localStorage, USERS_KEY) ?? []
const secretOf = (email: string, password: string) => hashString(`${email.toLowerCase()}|${password}`).toString(36)

function guestMeta(): GuestMeta | null {
  return read<GuestMeta>(sessionStorage, GUEST_KEY)
}

function wipeGuest() {
  clearScope(GUEST)
  try {
    sessionStorage.removeItem(GUEST_KEY)
  } catch {
    /* ignore */
  }
}

const asUser = (u: UserRecord): Session => ({ kind: 'user', user: { id: u.id, email: u.email, displayName: u.displayName } })

/** Ends a guest session that ran out. Returns true when one had. */
function expireGuestIfDue(): boolean {
  const meta = guestMeta()
  if (meta && meta.expiresAt <= Date.now()) {
    wipeGuest()
    return true
  }
  return false
}

/** The signed-in person's display name, or null for a guest. No side effects. */
export function currentDisplayName(): string | null {
  const pointer = read<{ userId: string }>(localStorage, SESSION_KEY)
  return (pointer && users().find((u) => u.id === pointer.userId)?.displayName) || null
}

/** Demo helper: makes the guest session end right now, as if its time had run out. */
export function expireGuestNow() {
  wipeGuest()
  write(sessionStorage, EXPIRED_KEY, 1)
}

export const mockAuth: AuthApi = {
  async restore(): Promise<RestoreResult> {
    let guestExpired = expireGuestIfDue()
    try {
      if (sessionStorage.getItem(EXPIRED_KEY)) {
        sessionStorage.removeItem(EXPIRED_KEY)
        guestExpired = true
      }
    } catch {
      /* ignore */
    }

    const pointer = read<{ userId: string }>(localStorage, SESSION_KEY)
    const user = pointer && users().find((u) => u.id === pointer.userId)
    if (user) {
      setScope({ kind: 'user', userId: user.id })
      return { session: asUser(user) }
    }
    const meta = guestMeta()
    if (meta) {
      setScope(GUEST)
      return { session: { kind: 'guest', guestId: meta.guestId, expiresAt: meta.expiresAt } }
    }
    setScope(null)
    return { session: null, guestExpired }
  },

  async signUp({ email, password, displayName }) {
    const bad = validateEmail(email) ?? validatePassword(password) ?? validateDisplayName(displayName)
    if (bad) throw new ApiError('invalid', bad)
    if (users().some((u) => u.email.toLowerCase() === email.trim().toLowerCase())) {
      throw new ApiError('invalid', 'There is already an account with that email. Try signing in instead.')
    }
    const record: UserRecord = { id: newId('usr'), email: email.trim(), displayName: displayName.trim(), secret: secretOf(email.trim(), password) }
    write(localStorage, USERS_KEY, [...users(), record])
    write(localStorage, SESSION_KEY, { userId: record.id })
    setScope({ kind: 'user', userId: record.id })
    return asUser(record)
  },

  async signIn({ email, password }) {
    const bad = validateEmail(email)
    if (bad) throw new ApiError('invalid', bad)
    const record = users().find((u) => u.email.toLowerCase() === email.trim().toLowerCase())
    if (!record) {
      throw new ApiError('unauthorised', 'No account with that email was found here. In demo mode, accounts only exist in this browser, so create one first.')
    }
    if (record.secret !== secretOf(email.trim(), password)) throw new ApiError('unauthorised', 'That password does not match. Please try again.')
    write(localStorage, SESSION_KEY, { userId: record.id })
    setScope({ kind: 'user', userId: record.id })
    return asUser(record)
  },

  async startGuest() {
    wipeGuest()
    const meta: GuestMeta = { guestId: newId('gst'), expiresAt: Date.now() + GUEST_SESSION_MINUTES * 60_000 }
    write(sessionStorage, GUEST_KEY, meta)
    try {
      localStorage.removeItem(SESSION_KEY)
    } catch {
      /* ignore */
    }
    setScope(GUEST)
    return { kind: 'guest', ...meta }
  },

  async signOut() {
    try {
      localStorage.removeItem(SESSION_KEY)
    } catch {
      /* ignore */
    }
    wipeGuest()
    setScope(null)
  },

  async guestSummary(): Promise<DataCounts | null> {
    if (!guestMeta() || expireGuestIfDue()) return null
    const counts = countsOf(dataFor(GUEST))
    return counts.profiles + counts.readings + counts.conversations > 0 ? counts : null
  },

  async importGuest(): Promise<DataCounts> {
    const pointer = read<{ userId: string }>(localStorage, SESSION_KEY)
    if (!pointer) throw new ApiError('unauthorised', 'Sign in first, then import the guest session.')
    const target: Scope = { kind: 'user', userId: pointer.userId }
    const source = dataFor(GUEST)
    const counts = countsOf(source)

    // fresh ids, so nothing can collide with what the account already holds
    const profileIds = new Map<string, string>()
    const readingIds = new Map<string, string>()
    const conversationIds = new Map<string, string>()
    mutateScope(target, (d) => {
      const taken = new Set(d.profiles.map((p) => p.name.toLowerCase()))
      for (const p of source.profiles) {
        const id = newId('prf')
        profileIds.set(p.id, id)
        let name = p.name
        for (let n = 2; taken.has(name.toLowerCase()); n++) name = `${p.name} ${n}`
        taken.add(name.toLowerCase())
        d.profiles.push({ ...p, id, name })
      }
      for (const r of source.readings) {
        const id = newId('rd')
        readingIds.set(r.id, id)
        d.readings.push({ ...r, id, profileId: profileIds.get(r.profileId) ?? r.profileId })
      }
      for (const c of source.conversations) {
        const id = newId('cnv')
        conversationIds.set(c.id, id)
        d.conversations.push({ ...c, id, readingId: readingIds.get(c.readingId) ?? c.readingId, profileId: profileIds.get(c.profileId) ?? c.profileId })
      }
      for (const m of source.messages) {
        d.messages.push({ ...m, id: newId('msg'), conversationId: conversationIds.get(m.conversationId) ?? m.conversationId })
      }
    })
    wipeGuest()
    return counts
  },

  async discardGuest() {
    wipeGuest()
  },
}
