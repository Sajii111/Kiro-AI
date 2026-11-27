// Words and colours for the palm lock, in one place so every screen says the same thing the same way.

import type { AttemptKind, PalmOutcome, UnlockEvent, UnlockStageKey } from '../../api/types'

/** What each step of a palm attempt has said so far. */
export type StepState = Partial<Record<UnlockStageKey, UnlockEvent>>

/** Folds one event into the steps shown so far. */
export function withEvent(steps: StepState, event: UnlockEvent): StepState {
  const before = steps[event.stage]
  // a "running" event starts the step afresh; a later one adds to what the step already said
  return { ...steps, [event.stage]: { ...(event.state === 'running' ? {} : before), ...event } }
}

/** The brief's exact outcome labels. */
export const OUTCOME_TITLE: Record<PalmOutcome, string> = {
  success: 'Authentication Successful',
  failed: 'Authentication Failed',
  invalid_image: 'Invalid Image',
}

/** Short labels for tables. */
export const OUTCOME_SHORT: Record<PalmOutcome, string> = {
  success: 'Successful',
  failed: 'Failed',
  invalid_image: 'Invalid image',
}

/** Tailwind classes per outcome. Never colour alone: each outcome also has its own icon and words. */
export const OUTCOME_TONE: Record<PalmOutcome, { text: string; bg: string; border: string; icon: 'check' | 'x' | 'alert' }> = {
  success: { text: 'text-detected', bg: 'bg-detected/15', border: 'border-detected/60', icon: 'check' },
  failed: { text: 'text-danger', bg: 'bg-danger/15', border: 'border-danger/60', icon: 'x' },
  invalid_image: { text: 'text-uncertain', bg: 'bg-uncertain/15', border: 'border-uncertain/60', icon: 'alert' },
}

export const KIND_LABEL: Record<AttemptKind, string> = {
  unlock: 'Unlock',
  test: 'Palm lab test',
  lock_added: 'Lock set up',
  lock_replaced: 'Lock replaced',
  lock_removed: 'Lock taken off',
  profile_deleted: 'Profile deleted',
}

export const STAGES: { key: UnlockStageKey; title: string; note: string }[] = [
  { key: 'checks', title: 'Photo checks', note: 'Sharp, well lit, one palm of the right hand, flat to the camera' },
  { key: 'roi', title: 'Palm square', note: 'The hand is straightened and a square is cut from the middle of the palm' },
  { key: 'prep', title: 'Preprocessing', note: 'Green channel, a light blur, CLAHE, shading taken out, normalised' },
  { key: 'features', title: 'Features', note: 'A: the crease map · B: the competitive code (six Gabor filters)' },
  { key: 'match', title: 'Matching', note: 'Compared with every photo the lock was made from; the best match counts' },
]

export const METHOD_NAME: Record<string, string> = {
  crease: 'Crease map',
  compcode: 'Competitive code',
  lbp: 'LBP (spare)',
}

export const fmtScore = (n: number | undefined) => (n === undefined ? '–' : n.toFixed(2))
