// SAMPLE BACKEND ONLY. The whole API, answered from this browser instead of a server.
//
// It follows the same contract as the real backend (src/api/types.ts), including the rules:
//   - a reading belongs to a profile, a conversation belongs to one reading,
//   - deleting a profile removes its readings, conversations, messages and findings,
//   - photos are used in memory for the length of one request and never stored.
// The photo steps shown while a reading is made (grayscale, smoothing, CLAHE, Canny, thresholding, morphology) are
// drawn here from the chosen photo purely as an illustration. The real pipeline runs OpenCV on the server.

import { runPipeline } from '../../lib/stageFilters'
import { PROFILE_NAME_MAX, MESSAGE_MAX, cleanReadingName, validateProfileName, validateReadingName } from '../../lib/validate'
import { ApiError } from '../errors'
import type {
  Api,
  Attempt,
  AttemptKind,
  Conversation,
  ConversationWithMessages,
  DeleteSummary,
  HandProfile,
  HandSide,
  ImageStageKey,
  PalmResult,
  ProcessingEvent,
  Reading,
  ReadingSummary,
  StageKey,
  UnlockEvent,
} from '../types'
import { currentDisplayName, expireGuestNow, mockAuth, passwordMatches } from './auth'
import { MOCK_ENGINE, postMessage, toProfile } from './convo'
import { compare, fingerprint, MOCK_THRESHOLD, outcomeOf, photoProblem, stepPictures } from './palm'
import { countStatuses } from '../../lib/readings'
import { headlineFor } from './generate'
import { buildValidation, measurePhoto, qualityFrom } from './measure'
import { loadSampleData, makeReading } from './samples'
import { clearScope, countsOf, data, dropConversations, dropReadings, getScope, mutate, newId, openProfileId, setOpenProfile, type MockLock, type StoreData } from './store'

export const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })

/** lets the screen paint before a heavy step starts */
const nextFrame = () => new Promise<void>((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)))

const LATENCY = 140
let failNext = false

const none: DeleteSummary = { profiles: 0, readings: 0, conversations: 0, messages: 0 }

async function previewsFor(blob: Blob): Promise<Record<ImageStageKey, string>> {
  const bitmap = await createImageBitmap(blob)
  const stages = runPipeline(bitmap, 560)
  bitmap.close()
  const url = (c: HTMLCanvasElement) => c.toDataURL('image/jpeg', 0.82)
  return {
    gray: url(stages.gray),
    blur: url(stages.blur),
    contrast: url(stages.contrast),
    edges: url(stages.edges),
    threshold: url(stages.threshold),
    morphology: url(stages.morphology),
  }
}

const find = {
  profile(id: string) {
    const p = data().profiles.find((x) => x.id === id)
    if (!p) throw new ApiError('not_found', 'That hand profile could not be found.')
    return p
  },
  reading(id: string) {
    const r = data().readings.find((x) => x.id === id)
    if (!r) throw new ApiError('not_found', 'That reading could not be found.')
    return r
  },
  conversation(id: string) {
    const c = data().conversations.find((x) => x.id === id)
    if (!c) throw new ApiError('not_found', 'That chat could not be found.')
    return c
  },
}

/** What a list shows about one reading. */
function summaryOf(d: ReturnType<typeof data>, r: Reading): ReadingSummary {
  return {
    id: r.id,
    profileId: r.profileId,
    profileName: d.profiles.find((p) => p.id === r.profileId)?.name ?? 'Unknown',
    ...(r.name ? { name: r.name } : {}),
    createdAt: r.createdAt,
    counts: countStatuses(r),
    headline: headlineFor(r),
    conversationCount: d.conversations.filter((c) => c.readingId === r.id).length,
  }
}

// ---------------------------------------------------------------- palm locks: what a session may reach

const FAILURES = 5
const WINDOW_MS = 10 * 60_000
const LOCKOUT_MS = 5 * 60_000

function lockOf(d: StoreData, profileId: string): MockLock | undefined {
  return d.locks.find((k) => k.profileId === profileId)
}

function canReach(d: StoreData, profileId: string, openId = openProfileId()): boolean {
  return !lockOf(d, profileId) || profileId === openId
}

function requireReach(profileId: string) {
  const d = data()
  if (!canReach(d, profileId)) {
    const name = d.profiles.find((p) => p.id === profileId)?.name ?? 'This profile'
    throw new ApiError('locked', `“${name}” is locked with a palm. Unlock it with its palm first.`, { profileId })
  }
}

