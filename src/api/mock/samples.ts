// SAMPLE BACKEND ONLY. Builds readings from a seed, and loads a ready-made set of profiles, readings and
// chats so the dashboard, history and report screens can be shown straight away.

import { hashString } from '../../lib/rand'
import type { HandSide, PhotoQuality, Reading } from '../types'
import { buildAnalysis, buildReport, MOCK_META, planStatuses } from './generate'
import { postMessage } from './convo'
import { newId, mutate } from './store'

export const SAMPLE_PHOTO = { width: 520, height: 660 }

export const GOOD_QUALITY: PhotoQuality = { sharpness: 'good', lighting: 'good', resolution: 'good', palmVisible: true, score: 0.96 }
export const FAIR_QUALITY: PhotoQuality = { sharpness: 'fair', lighting: 'fair', resolution: 'good', palmVisible: true, score: 0.68 }

export function makeReading(
  profileId: string,
  photos: Record<HandSide, { width: number; height: number }>,
  quality: Record<HandSide, PhotoQuality>,
  createdAt: string,
): Reading {
  const id = newId('rd')
  const seed = hashString(id)
  const plan = planStatuses(seed, quality)
  const hands = {
    left: buildAnalysis('left', plan.left, photos.left, quality.left, seed),
    right: buildAnalysis('right', plan.right, photos.right, quality.right, seed),
  }
  return { id, profileId, createdAt, hands, report: buildReport(hands, createdAt), meta: MOCK_META }
}

const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000 - Math.round(Math.random() * 3_600_000)).toISOString()


/** Adds sample profiles with readings and a short chat. Skips names that already exist. */
export function loadSampleData(myName: string | null) {
  mutate((d) => {
    const have = new Set(d.profiles.map((p) => p.name.toLowerCase()))
    const mine = (myName ?? 'Me').trim().split(/\s+/)[0] || 'Me'
    const add = (name: string, owner: 'self' | 'other', createdDaysAgo: number) => {
      if (have.has(name.toLowerCase())) return null
      have.add(name.toLowerCase())
      const p = { id: newId('prf'), name, owner, consent: true, createdAt: new Date(Date.now() - createdDaysAgo * 86_400_000).toISOString() }
      d.profiles.push(p)
      return p
    }
    const same = { left: SAMPLE_PHOTO, right: SAMPLE_PHOTO }
    const me = add(mine, 'self', 14)
    const nimal = add('Nimal', 'other', 13)

    if (me) {
      const old = makeReading(me.id, same, { left: FAIR_QUALITY, right: FAIR_QUALITY }, daysAgo(12))
      const latest = makeReading(me.id, same, { left: GOOD_QUALITY, right: GOOD_QUALITY }, daysAgo(2))
      d.readings.push(old, latest)
      const convo = {
        id: newId('cnv'),
        readingId: latest.id,
        profileId: me.id,
        title: 'New chat',
        createdAt: daysAgo(2),
        updatedAt: daysAgo(2),
        messageCount: 0,
      }
      d.conversations.push(convo)
      postMessage(d, convo.id, 'What does my heart line say?')
      postMessage(d, convo.id, 'And on the left hand?')
    }
    if (nimal) {
      d.readings.push(makeReading(nimal.id, same, { left: GOOD_QUALITY, right: GOOD_QUALITY }, daysAgo(5)))
    }
  })
}
