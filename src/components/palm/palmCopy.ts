// Words and colours for the palm lock, in one place so every screen says the same thing the same way.

import type { AttemptKind, PalmOutcome, UnlockEvent, UnlockStageKey } from '../../api/types'
import { t } from '../../i18n'

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
  success: t("Authentication Successful"),
  failed: t("Authentication Failed"),
  invalid_image: t("Invalid Image"),
}

/** Short labels for tables. */
export const OUTCOME_SHORT: Record<PalmOutcome, string> = {
  success: t("Successful"),
  failed: t("Failed"),
  invalid_image: t("Invalid image"),
}

/** Tailwind classes per outcome. Never colour alone: each outcome also has its own icon and words. */
export const OUTCOME_TONE: Record<PalmOutcome, { text: string; bg: string; border: string; icon: 'check' | 'x' | 'alert' }> = {
  success: { text: 'text-detected', bg: 'bg-detected/15', border: 'border-detected/60', icon: 'check' },
  failed: { text: 'text-danger', bg: 'bg-danger/15', border: 'border-danger/60', icon: 'x' },
  invalid_image: { text: 'text-uncertain', bg: 'bg-uncertain/15', border: 'border-uncertain/60', icon: 'alert' },
}

export const KIND_LABEL: Record<AttemptKind, string> = {
  unlock: t("Unlock"),
  test: t("Palm lab test"),
  lock_added: t("Lock set up"),
  lock_replaced: t("Lock replaced"),
  lock_removed: t("Lock taken off"),
  profile_deleted: t("Profile deleted"),
}

export const STAGES: { key: UnlockStageKey; title: string; note: string }[] = [
  { key: 'checks', title: t("Photo checks"), note: t("Sharp, well lit, one palm of the right hand, flat to the camera") },
  { key: 'roi', title: t("Palm square"), note: t("The hand is straightened and a square is cut from the middle of the palm") },
  { key: 'prep', title: t("Preprocessing"), note: t("Green channel, a light blur, CLAHE, shading taken out, normalised") },
  { key: 'features', title: t("Features"), note: t("A: the crease map · B: the competitive code (six Gabor filters)") },
  { key: 'match', title: t("Matching"), note: t("Compared with every photo the lock was made from; the best match counts") },
]

export const METHOD_NAME: Record<string, string> = {
  crease: t("Crease map"),
  compcode: t("Competitive code"),
  lbp: t("LBP (spare)"),
}

export const fmtScore = (n: number | undefined) => (n === undefined ? '–' : n.toFixed(2))
