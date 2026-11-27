// SAMPLE BACKEND ONLY. A stand-in for the palm lock, so the lock screens can be tried with no server.
//
// The real palm lock runs on the server: it finds the hand, cuts a square from the middle of the palm and compares its
// creases (a crease map and a competitive code). This stand-in only compares tiny grey thumbnails of the whole photo, which
// tells the very same photo from a different one and little else. The screens say so wherever its numbers appear.

import { clahe, gaussianBlur, grayToCanvas, toGray, type Gray } from '../../lib/stageFilters'
import type { HandSide, PalmOutcome, UnlockEvent } from '../types'
import { buildValidation, measurePhoto } from './measure'

const SIDE = 24
export const MOCK_THRESHOLD = 0.5

async function bitmapOf(blob: Blob): Promise<ImageBitmap> {
  return createImageBitmap(blob)
}

/** The middle square of a picture, drawn at `size` pixels. */
function middleSquare(bitmap: ImageBitmap, size: number): HTMLCanvasElement {
  const side = Math.min(bitmap.width, bitmap.height) * 0.6
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!
  ctx.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, size, size)
  return canvas
}

function grayOf(canvas: HTMLCanvasElement): Gray {
  const ctx = canvas.getContext('2d')!
  return toGray(ctx.getImageData(0, 0, canvas.width, canvas.height))
}

/** A tiny grey thumbnail, brightness taken out (mean 0, spread 1). */
export async function fingerprint(blob: Blob): Promise<number[]> {
  const bitmap = await bitmapOf(blob)
  const g = grayOf(middleSquare(bitmap, SIDE))
  bitmap.close()
  const values = Array.from(g.data)
  const mean = values.reduce((a, b) => a + b, 0) / values.length
  const spread = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length) || 1
  return values.map((v) => (v - mean) / spread)
}

function correlation(a: number[], b: number[]): number {
  let sum = 0
  for (let i = 0; i < a.length; i++) sum += a[i] * b[i]
  return sum / a.length
}

/** The best match of a photo against the enrolment thumbnails, as a score from 0 to 1. */
export function compare(prints: number[][], probe: number[]): { score: number; corr: number; best: number } {
  let best = 0
  let corr = -1
  prints.forEach((p, i) => {
    const c = correlation(p, probe)
    if (c > corr) {
      corr = c
      best = i
    }
  })
  const score = Math.max(0, Math.min(1, (corr - 0.55) / 0.4))
  return { score, corr, best }
}

/** The photo checks, as for a reading. Returns the first failing check's message, or null. */
export async function photoProblem(blob: Blob, side: HandSide): Promise<string | null> {
  const v = buildValidation(side, await measurePhoto(blob))
  if (v.ok) return null
  return v.checks.find((c) => c.status === 'fail')?.message ?? 'This photo did not pass the checks.'
}

/** Pictures for the steps of an attempt, drawn from the photo in the browser. */
export async function stepPictures(blob: Blob): Promise<Partial<Record<UnlockEvent['stage'], string>>> {
  const bitmap = await bitmapOf(blob)
  const square = middleSquare(bitmap, 160)
  bitmap.close()
  const g = gaussianBlur(grayOf(square), 1)
  const even = clahe(g)
  const url = (c: HTMLCanvasElement) => c.toDataURL('image/jpeg', 0.8)
  return {
    roi: url(square),
    prep: url(grayToCanvas(even)),
    features: url(grayToCanvas(even, { base: [20, 16, 40], bright: [255, 120, 110] })),
  }
}

export function outcomeOf(score: number): PalmOutcome {
  return score >= MOCK_THRESHOLD ? 'success' : 'failed'
}