function logLine(d: StoreData, profileId: string, kind: AttemptKind, reason: string, extra: Partial<Attempt> = {}): Attempt {
  const line: Attempt = {
    id: newId('att'),
    profileId,
    profileName: d.profiles.find((p) => p.id === profileId)?.name ?? 'Unknown',
    kind,
    at: new Date().toISOString(),
    reason,
    engineVersion: MOCK_ENGINE,
    ...extra,
  }
  d.attempts.push(line)
  if (d.attempts.length > 500) d.attempts = d.attempts.slice(-500)
  return line
}

function requirePassword(password: string | undefined) {
  if (!password) throw new ApiError('forbidden', 'Type your account password to do this without the palm.')
  if (!passwordMatches(password)) throw new ApiError('forbidden', 'That password is not right. Please try again.')
}

/** One palm attempt of the sample backend: the same steps and outcomes as the server's, from thumbnails. */
async function mockAttempt(profileId: string, photo: Blob, kind: 'unlock' | 'test', onEvent: (e: UnlockEvent) => void, signal?: AbortSignal): Promise<PalmResult> {
  const d = data()
  const profile = find.profile(profileId)
  const lock = lockOf(d, profileId)
  if (!lock) throw new ApiError('invalid', `“${profile.name}” has no palm lock, so there is nothing to compare the photo with.`)
  if (lock.lockedUntil && lock.lockedUntil > Date.now()) {
    const minutes = Math.max(1, Math.round((lock.lockedUntil - Date.now()) / 60_000))
    throw new ApiError('locked_out', `Too many palm attempts failed on this profile, so it is locked for now. Try again in about ${minutes} minute${minutes === 1 ? '' : 's'}.`, { lockedUntil: lock.lockedUntil, profileId })
  }
  const t0 = performance.now()
  const step = (stage: UnlockEvent['stage'], state: UnlockEvent['state'], detail?: string, preview?: string) =>
    onEvent({ stage, state, ...(detail ? { detail } : {}), ...(preview ? { preview } : {}), ms: Math.round(performance.now() - t0) })

  step('checks', 'running')
  const problem = await photoProblem(photo, lock.side)
  await wait(400, signal)
  let outcome: PalmResult['outcome']
  let score: number | undefined
  let best: number | undefined
  let corr = 0
  if (problem) {
    step('checks', 'failed', problem)
    outcome = 'invalid_image'
  } else {
    const pictures = await stepPictures(photo)
    step('checks', 'done', `The photo passed the checks (sample backend: the hand side is taken on trust)`)
    for (const [stage, detail] of [
      ['roi', 'The middle of the photo (the server cuts the square from the palm itself)'],
      ['prep', 'Grey, lightly blurred, contrast evened out'],
      ['features', 'A stand-in picture: the server draws its crease map and competitive code here'],
    ] as const) {
      step(stage, 'running')
      await wait(450, signal)
      step(stage, 'done', detail, pictures[stage])
    }
    step('match', 'running')
    await wait(450, signal)
    const found = compare(lock.prints, await fingerprint(photo))
    score = Math.round(found.score * 10000) / 10000
    best = found.best
    corr = found.corr
    outcome = outcomeOf(score)
    step('match', outcome === 'success' ? 'done' : 'failed', `Score ${score.toFixed(2)} against the threshold ${MOCK_THRESHOLD.toFixed(2)}`)
  }
  const durationMs = Math.round(performance.now() - t0)
  const reason =
    outcome === 'invalid_image'
      ? problem!
      : outcome === 'success'
        ? `The palm matched: score ${score!.toFixed(2)} reached the threshold ${MOCK_THRESHOLD.toFixed(2)}.`
        : `The palm did not match: score ${score!.toFixed(2)} is below the threshold ${MOCK_THRESHOLD.toFixed(2)}.`
  const methods: Record<string, number> = score === undefined ? {} : { crease: score, compcode: score }
  return mutate((dd) => {
    const k = lockOf(dd, profileId)!
    const line = logLine(dd, profileId, kind, reason, {
      outcome,
      ...(score !== undefined ? { score, threshold: MOCK_THRESHOLD, methods } : { threshold: MOCK_THRESHOLD }),
      ...(outcome === 'invalid_image' ? { problem: 'photo_checks' } : {}),
      hand: k.side,
      durationMs,
      calibrated: false,
    })
    let lockedUntil: number | undefined
    if (outcome === 'failed') {
      const now = Date.now()
      let since = Math.max(now - WINDOW_MS, k.lockedUntil ?? 0)
      const lastWin = [...dd.attempts].reverse().find((a) => a.profileId === profileId && (a.kind === 'unlock' || a.kind === 'test') && a.outcome === 'success')
      if (lastWin) since = Math.max(since, Date.parse(lastWin.at) + 1)
      const fails = dd.attempts.filter((a) => a.profileId === profileId && (a.kind === 'unlock' || a.kind === 'test') && a.outcome === 'failed' && Date.parse(a.at) >= since).length
      if (fails >= FAILURES) lockedUntil = k.lockedUntil = now + LOCKOUT_MS
    }
    let opened = false
    if (outcome === 'success') {
      delete k.lockedUntil
      if (kind === 'unlock') {
        setOpenProfile(profileId)
        opened = true
      }
    }
    return {
      attemptId: line.id,
      profileId,
      outcome,
      title: outcome === 'success' ? 'Authentication Successful' : outcome === 'failed' ? 'Authentication Failed' : 'Invalid Image',
      ...(score !== undefined ? { score } : {}),
      threshold: MOCK_THRESHOLD,
      methods,
      raw: (score === undefined ? {} : { crease: corr, compcode: corr, lbp: corr }) as Record<string, number>,
      reason,
      ...(outcome === 'invalid_image' ? { problem: 'photo_checks' } : {}),
      hand: k.side,
      durationMs,
      at: line.at,
      calibrated: false,
      engineVersion: MOCK_ENGINE,
      opened,
      ...(best !== undefined ? { bestSample: best } : {}),
      ...(lockedUntil ? { lockedUntil } : {}),
    }
  })
}

