import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api'
import type { HandProfile } from '../api/types'
import { useSession } from './session'
import { sessionKey } from './sessionKey'

// The hand profiles of whoever is signed in, and which one is "active" right now.
// Every screen that makes or shows a reading works on the active profile, and a chat is always tied to one reading
// of one profile, so switching profile can never carry a conversation across.

type Data = {
  /** null while loading the first time */
  profiles: HandProfile[] | null
  profilesError: string | null
  activeProfile: HandProfile | null
  setActiveProfileId: (id: string) => void
  /** loads profiles again, e.g. after one was created, renamed or deleted */
  refresh: () => void
}

const DataContext = createContext<Data | null>(null)
const ACTIVE_KEY = 'kiro-active-profile'

function readActive(): string | null {
  try {
    return sessionStorage.getItem(ACTIVE_KEY)
  } catch {
    return null
  }
}

export function DataProvider({ children }: { children: ReactNode }) {
  const { session } = useSession()
  const who = sessionKey(session)
  const [version, setVersion] = useState(0)
  const [activeId, setActiveId] = useState<string | null>(readActive)
  const [loaded, setLoaded] = useState<{ key: string; profiles?: HandProfile[]; error?: string } | null>(null)
  const key = `${who}|${version}`

  useEffect(() => {
    if (!who) return
    let live = true
    api
      .listProfiles()
      .then((profiles) => live && setLoaded({ key, profiles }))
      .catch((e: unknown) => live && setLoaded({ key, error: e instanceof Error ? e.message : 'Could not load your profiles.' }))
    return () => {
      live = false
    }
  }, [key, who])

  const refresh = useCallback(() => setVersion((v) => v + 1), [])
  const setActiveProfileId = useCallback((id: string) => {
    setActiveId(id)
    try {
      sessionStorage.setItem(ACTIVE_KEY, id)
    } catch {
      /* private browsing */
    }
  }, [])

  const mine = loaded && who && loaded.key.startsWith(`${who}|`) ? loaded : null
  const profiles = mine?.profiles ?? null
  const activeProfile = profiles ? (profiles.find((p) => p.id === activeId) ?? profiles[0] ?? null) : null

  const value = useMemo<Data>(
    () => ({ profiles, profilesError: mine?.error ?? null, activeProfile, setActiveProfileId, refresh }),
    [profiles, mine?.error, activeProfile, setActiveProfileId, refresh],
  )
  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useData(): Data {
  const ctx = useContext(DataContext)
  if (!ctx) throw new Error('useData must be used inside <DataProvider>')
  return ctx
}

/** The profiles, or null before they have loaded or outside a <DataProvider>. Unlike useData it never throws. */
// eslint-disable-next-line react-refresh/only-export-components
export function useProfilesIfAny(): HandProfile[] | null {
  return useContext(DataContext)?.profiles ?? null
}
