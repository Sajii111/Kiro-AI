// THE CONTRACT between the app and the backend.
//
// Every shape the backend returns is described here, and the sample (mock) backend produces exactly these
// shapes, so switching to the real FastAPI server changes nothing on screen. docs/API_CONTRACT.md explains
// the endpoints. Field names, statuses and the per-feature record follow the "feature result format" in the
// project plan: feature name, status (detected / uncertain / not visible), normalised path points,
// confidence, a short visual observation and the detection method version.
//
// Rules the shapes help to keep:
//   - One account owns many hand profiles. A reading belongs to a profile. A conversation belongs to one reading.
//   - Photos are never part of a saved record. Only structured findings, the report and the chat are stored.
//   - A feature that was not clearly seen says so (uncertain / not_visible) and carries no invented detail.

import type { FeatureStatus } from '../lib/status'

export type { FeatureStatus }

export type HandSide = 'left' | 'right'

/** The five principal lines. */
export type FeatureId = 'heart' | 'head' | 'life' | 'fate' | 'sun'

/** A point on the analysed photo as fractions of its width and height (0 to 1), origin at the top left. */
export type NormPoint = [number, number]

/** A box in the same 0 to 1 photo space. */
export type NormBox = { x: number; y: number; w: number; h: number }

// ------------------------------------------------------------------ photo checks

export type CheckId = 'file_type' | 'integrity' | 'dimensions' | 'blur' | 'lighting' | 'palm_visible'
export type CheckStatus = 'pass' | 'warn' | 'fail'

/** One line of the photo check list. `message` is plain language and says what to do next. */
export type PhotoCheck = {
  id: CheckId
  label: string
  status: CheckStatus
  message: string
}

export type ValidationResult = {
  side: HandSide
  /** false when at least one check failed. Warnings do not block. */
  ok: boolean
  /** size of the photo that was checked */
  width: number
  height: number
  checks: PhotoCheck[]
}

export type QualityLevel = 'good' | 'fair' | 'poor'

export type PhotoQuality = {
  sharpness: QualityLevel
  lighting: QualityLevel
  resolution: QualityLevel
  palmVisible: boolean
  /** 0 (unusable) to 1 (ideal) */
  score: number
}

// ------------------------------------------------------------------ findings

export type FeatureTraits = {
  length?: 'short' | 'medium' | 'long'
  curve?: 'straight' | 'gentle' | 'pronounced'
  clarity?: 'faint' | 'clear' | 'deep'
}

/** What the detector found for one line on one hand. */
export type FeatureResult = {
  id: FeatureId
  /** "Heart line" */
  name: string
  status: FeatureStatus
  /** Points along the line, 12 to 40 of them. Empty when status is "not_visible". */
  path: NormPoint[]
  /** The area that was searched. For "not_visible" this is all there is to draw. */
  searchArea: NormBox
  /**
   * The detection score, 0 to 1: how strongly the detector matched this line. It is NOT the chance that a reading
   * is right, so the screens call it "detection score". null when status is "not_visible".
   */
  confidence: number | null
  /** One or two plain sentences about what is visible. Visual only: no meaning attached. */
  observation: string
  /** Only what could be judged. An uncertain line carries clarity only; a missing one carries nothing. */
  traits: FeatureTraits
  /** Detection method and version, e.g. "opencv-ridge 0.4.1" */
  method: string
}

/** What can be judged about the shape of the hand: how broad the palm is, and how long the fingers are against it. */
export type PalmShapeTraits = {
  palm?: 'square' | 'long'
  fingers?: 'short' | 'long'
}

/**
 * The shape of the hand. Visual only, like a line's observation: the traditional "element" a shape is linked with
 * (earth, air, water, fire) is said in the report, never here.
 */
export type PalmShape = {
  status: FeatureStatus
  /** Only what could be judged. An uncertain shape carries nothing; a missing one carries nothing. */
  traits: PalmShapeTraits
  /** Palm width divided by palm length, and finger length divided by palm length. null when not measured. */
  palmRatio: number | null
  fingerRatio: number | null
  /** The detection score, 0 to 1. null when status is "not_visible". */
  confidence: number | null
  /** One or two plain sentences about what is visible. */
  observation: string
  /** Detection method and version */
  method: string
}

