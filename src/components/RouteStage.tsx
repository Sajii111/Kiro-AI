import { useEffect, useRef, useState, useSyncExternalStore, useTransition, type ReactNode } from 'react'
import { useLocation, type Location } from 'react-router-dom'
import { announceVeilOpen, LeavingContext, subscribeVeilHold, veilIsHeld } from '../lib/veil'
import TransitionMark from './TransitionMark'

// Switching pages. The address changes at once, but the page that is shown follows a moment later:
//
//   1. a veil (the colour of the sky, with a small star on it) fades in over the page that is leaving   ('in')
//   2. under the veil the next page is swapped in (and the scroll goes back to the top)               ('hold')
//   3. once the next page is ready the veil lifts, and the page eases in as it does                    ('out')
//
// It is short on purpose: a little under a second in all, and no progress bar. If the next page's code has to be fetched
// first, the veil simply stays closed until it arrives. Nothing happens for a change of query or #section on the same
// page, nor for the very first page of a visit, nor with "reduce motion" (the page just changes).
//
// The pages themselves need not know about any of this: <Routes location={shown}> shows the page for `shown`, and
// everything inside sees `shown` as the current location. Two things follow from the old page staying on screen for a
// moment after the address has changed, and both are handled here:
//   - it is told that it is leaving (useLeaving), so that it does not start a move of its own (a redirect to the
//     sign-in page, say) that would override the move the person just made;
//   - a page that redirects the moment it appears gets that redirect under the same veil: the veil waits a moment
//     after a page is ready before it lifts (SETTLE_MS), and a page that is only a stop on the way (useHoldVeil) keeps
//     it closed until it has moved on.

const COVER_MS = 230 // the veil fading in
const HOLD_MS = 150 // the least time it stays closed (so the star can be seen)
const SETTLE_MS = 80 // after the next page is ready: time for a redirect that page makes at once
const LIFT_MS = 420 // the veil fading out; must match the CSS

type Phase = 'idle' | 'in' | 'hold' | 'out'

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export default function RouteStage({ children }: { children: (shown: Location) => ReactNode }) {
  const location = useLocation()
  const [shown, setShown] = useState(location)
  const [phase, setPhaseState] = useState<Phase>('idle')
  const [holdOver, setHoldOver] = useState(false)
  const [pending, startTransition] = useTransition()
  const held = useSyncExternalStore(subscribeVeilHold, veilIsHeld, () => false)
  // what the timers need to know, without them going stale. `shown` (here) is the page asked for, `committed` the one on screen.
  const live = useRef({ phase: 'idle' as Phase, target: location, shown: location, committed: location, pending: false })
  const timers = useRef<number[]>([])

  const later = (fn: () => void, ms: number) => {
    timers.current.push(window.setTimeout(fn, ms))
  }
  const clearTimers = () => {
    timers.current.forEach((id) => window.clearTimeout(id))
    timers.current = []
  }
  const setPhase = (next: Phase) => {
    live.current.phase = next
    if (next === 'idle') delete document.documentElement.dataset.veil
    else document.documentElement.dataset.veil = next
    setPhaseState(next)
  }
  /** shows the page for the latest location (under the veil, or at once when there is no veil) */
  const swap = () => {
    const next = live.current.target
    live.current.shown = next
    if (!next.hash) window.scrollTo(0, 0)
    // a transition keeps the old page on screen until the new one (which may have to load) is ready
    startTransition(() => setShown(next))
  }
  /** closes the veil, swaps the page under it, and holds for a moment */
  const cover = () => {
    clearTimers()
    setPhase('in')
    later(() => {
      setPhase('hold')
      setHoldOver(false)
      swap()
      later(() => setHoldOver(true), HOLD_MS)
    }, COVER_MS)
  }

  // the address changed
  useEffect(() => {
    live.current.target = location
    if (location.key === live.current.shown.key) return
    const phaseNow = live.current.phase
    if (location.pathname === live.current.shown.pathname || reduced()) {
      // same page (or no veil wanted): no ceremony. A veil that is already up carries on as it is.
      swap()
      return
    }
    if (phaseNow === 'hold') swap() // already closed (a redirect, say): just change pages under it
    else if (phaseNow === 'idle' || phaseNow === 'out') cover()
    // while it is closing ('in') the swap takes whatever the latest location is
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location])

  // what is really on screen, for the timers below
  useEffect(() => {
    live.current.committed = shown
    live.current.pending = pending
  }, [shown, pending])

  // the next page is ready and the veil has been closed long enough: lift it (after a moment for a redirect that page makes at once)
  useEffect(() => {
    if (phase !== 'hold' || !holdOver || pending || held) return
    if (shown.key !== live.current.target.key) return
    const id = window.setTimeout(() => {
      const l = live.current
      if (l.phase !== 'hold' || l.pending || veilIsHeld() || l.committed.key !== l.target.key) return
      setPhase('out')
      announceVeilOpen()
      later(() => setPhase('idle'), LIFT_MS)
    }, SETTLE_MS)
    return () => window.clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, holdOver, pending, held, shown])

  useEffect(
    () => () => {
      clearTimers()
      delete document.documentElement.dataset.veil
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  // the address has moved on but the page on screen has not yet: that page is on its way out
  const leaving = location.key !== shown.key

  return (
    <>
      <LeavingContext.Provider value={leaving}>{children(shown)}</LeavingContext.Provider>
      <div className="veil" data-state={phase} aria-hidden="true">
        <TransitionMark size={64} />
      </div>
    </>
  )
}
