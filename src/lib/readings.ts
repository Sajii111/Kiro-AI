import type { FeatureStatus, Reading } from '../api/types'
import { formatDate } from './format'
import { t } from '../i18n'

/** How many of the ten findings (five lines on each hand) have each status. */
export function countStatuses(reading: Pick<Reading, 'hands'>): Record<FeatureStatus, number> {
  const counts: Record<FeatureStatus, number> = { detected: 0, uncertain: 0, not_visible: 0 }
  for (const side of ['left', 'right'] as const) for (const f of reading.hands[side].features) counts[f.status]++
  return counts
}

/** What to call a reading in a sentence (a button, a message, the delete box): its name when it has one, and always whose and when. */
export function readingLabel(reading: Pick<Reading, 'name' | 'createdAt'>, profileName: string): string {
  const plain = t("{profileName}’s reading of {1}", { profileName: profileName, "1": formatDate(reading.createdAt) })
  return reading.name ? `“${reading.name}” (${plain})` : plain
}

const LINE_WORDS: Record<string, string> = { heart: 'heart', head: 'head', life: 'life', fate: 'fate', sun: 'sun' }

/**
 * A reading's one-line summary for list rows, in the chosen language. The server writes it in English from a fixed pattern
 * ("Heart and life lines clear on both hands", "6 of 10 lines detected, 2 uncertain"), so the pattern is read back here.
 */
export function headlineText(headline: string): string {
  const both = /^(.+?) lines? clear on both hands$/i.exec(headline)
  if (both) {
    const names = both[1]
      .toLowerCase()
      .split(/, | and /)
      .map((w) => w.trim())
    if (names.every((n) => n in LINE_WORDS)) {
      const words = names.map((n) => t(`${n} line`))
      const list = words.length === 1 ? words[0] : t('{a} and {b}', { a: words.slice(0, -1).join(', '), b: words[words.length - 1] })
      return t('{lines} clear on both hands', { lines: list })
    }
  }
  const counted = /^(\d+) of 10 lines detected, (\d+) uncertain$/.exec(headline)
  if (counted) return t('{d} of 10 lines detected, {u} uncertain', { d: counted[1], u: counted[2] })
  return t(headline)
}
