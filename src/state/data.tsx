import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api'
import { errorMessage, PROFILE_LOCKED_EVENT } from '../api/errors'
import type { HandProfile } from '../api/types'
import { useToast } from '../components/ui/Toast'
import { useSession } from './session'
import { sessionKey } from './sessionKey'

// The hand profiles of whoever is signed in, and which one is "active" right now.
// Every screen that makes or shows a reading works on the active profile, and a chat is always tied to one reading
// of one profile, so switching profile can never carry a conversation across.
//
// The active profile is the one OPEN on the server for this browser (palm locks, ICA 02). The app starts on the profile
// picker; choosing a profile goes "inside" it. A profile without a lock opens with a click. A locked one opens only with its
// palm: choosing it sends UNLOCK_NEEDED_EVENT, and the app shell takes the person to the unlock screen. Only one profile is
// open at a time, so opening another locks a locked one again, and so does leaving it for the picker.

/** Sent on `window` with a profile id in `detail` when a locked profile was chosen: the app shell opens its unlock screen. */
export const UNLOCK_NEEDED_EVENT = 'kiro:unlock-needed'

type Data = {
  /** null while loading the first time */
  profiles: HandProfile[] | null
  profilesError: string | null
  /** the profile open in this browser (the one the app is "inside"), or null when none is chosen yet */
  activeProfile: HandProfile | null
  /** the profile being opened right now, while the server answers */
  openingId: string | null
  /** Opens a profile. A locked one is not opened here: the unlock screen is asked for instead. */
  setActiveProfileId: (id: string) => void
  /** Leaves the open profile (a locked one locks again) and goes back to choosing. False when it cannot be left now. */
  leaveProfile: () => Promise<boolean>
  /** loads profiles again, e.g. after one was created, renamed, deleted, locked or unlocked */
  refresh: () => void
}

const DataContext = createContext<Data | null>(null)
const ACTIVE_KEY = 'kiro-active-profile'

function remember(id: string) {
  try {
    sessionStorage.setItem(ACTIVE_KEY, id)
  } catch {
    /* private browsing */
  }
}

export function DataProvider({ children }: { children: ReactNode }) {
  const { session } = useSession()
  const toast = useToast()
  const who = sessionKey(session)
  const [version, setVersion] = useState(0)
  const [loaded, setLoaded] = useState<{ key: string; profiles?: HandProfile[]; error?: string } | null>(null)
  const key = `${who}|${version}`
  const opening = useRef<string | null>(null)
  const [openingId, setOpeningId] = useState<string | null>(null)

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

  const mine = loaded && who && loaded.key.startsWith(`${who}|`) ? loaded : null
  const profiles = mine?.profiles ?? null
  const activeProfile = profiles?.find((p) => p.open) ?? null

  const open = useCallback(
    (id: string, quiet = false) => {
      if (opening.current === id) return
      opening.current = id
      setOpeningId(id)
      remember(id)
      api
        .openProfile(id)
        .then(() => refresh())
        .catch((e: unknown) => {
          if (!quiet) toast(errorMessage(e))
          refresh()
        })
        .finally(() => {
          opening.current = null
          setOpeningId(null)
        })
    },
    [refresh, toast],
  )

  const setActiveProfileId = useCallback(
    (id: string) => {
      const p = profiles?.find((x) => x.id === id)
      if (!p) {
        open(id) // just made, and not in the list yet: a new profile has no lock
        return
      }
      if (p.open) return
      if (p.locked) {
        window.dispatchEvent(new CustomEvent(UNLOCK_NEEDED_EVENT, { detail: id }))
        return
      }
      open(id)
    },
    [profiles, open],
  )

  const leaveProfile = useCallback(async () => {
    try {
      await api.closeProfile()
      refresh()
      return true
    } catch (e) {
      toast(errorMessage(e)) // a reading is still being made: the profile stays open
      return false
    }
  }, [refresh, toast])

  // a profile that locked itself again (left alone too long) shows as locked straight away
  useEffect(() => {
    const onLocked = () => refresh()
    window.addEventListener(PROFILE_LOCKED_EVENT, onLocked)
    return () => window.removeEventListener(PROFILE_LOCKED_EVENT, onLocked)
  }, [refresh])

  const value = useMemo<Data>(
    () => ({ profiles, profilesError: mine?.error ?? null, activeProfile, openingId, setActiveProfileId, leaveProfile, refresh }),
    [profiles, mine?.error, activeProfile, openingId, setActiveProfileId, leaveProfile, refresh],
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
