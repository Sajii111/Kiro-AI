import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api'
import { errorMessage, SESSION_LOST_EVENT } from '../api/errors'
import type { DataCounts, RestoreResult, Session, SignInInput, SignUpInput } from '../api/types'
import { forgetAllPhotos } from './media'

// Who is using the app: nobody yet, a guest (temporary, nothing saved), or a signed-in person.

type SessionState = {
  /** "loading" for the first moment while the saved session is looked up */
  status: 'loading' | 'ready'
  session: Session | null
  /** a message for the sign-in page, e.g. after a guest session ended */
  notice: string | null
  clearNotice: () => void
  /** set after signing in when a guest session still holds data: the person must say yes or no */
  importOffer: DataCounts | null
  signUp: (input: SignUpInput) => Promise<void>
  signIn: (input: SignInInput) => Promise<void>
  startGuest: () => Promise<void>
  signOut: () => Promise<void>
  acceptImport: () => Promise<DataCounts>
  declineImport: () => Promise<void>
  /** looks the session up again, e.g. after a demo tool ended the guest session */
  refresh: () => Promise<void>
}

const SessionContext = createContext<SessionState | null>(null)

const EXPIRED_NOTICE = 'Your guest session ended, and nothing from it was saved. You can start a new one any time.'
const ENDED_NOTICE = 'Your session ended, so we signed you out. Please sign in again to carry on.'

/** What a guest session still holds, or null. Asking is a courtesy: if it fails, nobody should be kept from getting in. */
async function guestLeftovers(): Promise<DataCounts | null> {
  try {
    return await api.auth.guestSummary()
  } catch {
    return null
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<'loading' | 'ready'>('loading')
  const [session, setSession] = useState<Session | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [importOffer, setImportOffer] = useState<DataCounts | null>(null)

  // who was signed in a moment ago, so that a session which ends by itself can be told apart from one that never started
  const lastSession = useRef<Session | null>(null)
  useEffect(() => {
    lastSession.current = session
  }, [session])

  const apply = useCallback(async (result: RestoreResult) => {
    const before = lastSession.current
    // photos only ever live in this tab, and never outlast the session that made them
    if (!result.session) forgetAllPhotos()
    setSession(result.session)
    if (result.guestExpired) setNotice(EXPIRED_NOTICE)
    else if (!result.session && before?.kind === 'user') setNotice(ENDED_NOTICE)
    setImportOffer(result.session?.kind === 'user' ? await guestLeftovers() : null)
    setStatus('ready')
  }, [])

  const refresh = useCallback(async () => apply(await api.auth.restore()), [apply])

  useEffect(() => {
    let live = true
    api.auth.restore().then(
      (result) => {
        if (live) void apply(result)
      },
      (error: unknown) => {
        // the server could not be reached: open the app signed out, and say why, instead of waiting on a blank page
        if (!live) return
        setNotice(errorMessage(error))
        setStatus('ready')
      },
    )
    return () => {
      live = false
    }
  }, [apply])

  // when a guest session runs out, look the session up again: the backend clears the temporary data
  useEffect(() => {
    if (session?.kind !== 'guest') return
    const timer = setTimeout(() => void refresh().catch(() => {}), Math.max(0, session.expiresAt - Date.now()) + 60)
    return () => clearTimeout(timer)
  }, [session, refresh])

  // the server says the session is over (a cookie ran out, a guest session ended): look it up again, which shows sign-in
  useEffect(() => {
    let checking = false
    const onLost = () => {
      if (checking) return
      checking = true
      refresh()
        .catch(() => {
          // still cannot reach the server: keep what is on screen, the next call will say so
        })
        .finally(() => {
          checking = false
        })
    }
    window.addEventListener(SESSION_LOST_EVENT, onLost)
    return () => window.removeEventListener(SESSION_LOST_EVENT, onLost)
  }, [refresh])

  const afterSignIn = useCallback(async (next: Session) => {
    setSession(next)
    setNotice(null)
    setImportOffer(await guestLeftovers())
  }, [])

  const value = useMemo<SessionState>(
    () => ({
      status,
      session,
      notice,
      clearNotice: () => setNotice(null),
      importOffer,
      signUp: async (input) => afterSignIn(await api.auth.signUp(input)),
      signIn: async (input) => afterSignIn(await api.auth.signIn(input)),
      startGuest: async () => {
        const next = await api.auth.startGuest()
        setSession(next)
        setNotice(null)
        setImportOffer(null)
      },
      signOut: async () => {
        await api.auth.signOut()
        forgetAllPhotos()
        setSession(null)
        setImportOffer(null)
      },
      acceptImport: async () => {
        const counts = await api.auth.importGuest()
        setImportOffer(null)
        return counts
      },
      declineImport: async () => {
        await api.auth.discardGuest()
        setImportOffer(null)
      },
      refresh,
    }),
    [status, session, notice, importOffer, afterSignIn, refresh],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession(): SessionState {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSession must be used inside <SessionProvider>')
  return ctx
}
