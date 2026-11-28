// The steps shown while a reading is made, and the plain-language "what is this for" of each one.
// (Six of them are the image-processing stages from the project plan; the landing page explains the same six.)

import type { HandSide, ImageStageKey, ProcessingEvent, StageKey } from '../../api/types'
import { STAGES } from '../../landing/content'
import { t } from '../../i18n'

export type StageMeta = {
  key: StageKey
  /** the step in the list */
  label: string
  /** the sentence under the title while this step runs */
  doing: string
  /** what the step is for */
  why: string
  /** true when the step produces a picture for the before/after slider */
  image: boolean
}

const why = (key: ImageStageKey) => STAGES.find((s) => s.key === key)!.body

export const STAGE_META: StageMeta[] = [
  { key: 'validate', label: t("Photos checked"), doing: t("Checking both photos…"), why: t("File type, file health, size, focus, lighting and whether a palm is really in view."), image: false },
  { key: 'resize', label: t("Resized"), doing: t("Bringing both photos to a standard size…"), why: t("Both photos are brought to the same working size so that they are treated in exactly the same way."), image: false },
  { key: 'gray', label: t("Grayscale"), doing: t("Taking the colour out…"), why: why('gray'), image: true },
  { key: 'blur', label: t("Gaussian smoothing"), doing: t("Smoothing away noise…"), why: why('blur'), image: true },
  { key: 'contrast', label: t("CLAHE contrast"), doing: t("Lifting the faint creases…"), why: why('contrast'), image: true },
  { key: 'edges', label: t("Canny edges"), doing: t("Tracing where brightness changes sharply…"), why: why('edges'), image: true },
  { key: 'threshold', label: t("Thresholding"), doing: t("Turning the creases into a black-and-white map…"), why: why('threshold'), image: true },
  { key: 'morphology', label: t("Morphology"), doing: t("Clearing specks and joining broken pieces…"), why: why('morphology'), image: true },
  { key: 'lines', label: t("Locating the lines"), doing: t("Looking for the main lines and naming each one…"), why: t("The main lines are located and named. Each one gets a status, and a line that cannot be seen is never invented."), image: false },
  { key: 'reading', label: t("Writing the reading"), doing: t("Writing the reading from what was found…"), why: t("Only the results, as words and never the photos, go to Gemini, an AI made by Google that must stay within what was actually found. Each passage it writes is checked, and one that fails is replaced by the app’s own wording."), image: false },
]

export const STAGE_BY_KEY = Object.fromEntries(STAGE_META.map((s) => [s.key, s])) as Record<StageKey, StageMeta>

/** Where one step has got to. `waiting` means it has not started. */
export type StageStatus = { state: 'waiting' | ProcessingEvent['state']; detail?: string }
export type StageMap = Record<StageKey, StageStatus>
/** The pictures of each finished step, one per hand, as data URLs. They live in this tab only. */
export type PreviewMap = Partial<Record<StageKey, Partial<Record<HandSide, string>>>>

export const initialStages = (): StageMap => Object.fromEntries(STAGE_META.map((s) => [s.key, { state: 'waiting' as const }])) as StageMap