/**
 * A crease that was found but does not match any of the five principal lines. It is shown on the hand and counted,
 * but it has no name and nothing is said about its meaning.
 */
export type OtherCrease = {
  /** stable within one reading, e.g. "c1" */
  id: string
  /** 8 to 40 points along the crease */
  path: NormPoint[]
  /** The detection score, 0 to 1 */
  confidence: number
  /** One plain sentence about where it is and how it looks. */
  observation: string
}

export type HandAnalysis = {
  side: HandSide
  /** Size of the analysed photo. The normalised coordinates above refer to this picture. */
  photo: { width: number; height: number }
  quality: PhotoQuality
  /**
   * The outline of the hand found in the photo, as a closed shape. It is what lets a saved reading redraw a
   * schematic sketch of the hand once the photo is gone. null when no outline could be found.
   */
  outline: NormPoint[] | null
  features: FeatureResult[]
  /** The overall shape of the hand */
  palmShape: PalmShape
  /** Strong creases left over after the five principal lines were named. Empty when there are none. */
  otherCreases: OtherCrease[]
  methodVersion: string
}

// ------------------------------------------------------------------ report

export type SideObservation = { status: FeatureStatus; text: string }

/** One principal line, both hands. What was seen is kept apart from what the tradition says. */
export type ReportSection = {
  featureId: FeatureId
  title: string
  /** What was seen in each photo. Visual only. */
  observed: Record<HandSide, SideObservation>
  /** What the tradition says about it. null where the line was not seen: nothing is claimed. */
  traditional: Record<HandSide, string | null>
  /** How the two hands compare on this line. null when it cannot be compared. */
  comparison: string | null
}

/** The shape of the hand, both hands. Same rule as a line: what was seen is kept apart from what the tradition says. */
export type ShapeSection = {
  observed: Record<HandSide, SideObservation>
  /** The traditional "element" of the hand (earth, air, water, fire). null where the shape was not judged. */
  traditional: Record<HandSide, string | null>
  comparison: string | null
}

export type ThemeId = 'personality' | 'career' | 'financial' | 'relationships' | 'future'

/** What a theme can rest on: one of the five lines, or the shape of the hand. */
export type ThemeSource = FeatureId | 'shape'

/**
 * One life theme, read the traditional way from the lines (and hand shape) that WERE detected. Every theme is
 * labelled traditional, names what it rests on, and says what it left out. None of it is advice or a prediction.
 */
export type ThemeSection = {
  themeId: ThemeId
  /** "Personality", "Career and professional life", "Financial and prosperity themes", "Relationships and emotional life", "Future outlook" */
  title: string
  /** Always "traditional". The screens label every theme this way, so it can never pass for a finding or a forecast. */
  label: 'traditional'
  /** What the tradition says, written only from `basedOn`. null when nothing it rests on was clearly seen: nothing is claimed. */
  traditional: string | null
  /** The sources that were detected on at least one hand and used, in the order the tradition lists them */
  basedOn: ThemeSource[]
  /** Sources this theme normally rests on but that were only uncertain, or not visible, on both hands, so were not used */
  leftOut: ThemeSource[]
}

export type Report = {
  summary: string
  /** Exactly five, one per line. This is the "by line" view. */
  sections: ReportSection[]
  /** Exactly five, in the order personality, career, financial, relationships, future. This is the "by theme" view. */
  themes: ThemeSection[]
  /** The shape of the hand. */
  shape: ShapeSection
  /** Plain statements about anything unclear or missing, and about photo quality. */
  uncertainty: string[]
  disclaimer: string
  generatedAt: string
}

export type ReadingMeta = {
  /** Who wrote the words: "gemini" when Gemini wrote at least one passage, "knowledge-base" when the fixed wording did, "sample" (or "mock") for a sample reading. */
  provider: string
  model: string
  /** Version of the curated palmistry knowledge base the report was grounded in */
  knowledgeBase: string
  /** Version of the instructions given to the model */
  prompt: string
  /** Version of the image-processing pipeline */
  pipeline: string
  /** true when this reading came from the sample backend, not real analysis */
  mock: boolean
  /** One plain sentence on how the words were written: which passages Gemini wrote, and why any came from the knowledge base instead. Left out when there is nothing to say. */
  note?: string
}

