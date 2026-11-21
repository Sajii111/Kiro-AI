import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../api/errors'

type Dep = string | number | boolean | null | undefined

/**
 * Loads something from the API and keeps track of "loading" and "error".
 * `deps` say when to load again (an id changed, say). `reload()` loads again on demand and keeps showing the
 * old result meanwhile. A result for different deps is never shown, so one reading's data cannot flash up
 * on another reading's page.
 */
export function useResource<T>(load: () => Promise<T>, deps: readonly Dep[]) {
  const depsKey = deps.join('|')
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })

  const [tick, setTick] = useState(0)
  const [state, setState] = useState<{ key: string; data?: T; error?: string } | null>(null)
  const key = `${depsKey}#${tick}`

  useEffect(() => {
    let live = true
    loadRef
      .current()
      .then((data) => live && setState({ key, data }))
      .catch((e: unknown) => live && setState({ key, error: errorMessage(e) }))
    return () => {
      live = false
    }
  }, [key])

  const sameDeps = !!state && state.key.startsWith(`${depsKey}#`)
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return {
    data: sameDeps ? state.data : undefined,
    error: state && state.key === key ? state.error : undefined,
    loading: !state || state.key !== key,
    reload,
  }
}
