// The steps shown while a reading is made, and the plain-language "what is this for" of each one.
// (Six of them are the image-processing stages from the project plan; the landing page explains the same six.)

import type { HandSide, ImageStageKey, ProcessingEvent, StageKey } from '../../api/types'
import { STAGES } from '../../landing/content'

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
  { key: 'validate', label: 'Photos checked', doing: 'Checking both photos…', why: 'File type, file health, size, focus, lighting and whether a palm is really in view.', image: false },
  { key: 'resize', label: 'Resized', doing: 'Bringing both photos to a standard size…', why: 'Both photos are brought to the same working size so that they are treated in exactly the same way.', image: false },
  { key: 'gray', label: 'Grayscale', doing: 'Taking the colour out…', why: why('gray'), image: true },
  { key: 'blur', label: 'Gaussian smoothing', doing: 'Smoothing away noise…', why: why('blur'), image: true },
  { key: 'contrast', label: 'CLAHE contrast', doing: 'Lifting the faint creases…', why: why('contrast'), image: true },
  { key: 'edges', label: 'Canny edges', doing: 'Tracing where brightness changes sharply…', why: why('edges'), image: true },
  { key: 'threshold', label: 'Thresholding', doing: 'Turning the creases into a black-and-white map…', why: why('threshold'), image: true },
  { key: 'morphology', label: 'Morphology', doing: 'Clearing specks and joining broken pieces…', why: why('morphology'), image: true },
  { key: 'lines', label: 'Locating the lines', doing: 'Looking for the main lines and naming each one…', why: 'The main lines are located and named. Each one gets a status, and a line that cannot be seen is never invented.', image: false },
  { key: 'reading', label: 'Writing the reading', doing: 'Writing the reading from what was found…', why: 'Only the results, as words and never the photos, go to Gemini, an AI made by Google that must stay within what was actually found. Each passage it writes is checked, and one that fails is replaced by the app’s own wording.', image: false },
]

export const STAGE_BY_KEY = Object.fromEntries(STAGE_META.map((s) => [s.key, s])) as Record<StageKey, StageMeta>

/** Where one step has got to. `waiting` means it has not started. */
export type StageStatus = { state: 'waiting' | ProcessingEvent['state']; detail?: string }
export type StageMap = Record<StageKey, StageStatus>
/** The pictures of each finished step, one per hand, as data URLs. They live in this tab only. */
export type PreviewMap = Partial<Record<StageKey, Partial<Record<HandSide, string>>>>

export const initialStages = (): StageMap => Object.fromEntries(STAGE_META.map((s) => [s.key, { state: 'waiting' as const }])) as StageMap
