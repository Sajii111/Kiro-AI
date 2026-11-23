// The page-switch veil (components/RouteStage.tsx) closes over the screen for a moment while one page is swapped for the
// next. It tells the rest of the app what it is doing through <html data-veil="in | hold | out"> (no attribute when it is
// not there). Anything that plays an entrance when a page opens waits for the veil with afterVeil(), so the entrance is
// not wasted behind it. (The page's own CSS entrance is held by a rule in index.css.)

import { createContext, useContext, useEffect } from 'react'

const OPEN = 'kiro:veil-open'

/** true while the veil is closing or closed, so a page opened right now is still hidden behind it */
export function veilIsUp(): boolean {
  const v = document.documentElement.dataset.veil
  return v === 'in' || v === 'hold'
}

/** Runs `callback` at once when no veil is up, otherwise as soon as it starts to lift. Returns a way to cancel. */
export function afterVeil(callback: () => void): () => void {
  if (!veilIsUp()) {
    callback()
    return () => undefined
  }
  const run = () => {
    window.removeEventListener(OPEN, run)
    callback()
  }
  window.addEventListener(OPEN, run)
  return () => window.removeEventListener(OPEN, run)
}

/** Used by the veil itself: the veil starts to lift now. */
export function announceVeilOpen() {
  window.dispatchEvent(new Event(OPEN))
}

// ---- a stop on the way

let held = 0
const holdListeners = new Set<() => void>()
const notifyHold = () => holdListeners.forEach((l) => l())

/** true while some page asked for the veil to stay closed (see useHoldVeil) */
export const veilIsHeld = () => held > 0

/** For the veil: runs `fn` whenever a page starts or stops holding it. Returns a way to stop listening. */
export function subscribeVeilHold(fn: () => void) {
  holdListeners.add(fn)
  return () => {
    holdListeners.delete(fn)
  }
}

/**
 * For a page that is only a stop on the way to another page (it sets something up, then moves on): for as long as it is
 * on screen the veil stays closed, so nobody sees the stop and the move on plays under the same veil. It lets go after
 * `maxMs` in any case, so that a stop which never finishes shows what it is waiting for instead of blocking the screen.
 */
export function useHoldVeil(maxMs = 6000) {
  useEffect(() => {
    held++
    notifyHold()
    let released = false
    const release = () => {
      if (released) return
      released = true
      held--
      notifyHold()
    }
    const timer = window.setTimeout(release, maxMs)
    return () => {
      window.clearTimeout(timer)
      release()
    }
  }, [maxMs])
}

// ---- the page on its way out

/**
 * True for the page that is still on screen although the address already points somewhere else (the veil is closing
 * over it). Such a page must not start any move of its own, a redirect to the sign-in page for one, or it would
 * override the move that the person has just made.
 */
export const LeavingContext = createContext(false)

export const useLeaving = () => useContext(LeavingContext)