function checkName(name: string, ignoreId?: string) {
  const bad = validateProfileName(name)
  if (bad) throw new ApiError('invalid', bad)
  const clash = data().profiles.some((p) => p.id !== ignoreId && p.name.toLowerCase() === name.trim().toLowerCase())
  if (clash) throw new ApiError('invalid', `You already have a profile called “${name.trim()}”. Please choose a different name.`)
}

export const mockApi: Api = {
  auth: mockAuth,

  async accountStorage() {
    return 'browser'
  },

  // ---------------------------------------------------------------- profiles
  async listProfiles(): Promise<HandProfile[]> {
    await wait(LATENCY)
    const d = data()
    return d.profiles.map((p) => toProfile(d, p)).sort((a, b) => a.createdAt.localeCompare(b.createdAt))
  },

  async createProfile(input) {
    await wait(LATENCY)
    checkName(input.name)
    if (input.owner === 'other' && !input.consent) {
      throw new ApiError('invalid', 'Please confirm that this person has agreed to you uploading their palms.')
    }
    if (data().profiles.length >= 12) throw new ApiError('invalid', 'That is the most hand profiles one account can hold (12). Delete one you no longer need first.')
    return mutate((d) => {
      const p = { id: newId('prf'), name: input.name.trim(), owner: input.owner, consent: input.owner === 'self' ? true : input.consent, createdAt: new Date().toISOString() }
      d.profiles.push(p)
      return toProfile(d, p)
    })
  },

  async renameProfile(id, name) {
    await wait(LATENCY)
    find.profile(id)
    requireReach(id)
    checkName(name, id)
    return mutate((d) => {
      const p = d.profiles.find((x) => x.id === id)!
      p.name = name.trim().slice(0, PROFILE_NAME_MAX)
      return toProfile(d, p)
    })
  },

  async deleteProfile(id, password) {
    await wait(LATENCY)
    find.profile(id)
    const openId = openProfileId()
    if (lockOf(data(), id) && openId !== id) requirePassword(password)
    return mutate((d) => {
      if (lockOf(d, id)) logLine(d, id, 'profile_deleted', `Locked profile deleted ${openId === id ? 'while it was open' : 'with the account password'}.`, { via: openId === id ? 'palm' : 'password' })
      const readingIds = new Set(d.readings.filter((r) => r.profileId === id).map((r) => r.id))
      const gone = dropReadings(d, readingIds)
      d.profiles = d.profiles.filter((p) => p.id !== id)
      d.locks = d.locks.filter((k) => k.profileId !== id)
      if (openId === id) setOpenProfile(null)
      return { profiles: 1, ...gone }
    })
  },

  // ---------------------------------------------------------------- palm locks
  async openProfile(id) {
    await wait(LATENCY)
    find.profile(id)
    requireReach(id)
    setOpenProfile(id)
    const d = data()
    return toProfile(d, d.profiles.find((p) => p.id === id)!, id)
  },

  async closeProfile() {
    await wait(LATENCY)
    setOpenProfile(null)
  },

  async lockProfile(id, input) {
    await wait(LATENCY)
    if (getScope()?.kind !== 'user') throw new ApiError('forbidden', 'Create an account or sign in to lock a profile with a palm. A guest session is temporary, and its lock would go with it.')
    const profile = find.profile(id)
    requireReach(id)
    if (!input.consent) throw new ApiError('invalid', `Please confirm that ${profile.owner === 'self' ? 'you agree' : `${profile.name} has agreed`} to their palm being used as a lock. Only encrypted numbers are kept, never the photos.`)
    if (input.photos.length < 3 || input.photos.length > 5) throw new ApiError('invalid', `Locking a profile takes 3 to 5 photos of the same palm. ${input.photos.length} were sent.`)
    const problems = (await Promise.all(input.photos.map((b) => photoProblem(b, input.side)))).flatMap((message, index) => (message ? [{ index, code: 'photo_checks', message }] : []))
    if (problems.length) throw new ApiError('invalid', `${problems.length} of the photos could not be used for the lock. Take ${problems.length === 1 ? 'it' : 'them'} again and try once more.`, { photos: problems })
    const prints = await Promise.all(input.photos.map(fingerprint))
    await wait(900)
    return mutate((d) => {
      const replaced = !!lockOf(d, id)
      d.locks = d.locks.filter((k) => k.profileId !== id)
      d.locks.push({ profileId: id, side: input.side, createdAt: new Date().toISOString(), samples: prints.length, prints })
      logLine(d, id, replaced ? 'lock_replaced' : 'lock_added', `Palm lock ${replaced ? 'replaced' : 'set up'} with ${prints.length} photos of the ${input.side} hand.`, { hand: input.side, calibrated: false })
      setOpenProfile(id)
      return toProfile(d, d.profiles.find((p) => p.id === id)!, id)
    })
  },

  async removeLock(id, password) {
    await wait(LATENCY)
    const profile = find.profile(id)
    if (!lockOf(data(), id)) throw new ApiError('invalid', `“${profile.name}” has no palm lock to take off.`)
    const isOpen = openProfileId() === id
    if (!isOpen) requirePassword(password)
    return mutate((d) => {
      d.locks = d.locks.filter((k) => k.profileId !== id)
      logLine(d, id, 'lock_removed', `Palm lock taken off ${isOpen ? 'while the profile was open' : 'with the account password'}.`, { via: isOpen ? 'palm' : 'password' })
      return toProfile(d, d.profiles.find((p) => p.id === id)!)
    })
  },

  unlockProfile(id, photo, onEvent, signal) {
    return mockAttempt(id, photo, 'unlock', onEvent, signal)
  },

  async testVerification(userId, photo, onEvent, signal) {
    const id = userId.trim()
    if (!id) throw new ApiError('invalid', 'Type the user ID of the profile to test against.')
    if (!data().profiles.some((p) => p.id === id)) {
      throw new ApiError('not_found', `There is no hand profile with the user ID “${id.slice(0, 60)}” in this account, so nothing was compared. Check the ID shown on the profile's palm lock.`)
    }
    return mockAttempt(id, photo, 'test', onEvent, signal)
  },

  async palmLockInfo() {
    await wait(LATENCY)
    return {
      available: true,
      note: 'This is the sample backend: it compares tiny thumbnails of the photos, not palms. Start the real server to try the palm lock itself.',
      engineVersion: MOCK_ENGINE,
      configHash: 'sample',
      calibrated: false,
      threshold: MOCK_THRESHOLD,
      calibrationSource: 'a fixed number in the sample backend',
      measured: {},
      methods: [
        { id: 'crease', name: 'Crease map', weight: 0.5, description: 'On the server: where the creases run, compared as maps and direction histograms.' },
        { id: 'compcode', name: 'Competitive code', weight: 0.5, description: 'On the server: the strongest line direction in each block, from six Gabor filters.' },
        { id: 'lbp', name: 'Local binary patterns (spare)', weight: 0, description: 'On the server: skin texture histograms, shown for comparison only.' },
      ],
      policy: { failures: FAILURES, windowMinutes: 10, lockoutMinutes: 5, idleMinutes: 15, enrolMin: 3, enrolMax: 5 },
      roiSize: 128,
    }
  },

  async listActivity(profileId) {
    await wait(LATENCY)
    return [...data().attempts].reverse().filter((a) => !profileId || a.profileId === profileId)
  },

  // ---------------------------------------------------------------- photos and readings
  async validatePhoto(side: HandSide, photo: Blob) {
    await wait(LATENCY + 250)
    return buildValidation(side, await measurePhoto(photo))
  },

  async createReading(input, onEvent, signal) {
    find.profile(input.profileId)
    requireReach(input.profileId)
    // the name is checked before any photo is looked at, as the server does
    const nameProblem = validateReadingName(input.name ?? '')
    if (nameProblem) throw new ApiError('invalid', nameProblem)
    const name = cleanReadingName(input.name ?? '')
    const emit = (stage: StageKey, state: ProcessingEvent['state'], detail?: string, previews?: ProcessingEvent['previews']) =>
      onEvent({ stage, state, ...(detail ? { detail } : {}), ...(previews ? { previews } : {}) })

    // 1. the photos are checked again on the server side, whatever the browser said
    emit('validate', 'running')
    const [ml, mr] = await Promise.all([measurePhoto(input.left), measurePhoto(input.right)])
    const vl = buildValidation('left', ml)
    const vr = buildValidation('right', mr)
    await wait(550, signal)
    if (!vl.ok || !vr.ok) {
      emit('validate', 'failed', 'A photo did not pass the checks')
      throw new ApiError('invalid', 'One of the photos did not pass the checks. Please replace it and try again.')
    }
    emit('validate', 'done', 'Both photos passed the checks')

    // 2. resize
    emit('resize', 'running')
    await wait(650, signal)
    emit('resize', 'done', `Both photos are ${Math.max(ml.width, ml.height, mr.width, mr.height)} px or less on the longest side`)

    // 3. grayscale, smoothing, contrast, edges
    emit('gray', 'running')
    await nextFrame()
    const left = await previewsFor(input.left)
    await nextFrame()
    const right = await previewsFor(input.right)
    await wait(450, signal)
    emit('gray', 'done', 'Colour removed, brightness kept', { left: left.gray, right: right.gray })

    const steps: { key: Exclude<ImageStageKey, 'gray'>; detail: string }[] = [
      { key: 'blur', detail: 'Noise and skin texture smoothed away' },
      { key: 'contrast', detail: 'Local contrast lifted so faint creases stand out' },
      { key: 'edges', detail: 'Sharp changes in brightness traced as edges' },
      { key: 'threshold', detail: 'Marks darker than their surroundings turned white, the rest black' },
      { key: 'morphology', detail: 'Tiny specks removed and broken pieces joined' },
    ]
    for (const step of steps) {
      emit(step.key, 'running')
      await wait(850, signal)
      if (failNext && step.key === 'contrast') {
        failNext = false
        emit(step.key, 'failed', 'The step could not be completed')
        throw new ApiError('processing_failed', 'We could not finish working on these photos. Nothing was saved and your photos were thrown away. Please try again.')
      }
      emit(step.key, 'done', step.detail, { left: left[step.key], right: right[step.key] })
    }

    // 4. find and name the lines
    emit('lines', 'running')
    await wait(1100, signal)
    const reading = makeReading(
      input.profileId,
      { left: { width: vl.width, height: vl.height }, right: { width: vr.width, height: vr.height } },
      { left: qualityFrom(vl, ml), right: qualityFrom(vr, mr) },
      new Date().toISOString(),
    )
    if (name) reading.name = name
    const found = countStatuses(reading)
    emit('lines', 'done', `${found.detected} of 10 lines detected, ${found.uncertain} uncertain, ${found.not_visible} not visible`)

    // 5. write the reading
    emit('reading', 'running')
    await wait(1300, signal)
    mutate((d) => {
      d.readings.push(reading)
    })
    emit('reading', 'done', 'Report written from the results')
    return reading
  },

  async listReadings(profileId) {
    await wait(LATENCY)
    const d = data()
    if (profileId) requireReach(profileId)
    const openId = openProfileId()
    const summaries: ReadingSummary[] = d.readings.filter((r) => (!profileId || r.profileId === profileId) && canReach(d, r.profileId, openId)).map((r) => summaryOf(d, r))
    return summaries.sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  },

  async getReading(id): Promise<Reading> {
    await wait(LATENCY)
    const r = find.reading(id)
    requireReach(r.profileId)
    return r
  },

  async renameReading(id, name) {
    await wait(LATENCY)
    requireReach(find.reading(id).profileId)
    const bad = validateReadingName(name)
    if (bad) throw new ApiError('invalid', bad)
    return mutate((d) => {
      const r = d.readings.find((x) => x.id === id)!
      const clean = cleanReadingName(name)
      if (clean) r.name = clean
      else delete r.name
      return summaryOf(d, r)
    })
  },

  async deleteReading(id) {
    await wait(LATENCY)
    requireReach(find.reading(id).profileId)
    return mutate((d) => ({ ...none, ...dropReadings(d, new Set([id])) }))
  },

  // ---------------------------------------------------------------- chat
  async listConversations(filter) {
    await wait(LATENCY)
    const d = data()
    if (filter?.profileId) requireReach(filter.profileId)
    const openId = openProfileId()
    return d.conversations
      .filter((c) => (!filter?.readingId || c.readingId === filter.readingId) && (!filter?.profileId || c.profileId === filter.profileId) && canReach(d, c.profileId, openId))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  },

  async createConversation(readingId): Promise<Conversation> {
    await wait(LATENCY)
    const reading = find.reading(readingId)
    requireReach(reading.profileId)
    const now = new Date().toISOString()
    return mutate((d) => {
      const c: Conversation = { id: newId('cnv'), readingId, profileId: reading.profileId, title: 'New chat', createdAt: now, updatedAt: now, messageCount: 0 }
      d.conversations.push(c)
      return c
    })
  },

  async getConversation(id): Promise<ConversationWithMessages> {
    await wait(LATENCY)
    const c = find.conversation(id)
    requireReach(c.profileId)
    return { ...c, messages: data().messages.filter((m) => m.conversationId === id).sort((a, b) => a.createdAt.localeCompare(b.createdAt)) }
  },

  async sendMessage(conversationId, text) {
    const clean = text.trim()
    if (!clean) throw new ApiError('invalid', 'Please type a question first.')
    if (clean.length > MESSAGE_MAX) throw new ApiError('invalid', `Please keep your question under ${MESSAGE_MAX} characters.`)
    requireReach(find.conversation(conversationId).profileId)
    await wait(650 + Math.round(Math.random() * 500))
    return mutate((d) => postMessage(d, conversationId, clean))
  },

  async deleteConversation(id) {
    await wait(LATENCY)
    requireReach(find.conversation(id).profileId)
    return mutate((d) => ({ ...none, ...dropConversations(d, new Set([id])) }))
  },

  // ---------------------------------------------------------------- the whole account
  async exportData() {
    await wait(LATENCY)
    const d = data()
    const openId = openProfileId()
    return {
      exportedAt: new Date().toISOString(),
      profiles: d.profiles.map((p) => toProfile(d, p, openId)),
      readings: d.readings.filter((r) => canReach(d, r.profileId, openId)),
      conversations: d.conversations.filter((c) => canReach(d, c.profileId, openId)).map((c) => ({ ...c, messages: d.messages.filter((m) => m.conversationId === c.id) })),
    }
  },

  async deleteAllData(password) {
    await wait(LATENCY)
    const scope = getScope()
    if (!scope) throw new ApiError('unauthorised', 'Please sign in first.')
    const d = data()
    const openId = openProfileId()
    if (d.profiles.some((p) => !canReach(d, p.id, openId))) requirePassword(password)
    const counts = countsOf(d)
    clearScope(scope)
    setOpenProfile(null)
    return counts
  },

  // ---------------------------------------------------------------- demonstration helpers
  demo: {
    async loadSamples() {
      await wait(LATENCY)
      loadSampleData(currentDisplayName())
    },
    async reset() {
      await wait(LATENCY)
      const scope = getScope()
      if (scope) clearScope(scope)
    },
    async expireGuest() {
      expireGuestNow()
    },
    setFailNext(on) {
      failNext = on
    },
    failNext() {
      return failNext
    },
  },
}