export type Reading = {
  id: string
  profileId: string
  createdAt: string
  hands: Record<HandSide, HandAnalysis>
  report: Report
  meta: ReadingMeta
}

/** What lists show. */
export type ReadingSummary = {
  id: string
  profileId: string
  profileName: string
  createdAt: string
  /** Counts across both hands (10 features in total) */
  counts: Record<FeatureStatus, number>
  headline: string
  conversationCount: number
}

// ------------------------------------------------------------------ profiles

export type HandProfile = {
  id: string
  /** Kept simple on purpose: a first name or nickname */
  name: string
  /** "self" = my own hands. "other" = someone who agreed to it. */
  owner: 'self' | 'other'
  /** For "other": the person agreed to their palms being uploaded */
  consent: boolean
  createdAt: string
  readingCount: number
  lastReadingAt: string | null
}

export type NewProfileInput = {
  name: string
  owner: 'self' | 'other'
  consent: boolean
}

// ------------------------------------------------------------------ chat

export type MessageRefs = {
  featureIds?: FeatureId[]
  side?: HandSide
  /** which part of the report the answer leaned on */
  section?: FeatureId | 'summary' | 'comparison' | 'uncertainty' | 'themes' | 'shape'
}

export type BoundaryKind =
  | 'medical'
  | 'financial'
  | 'employment'
  | 'relationship'
  | 'lifespan'
  /** asked to predict what will happen */
  | 'prediction'
  | 'not_seen'
  | 'off_topic'

export type MessageFlags = {
  /** the answer carries the traditional / entertainment reminder */
  disclaimer?: boolean
  /** why the assistant declined to go further */
  boundary?: BoundaryKind
  /** the question was about someone else; offer a switch to that profile */
  switchProfileId?: string
}

export type Message = {
  id: string
  conversationId: string
  role: 'user' | 'assistant'
  text: string
  createdAt: string
  refs?: MessageRefs
  flags?: MessageFlags
  /** Who wrote an assistant answer: "gemini" (the language model, and the answer passed the checks) or "knowledge-base" (the fixed wording, used because Gemini was expected to answer and did not). Left out when the model was never involved: a boundary, a greeting, no Gemini key. */
  source?: 'gemini' | 'knowledge-base'
  /** Why Gemini did not answer, in one sentence. Left out when there is nothing to say. */
  note?: string
}

export type Conversation = {
  id: string
  readingId: string
  profileId: string
  title: string
  createdAt: string
  updatedAt: string
  messageCount: number
}

export type ConversationWithMessages = Conversation & { messages: Message[] }

// ------------------------------------------------------------------ processing

/**
 * The steps shown to the user while a reading is made, in this order. The six image steps (gray to morphology) each
 * come with a picture for the before/after slider.
 */
export type StageKey =
  | 'validate'
  | 'resize'
  | 'gray'
  | 'blur'
  | 'contrast'
  | 'edges'
  | 'threshold'
  | 'morphology'
  | 'lines'
  | 'reading'

/** The steps that carry a picture. */
export type ImageStageKey = 'gray' | 'blur' | 'contrast' | 'edges' | 'threshold' | 'morphology'
export type StageState = 'running' | 'done' | 'failed'

export type ProcessingEvent = {
  stage: StageKey
  state: StageState
  /** a short line about what happened, e.g. "Located 4 lines on the left hand" */
  detail?: string
  /**
   * Small pictures of this step for the before/after slider, as data URLs, one per hand.
   * They exist only for the length of this request and are never stored.
   */
  previews?: Partial<Record<HandSide, string>>
}

export type NewReadingInput = {
  profileId: string
  left: Blob
  right: Blob
  /**
   * True when that photo is one of the website's built-in sample drawings ("Try a sample"). The server then judges it
   * with the simple check and makes a clearly labelled sample reading, because a hand finder cannot find a hand in a
   * sketch. A real photo never sets it, and setting it can only make a reading less real, never more.
   */
  leftSample?: boolean
  rightSample?: boolean
}

