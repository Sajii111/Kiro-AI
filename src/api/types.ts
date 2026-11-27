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
   * is right, so the screens call it "score". null when status is "not_visible".
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

/** One principal line, both hands. What was seen is kept apart from what the line foretells (the `traditional` fields). */
export type ReportSection = {
  featureId: FeatureId
  title: string
  /** What was seen in each photo. Visual only. */
  observed: Record<HandSide, SideObservation>
  /** What the line foretells, in the reader's voice (the field keeps its older name). null where the line was not seen: nothing is claimed. */
  traditional: Record<HandSide, string | null>
  /** How the two hands compare on this line. null when it cannot be compared. */
  comparison: string | null
}

/** The shape of the hand, both hands. Same rule as a line: what was seen is kept apart from what the shape foretells. */
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
 * One life theme, read from the lines (and hand shape) that WERE detected and told as a fortune: confident, in soft
 * time only (no dates, no ages, no sums). Every theme names what it rests on and says what it left out. None of it is advice.
 */
export type ThemeSection = {
  themeId: ThemeId
  /** "Personality", "Career and professional life", "Financial and prosperity themes", "Relationships and emotional life", "Future outlook" */
  title: string
  /** Always "traditional" (the field's older name). The screens label every theme "What your lines foretell", so it can never pass for something seen in the photo. */
  label: 'traditional'
  /** What the lines foretell, written only from `basedOn`. null when nothing it rests on was clearly seen: nothing is claimed. */
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
  /** What the person called this reading, when they did. The screens call it by its date when it has no name. Never sent to Gemini. */
  name?: string
  hands: Record<HandSide, HandAnalysis>
  report: Report
  meta: ReadingMeta
}

/** What lists show. */
export type ReadingSummary = {
  id: string
  profileId: string
  profileName: string
  /** The reading's own name, when it has one */
  name?: string
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
  /** 0 and null while the profile is locked: how much it holds is the profile's own business */
  readingCount: number
  lastReadingAt: string | null
  /** the palm lock, or null when the profile has none */
  lock: LockSummary | null
  /** true while the profile has a lock and is not open in this browser: its readings and chats cannot be reached */
  locked: boolean
  /** true for the one profile open in this browser (the one the app is working in) */
  open: boolean
}

// ------------------------------------------------------------------ palm locks (ICA 02)

/** What may be known about a profile's palm lock. Never the template itself. */
export type LockSummary = {
  side: HandSide
  createdAt: string
  /** how many photos the lock was made from */
  samples: number
  engineVersion: string
}

/** The three outcomes of a palm attempt. */
export type PalmOutcome = 'success' | 'failed' | 'invalid_image'

export type AttemptKind = 'unlock' | 'test' | 'lock_added' | 'lock_replaced' | 'lock_removed' | 'profile_deleted'

/** One line of the attempt log. Numbers and words only: never a photo, never a template. */
export type Attempt = {
  /** the attempt ID */
  id: string
  /** the user ID: the hand profile the attempt was for */
  profileId: string
  /** its name at the time */
  profileName: string
  kind: AttemptKind
  at: string
  outcome?: PalmOutcome
  score?: number
  threshold?: number
  /** each deciding method's normalised score, 0 to 1 */
  methods?: Record<string, number>
  reason: string
  /** why the photo could not be judged, for an invalid image */
  problem?: string
  hand?: HandSide
  durationMs?: number
  engineVersion: string
  /** false while the threshold is a placeholder */
  calibrated?: boolean
  /** how a lock was taken off or a locked profile deleted */
  via?: 'palm' | 'password'
}

export type UnlockStageKey = 'checks' | 'roi' | 'prep' | 'features' | 'match'

/** One step of a palm attempt, as it happens. */
export type UnlockEvent = {
  stage: UnlockStageKey
  state: StageState
  detail?: string
  /** a small picture of what the step made (data: URL) */
  preview?: string
  /** how long the step took */
  ms?: number
}

