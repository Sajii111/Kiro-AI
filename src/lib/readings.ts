import type { FeatureStatus, Reading } from '../api/types'
import { formatDate } from './format'

/** How many of the ten findings (five lines on each hand) have each status. */
export function countStatuses(reading: Pick<Reading, 'hands'>): Record<FeatureStatus, number> {
  const counts: Record<FeatureStatus, number> = { detected: 0, uncertain: 0, not_visible: 0 }
  for (const side of ['left', 'right'] as const) for (const f of reading.hands[side].features) counts[f.status]++
  return counts
}

/** What to call a reading in a sentence (a button, a message, the delete box): its name when it has one, and always whose and when. */
export function readingLabel(reading: Pick<Reading, 'name' | 'createdAt'>, profileName: string): string {
  const plain = `${profileName}’s reading of ${formatDate(reading.createdAt)}`
  return reading.name ? `“${reading.name}” (${plain})` : plain
}
