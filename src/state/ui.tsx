import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { ambient } from '../lib/ambient'
import { applyTheme, getInitialTheme, rememberTheme, type Theme } from '../lib/theme'
import { runThemeChange, type Origin } from '../lib/themeTransition'

// Look-and-feel state that every page shares: theme, sound, and whether the intro gate has been passed.

type Ui = {
  theme: Theme
  /** Switches between Night Sky (dark) and Golden Hour (light). `origin` is where the animation grows from: the pressed button. */
  toggleTheme: (origin?: Origin) => void
  /** the music is audible right now */
  soundOn: boolean
  /** the music is wanted (it is on by default) but the browser holds it back until the first click, key press or tap */
  soundWaiting: boolean
  /** mutes the music, or turns it on; the choice is remembered on this device */
  toggleSound: () => void
  /** true once the visitor has passed the intro gate in this browser tab */
  entered: boolean
  enter: () => void
}

const UiContext = createContext<Ui | null>(null)
const ENTERED_KEY = 'kiro-entered'

export function UiProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const sound = useSyncExternalStore(ambient.subscribe, ambient.getSnapshot, () => 'off' as const)
  const [entered, setEntered] = useState(() => {
    try {
      // opening the site with ?intro plays the welcome again (handy for showing it to someone)
      if (new URLSearchParams(window.location.search).has('intro')) {
        sessionStorage.removeItem(ENTERED_KEY)
        return false
      }
      return sessionStorage.getItem(ENTERED_KEY) === '1'
    } catch {
      return false
    }
  })

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  // The site starts with music: it plays at once if the browser allows it, otherwise on the first click, key press or tap.
  useEffect(() => {
    ambient.begin()
  }, [])

  const toggleTheme = useCallback((origin?: Origin) => {
    const next: Theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'
    // the page and the React state change together, inside the animation, so the new picture is complete when it is revealed
    runThemeChange(() => {
      applyTheme(next)
      flushSync(() => setTheme(next))
    }, origin)
    rememberTheme(next)
  }, [])

  const toggleSound = useCallback(() => ambient.toggle(), [])

  const enter = useCallback(() => {
    try {
      sessionStorage.setItem(ENTERED_KEY, '1')
    } catch {
      /* private browsing */
    }
    setEntered(true)
  }, [])

  const soundOn = sound === 'playing'
  const soundWaiting = sound === 'waiting'
  const value = useMemo(
    () => ({ theme, toggleTheme, soundOn, soundWaiting, toggleSound, entered, enter }),
    [theme, toggleTheme, soundOn, soundWaiting, toggleSound, entered, enter],
  )
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useUi(): Ui {
  const ctx = useContext(UiContext)
  if (!ctx) throw new Error('useUi must be used inside <UiProvider>')
  return ctx
}
