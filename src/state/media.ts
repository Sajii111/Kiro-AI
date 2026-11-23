// Photos live here, in this browser tab's memory, and nowhere else. This is what makes "photos are never
// saved" true on the screen: reload or close the tab and they are gone. A saved reading only ever keeps findings.

export type TabPhotos = {
  left: string
  right: string
  /** true when the lines on the reading can be drawn on top of these photos */
  aligned: boolean
}

const photos = new Map<string, TabPhotos>()

export const keepPhotos = (readingId: string, value: TabPhotos) => void photos.set(readingId, value)

export function getPhotos(readingId: string): TabPhotos | null {
  return photos.get(readingId) ?? null
}

/** Frees the photos of a reading (when it is deleted). */
export function forgetPhotos(readingId: string) {
  const p = photos.get(readingId)
  if (!p) return
  URL.revokeObjectURL(p.left)
  URL.revokeObjectURL(p.right)
  photos.delete(readingId)
}

/** Frees every photo held in this tab: when the session ends, or when all data is deleted. */
export function forgetAllPhotos() {
  for (const id of [...photos.keys()]) forgetPhotos(id)
}