// ------------------------------------------------------------------ accounts and sessions

export type UserInfo = { id: string; email: string; displayName: string }

export type Session =
  | { kind: 'user'; user: UserInfo }
  /** Temporary. `expiresAt` is a millisecond timestamp. */
  | { kind: 'guest'; guestId: string; expiresAt: number }

/** What a guest session holds, so the import offer can say exactly what would be copied. */
export type DataCounts = {
  profiles: number
  readings: number
  conversations: number
  messages: number
}

export type RestoreResult = {
  session: Session | null
  /** set when a guest session ended by itself since the last visit */
  guestExpired?: boolean
}

export type SignUpInput = { email: string; password: string; displayName: string }
export type SignInInput = { email: string; password: string }

export interface AuthApi {
  restore(): Promise<RestoreResult>
  signUp(input: SignUpInput): Promise<Session>
  signIn(input: SignInInput): Promise<Session>
  startGuest(): Promise<Session>
  signOut(): Promise<void>
  /** What is waiting in a guest session, or null when there is nothing. */
  guestSummary(): Promise<DataCounts | null>
  /** Copies the guest data into the signed-in account. Only ever called after the person said yes. */
  importGuest(): Promise<DataCounts>
  /** Throws the guest data away. */
  discardGuest(): Promise<void>
}

// ------------------------------------------------------------------ the whole API

/** Counts of what a delete removed. A profile delete cascades: profile, readings, conversations, messages. */
export type DeleteSummary = DataCounts

export type ExportBundle = {
  exportedAt: string
  profiles: HandProfile[]
  readings: Reading[]
  conversations: ConversationWithMessages[]
}

/** Helpers that exist only on the sample backend, for demonstrations and tests. */
export interface DemoTools {
  loadSamples(): Promise<void>
  reset(): Promise<void>
  expireGuest(): Promise<void>
  setFailNext(on: boolean): void
  failNext(): boolean
}

/**
 * Where accounts are kept (from GET /v1/health). "firestore": in the server's online database, so they last. "memory": in the
 * server's memory only, gone when it restarts. "browser": the sample backend, which keeps everything in this browser.
 */
export type AccountStorage = 'firestore' | 'memory' | 'browser'

export interface Api {
  auth: AuthApi

  /** Where this server keeps accounts. Never fails: an unknown answer counts as "memory". */
  accountStorage(): Promise<AccountStorage>

  listProfiles(): Promise<HandProfile[]>
  createProfile(input: NewProfileInput): Promise<HandProfile>
  renameProfile(id: string, name: string): Promise<HandProfile>
  deleteProfile(id: string): Promise<DeleteSummary>

  /**
   * Checks one photo (already shrunk by the browser). The photo is discarded straight after.
   * `sample` says the photo is one of the built-in sample drawings (see NewReadingInput).
   */
  validatePhoto(side: HandSide, photo: Blob, options?: { sample?: boolean }): Promise<ValidationResult>
  /**
   * Runs the whole pipeline on both photos and returns the finished reading. `onEvent` fires as each step
   * starts and finishes. Photos are processed in memory and discarded afterwards, also when it fails.
   */
  createReading(input: NewReadingInput, onEvent: (event: ProcessingEvent) => void, signal?: AbortSignal): Promise<Reading>
  listReadings(profileId?: string): Promise<ReadingSummary[]>
  getReading(id: string): Promise<Reading>
  deleteReading(id: string): Promise<DeleteSummary>

  listConversations(filter?: { readingId?: string; profileId?: string }): Promise<Conversation[]>
  createConversation(readingId: string): Promise<Conversation>
  getConversation(id: string): Promise<ConversationWithMessages>
  /** Sends one question. The reading, the report and the earlier messages are attached by the server, not the browser. */
  sendMessage(conversationId: string, text: string): Promise<{ user: Message; assistant: Message }>
  deleteConversation(id: string): Promise<DeleteSummary>

  exportData(): Promise<ExportBundle>
  deleteAllData(): Promise<DeleteSummary>

  /** Only present on the sample backend. */
  demo?: DemoTools
}