/** The answer to a palm attempt. */
export type PalmResult = {
  attemptId: string
  profileId: string
  outcome: PalmOutcome
  /** "Authentication Successful", "Authentication Failed" or "Invalid Image" */
  title: string
  /** the fused score, 0 to 1; left out for an invalid image */
  score?: number
  threshold: number
  methods: Record<string, number>
  /** every method's own similarity before normalising, the spare included */
  raw: Record<string, number>
  reason: string
  problem?: string
  hand: HandSide
  durationMs: number
  at: string
  calibrated: boolean
  engineVersion: string
  /** true when this attempt opened the profile (a successful unlock, never a test) */
  opened: boolean
  bestSample?: number
  /** set when this failure locked the profile out */
  lockedUntil?: number
}

export type PalmMethod = { id: string; name: string; weight: number; description: string }

/** How the palm lock decides. Read-only: the threshold changes only by calibrating on validation photos. */
export type PalmLockInfo = {
  available: boolean
  note: string | null
  engineVersion: string
  configHash: string
  calibrated: boolean
  threshold: number
  calibrationSource: string
  measured: Record<string, string | number>
  methods: PalmMethod[]
  policy: { failures: number; windowMinutes: number; lockoutMinutes: number; idleMinutes: number; enrolMin: number; enrolMax: number }
  roiSize: number
}

export type LockInput = {
  side: HandSide
  /** the owner (or, for "other", the person) agreed to their palm being used as a lock */
  consent: boolean
  /** 3 to 5 photos of the same palm, already shrunk by the browser */
  photos: Blob[]
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
  /** no longer produced: love, work and the road ahead are now foretold. Kept so older saved chats still type-check. */
  | 'prediction'
  | 'not_seen'
  | 'off_topic'

export type MessageFlags = {
  /** the answer carries the "an old art, not a science" reminder */
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
  /** Optional name for the reading, up to 40 characters, kept simple (see validateReadingName). Left out means no name. */
  name?: string
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
  /** A locked profile that is not open needs the account password. */
  deleteProfile(id: string, password?: string): Promise<DeleteSummary>

  // ---- palm locks
  /** Opens a profile without a lock (or one already unlocked) in this browser. The one open before is closed. */
  openProfile(id: string): Promise<HandProfile>
  /** Closes the open profile; a locked one locks again. */
  closeProfile(): Promise<void>
  /** Locks a profile with 3 to 5 photos of one palm. The profile stays open afterwards. */
  lockProfile(id: string, input: LockInput): Promise<HandProfile>
  /** Takes the lock off: free while the profile is open, otherwise with the account password. */
  removeLock(id: string, password?: string): Promise<HandProfile>
  /** One photo against the lock. `onEvent` fires as each step starts and ends. A success opens the profile. */
  unlockProfile(id: string, photo: Blob, onEvent: (event: UnlockEvent) => void, signal?: AbortSignal): Promise<PalmResult>
  /** The Palm lab's test: one photo against the lock of a typed user ID. Opens nothing. */
  testVerification(userId: string, photo: Blob, onEvent: (event: UnlockEvent) => void, signal?: AbortSignal): Promise<PalmResult>
  palmLockInfo(): Promise<PalmLockInfo>
  /** The attempt log, newest first. */
  listActivity(profileId?: string): Promise<Attempt[]>

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
  /** Gives a reading a new name. An empty name takes the name away. Answers with the row a list shows. */
  renameReading(id: string, name: string): Promise<ReadingSummary>
  deleteReading(id: string): Promise<DeleteSummary>

  listConversations(filter?: { readingId?: string; profileId?: string }): Promise<Conversation[]>
  createConversation(readingId: string): Promise<Conversation>
  getConversation(id: string): Promise<ConversationWithMessages>
  /** Sends one question. The reading, the report and the earlier messages are attached by the server, not the browser. */
  sendMessage(conversationId: string, text: string): Promise<{ user: Message; assistant: Message }>
  deleteConversation(id: string): Promise<DeleteSummary>

  exportData(): Promise<ExportBundle>
  /** With a locked profile that is not open, the account password is needed. */
  deleteAllData(password?: string): Promise<DeleteSummary>

  /** Only present on the sample backend. */
  demo?: DemoTools
}
