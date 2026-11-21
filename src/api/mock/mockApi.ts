// SAMPLE BACKEND ONLY. The whole API, answered from this browser instead of a server.
//
// It follows the same contract as the real backend (src/api/types.ts), including the rules:
//   - a reading belongs to a profile, a conversation belongs to one reading,
//   - deleting a profile removes its readings, conversations, messages and findings,
//   - photos are used in memory for the length of one request and never stored.
// The photo steps shown while a reading is made (grayscale, smoothing, CLAHE, Canny, thresholding, morphology) are
// drawn here from the chosen photo purely as an illustration. The real pipeline runs OpenCV on the server.

import { runPipeline } from '../../lib/stageFilters'
import { PROFILE_NAME_MAX, MESSAGE_MAX, validateProfileName } from '../../lib/validate'
import { ApiError } from '../errors'
import type {
  Api,
  Conversation,
  ConversationWithMessages,
  DeleteSummary,
  HandProfile,
  HandSide,
  ImageStageKey,
  ProcessingEvent,
  Reading,
  ReadingSummary,
  StageKey,
} from '../types'
import { currentDisplayName, expireGuestNow, mockAuth } from './auth'
import { postMessage, toProfile } from './convo'
import { countStatuses } from '../../lib/readings'
import { headlineFor } from './generate'
import { buildValidation, measurePhoto, qualityFrom } from './measure'
import { loadSampleData, makeReading } from './samples'
import { clearScope, countsOf, data, dropConversations, dropReadings, getScope, mutate, newId } from './store'

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
    checkName(name, id)
    return mutate((d) => {
      const p = d.profiles.find((x) => x.id === id)!
      p.name = name.trim().slice(0, PROFILE_NAME_MAX)
      return toProfile(d, p)
    })
  },

  async deleteProfile(id) {
    await wait(LATENCY)
    find.profile(id)
    return mutate((d) => {
      const readingIds = new Set(d.readings.filter((r) => r.profileId === id).map((r) => r.id))
      const gone = dropReadings(d, readingIds)
      d.profiles = d.profiles.filter((p) => p.id !== id)
      return { profiles: 1, ...gone }
    })
  },

  // ---------------------------------------------------------------- photos and readings
  async validatePhoto(side: HandSide, photo: Blob) {
    await wait(LATENCY + 250)
    return buildValidation(side, await measurePhoto(photo))
  },

  async createReading(input, onEvent, signal) {
    find.profile(input.profileId)
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
        throw new ApiError('processing_failed', 'We could not finish analysing these photos. Nothing was saved and your photos have been discarded. Please try again.')
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
    const found = countStatuses(reading)
    emit('lines', 'done', `${found.detected} of 10 lines detected, ${found.uncertain} uncertain, ${found.not_visible} not visible`)

    // 5. write the reading
    emit('reading', 'running')
    await wait(1300, signal)
    mutate((d) => {
      d.readings.push(reading)
    })
    emit('reading', 'done', 'Report written from the findings')
    return reading
  },

  async listReadings(profileId) {
    await wait(LATENCY)
    const d = data()
    const summaries: ReadingSummary[] = d.readings
      .filter((r) => !profileId || r.profileId === profileId)
      .map((r) => ({
        id: r.id,
        profileId: r.profileId,
        profileName: d.profiles.find((p) => p.id === r.profileId)?.name ?? 'Unknown',
        createdAt: r.createdAt,
        counts: countStatuses(r),
        headline: headlineFor(r),
        conversationCount: d.conversations.filter((c) => c.readingId === r.id).length,
      }))
    return summaries.sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  },

  async getReading(id): Promise<Reading> {
    await wait(LATENCY)
    return find.reading(id)
  },

  async deleteReading(id) {
    await wait(LATENCY)
    find.reading(id)
    return mutate((d) => ({ ...none, ...dropReadings(d, new Set([id])) }))
  },

  // ---------------------------------------------------------------- chat
  async listConversations(filter) {
    await wait(LATENCY)
    return data()
      .conversations.filter((c) => (!filter?.readingId || c.readingId === filter.readingId) && (!filter?.profileId || c.profileId === filter.profileId))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  },

  async createConversation(readingId): Promise<Conversation> {
    await wait(LATENCY)
    const reading = find.reading(readingId)
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
    return { ...c, messages: data().messages.filter((m) => m.conversationId === id).sort((a, b) => a.createdAt.localeCompare(b.createdAt)) }
  },

  async sendMessage(conversationId, text) {
    const clean = text.trim()
    if (!clean) throw new ApiError('invalid', 'Please type a question first.')
    if (clean.length > MESSAGE_MAX) throw new ApiError('invalid', `Please keep your question under ${MESSAGE_MAX} characters.`)
    find.conversation(conversationId)
    await wait(650 + Math.round(Math.random() * 500))
    return mutate((d) => postMessage(d, conversationId, clean))
  },

  async deleteConversation(id) {
    await wait(LATENCY)
    find.conversation(id)
    return mutate((d) => ({ ...none, ...dropConversations(d, new Set([id])) }))
  },

  // ---------------------------------------------------------------- the whole account
  async exportData() {
    await wait(LATENCY)
    const d = data()
    return {
      exportedAt: new Date().toISOString(),
      profiles: d.profiles.map((p) => toProfile(d, p)),
      readings: d.readings,
      conversations: d.conversations.map((c) => ({ ...c, messages: d.messages.filter((m) => m.conversationId === c.id) })),
    }
  },

  async deleteAllData() {
    await wait(LATENCY)
    const scope = getScope()
    if (!scope) throw new ApiError('unauthorised', 'Please sign in first.')
    const counts = countsOf(data())
    clearScope(scope)
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
