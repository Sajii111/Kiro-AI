import { useSyncExternalStore } from 'react'
import { API_URL, USE_MOCK } from '../config'

// Real loading progress for the intro gate: fonts, the 3D scene and (when a backend is configured)
// a wake-up ping to the API so a sleeping free host is already warm by the time someone enters.

type Task = 'fonts' | 'scene' | 'api'

const WEIGHTS: Record<Task, number> = { fonts: 0.2, scene: 0.65, api: 0.15 }
const values: Record<Task, number> = { fonts: 0, scene: 0, api: 0 }
const listeners = new Set<() => void>()
let snapshot = 0

function compute() {
  return (Object.keys(WEIGHTS) as Task[]).reduce((sum, k) => sum + WEIGHTS[k] * values[k], 0)
}

export function setLoad(task: Task, value: number) {
  values[task] = Math.max(values[task], Math.min(1, value))
  snapshot = compute()
  listeners.forEach((l) => l())
}

export function useLoadProgress(): number {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => snapshot,
  )
}

let started = false

/** Kick off the real work once. Safe to call more than once. */
export function startPreload() {
  if (started) return
  started = true

  // fonts
  const fontJobs = [
    document.fonts.load('400 1em "DM Sans Variable"'),
    document.fonts.load('400 1em "Fraunces Variable"'),
    document.fonts.load('italic 400 1em "Fraunces Variable"'),
  ]
  Promise.allSettled(fontJobs).then(() => setLoad('fonts', 1))

  // backend wake-up (best effort: never blocks the visitor)
  if (USE_MOCK || !API_URL) {
    setLoad('api', 1)
  } else {
    const ctrl = new AbortController()
    const timer = window.setTimeout(() => ctrl.abort(), 4000)
    fetch(`${API_URL}/health`, { signal: ctrl.signal, cache: 'no-store' })
      .catch(() => undefined)
      .finally(() => {
        window.clearTimeout(timer)
        setLoad('api', 1)
      })
  }

  // safety net: if the 3D scene never reports (no WebGL, say) don't trap anyone on the gate
  window.setTimeout(() => setLoad('scene', 1), 12000)
}
