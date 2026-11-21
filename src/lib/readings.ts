import type { FeatureStatus, Reading } from '../api/types'

/** How many of the ten findings (five lines on each hand) have each status. */
export function countStatuses(reading: Pick<Reading, 'hands'>): Record<FeatureStatus, number> {
  const counts: Record<FeatureStatus, number> = { detected: 0, uncertain: 0, not_visible: 0 }
  for (const side of ['left', 'right'] as const) for (const f of reading.hands[side].features) counts[f.status]++
  return counts
}
