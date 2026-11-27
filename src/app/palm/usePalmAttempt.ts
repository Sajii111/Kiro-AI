import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, errorMessage, isAbort } from '../../api/errors'
import type { PalmResult, UnlockEvent } from '../../api/types'
import { withEvent, type StepState } from '../../components/palm/palmCopy'

export type AttemptState =
  | { phase: 'idle' }
  | { phase: 'running'; steps: StepState }
  | { phase: 'done'; steps: StepState; result: PalmResult }
  | { phase: 'error'; steps: StepState; message: string; lockedUntil?: number }

/** Runs one palm attempt (an unlock or a Palm lab test) and keeps its live steps and its result. Leaving the page stops it. */
export function usePalmAttempt(run: (onEvent: (e: UnlockEvent) => void, signal: AbortSignal) => Promise<PalmResult>) {
  const [state, setState] = useState<AttemptState>({ phase: 'idle' })
  const abort = useRef<AbortController | null>(null)

  useEffect(() => () => abort.current?.abort(), [])

  const start = useCallback(async () => {
    abort.current?.abort()
    const controller = new AbortController()
    abort.current = controller
    let steps: StepState = {}
    setState({ phase: 'running', steps })
    try {
      const result = await run((event) => {
        steps = withEvent(steps, event)
        setState({ phase: 'running', steps })
      }, controller.signal)
      setState({ phase: 'done', steps, result })
      return result
    } catch (e) {
      if (isAbort(e)) return null
      setState({ phase: 'error', steps, message: errorMessage(e), lockedUntil: e instanceof ApiError ? e.details.lockedUntil : undefined })
      return null
    }
  }, [run])

  const reset = useCallback(() => {
    abort.current?.abort()
    setState({ phase: 'idle' })
  }, [])

  return { state, start, reset }
}
