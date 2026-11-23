// Getting a photo from the visitor ready to send: quick safety checks, then shrink it in the browser.
//
// This is not "image processing" in the project's sense (grayscale, blur, CLAHE, Canny all happen on the
// backend). It is the front door: refuse files that are obviously not photos, and never send more pixels
// than needed. Re-drawing the picture also drops hidden metadata such as the GPS location a phone adds.

import { MAX_PHOTO_BYTES, MAX_PHOTO_SIDE } from '../config'
import { drawDemoPalm } from './demoPalm'
import { rng } from './rand'
import type { HandSide } from '../api/types'

export type PhotoProblemCode = 'empty' | 'unsupported_type' | 'too_large' | 'corrupt'

/** A photo that cannot be used, with a message that says what to do about it. */
export class PhotoProblem extends Error {
  code: PhotoProblemCode
  constructor(code: PhotoProblemCode, message: string) {
    super(message)
    this.name = 'PhotoProblem'
    this.code = code
  }
}

export type PreparedPhoto = {
  /** the shrunken JPEG that would be uploaded */
  blob: Blob
  /** a temporary address for showing it on screen. Free it with releasePhoto(). */
  url: string
  width: number
  height: number
  name: string
  originalBytes: number
  originalWidth: number
  originalHeight: number
  /** true when it was one of the built-in sample photos */
  sample: boolean
}

export const ACCEPT = 'image/jpeg,image/png'

/** What the file's first bytes say it is, whatever its name claims. */
async function sniff(file: Blob): Promise<'jpeg' | 'png' | null> {
  const b = new Uint8Array(await file.slice(0, 8).arrayBuffer())
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return 'jpeg'
  if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return 'png'
  return null
}

function niceTypeName(file: File): string {
  const ext = file.name.includes('.') ? file.name.split('.').pop()!.toUpperCase() : ''
  if (file.type === 'image/heic' || file.type === 'image/heif' || ext === 'HEIC' || ext === 'HEIF') return 'HEIC'
  if (ext) return ext
  return file.type || 'This kind of'
}

const CORRUPT =
  'This file does not open as a normal JPG or PNG photo. It may be damaged or renamed. Please choose it again, or take a new photo.'

/** Checks the basics and returns a shrunken copy. Throws PhotoProblem with a plain message when it cannot be used. */
export async function preparePhoto(file: File, sample = false): Promise<PreparedPhoto> {
  if (file.size === 0) throw new PhotoProblem('empty', 'That file is empty. Please choose the photo again.')

  const ext = file.name.split('.').pop()?.toLowerCase()
  const goodExt = ext === 'jpg' || ext === 'jpeg' || ext === 'png'
  const goodMime = file.type === 'image/jpeg' || file.type === 'image/png'
  if (!goodExt && !goodMime) {
    const heic = niceTypeName(file) === 'HEIC'
    throw new PhotoProblem(
      'unsupported_type',
      `${niceTypeName(file)} files are not supported. Please use a JPG or PNG photo.${
        heic ? ' On an iPhone, set the camera to "Most Compatible", or export the photo as JPG.' : ''
      }`,
    )
  }

  if (file.size > MAX_PHOTO_BYTES) {
    throw new PhotoProblem('too_large', `This photo is ${(file.size / 1024 / 1024).toFixed(0)} MB, which is more than the 15 MB limit. Please choose a smaller one.`)
  }

  if (!(await sniff(file))) throw new PhotoProblem('corrupt', CORRUPT)

  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    throw new PhotoProblem('corrupt', CORRUPT)
  }

  const originalWidth = bitmap.width
  const originalHeight = bitmap.height
  const scale = Math.min(1, MAX_PHOTO_SIDE / Math.max(originalWidth, originalHeight))
  const width = Math.max(1, Math.round(originalWidth * scale))
  const height = Math.max(1, Math.round(originalHeight * scale))

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    bitmap.close()
    throw new PhotoProblem('corrupt', CORRUPT)
  }
  // a white base so transparent PNGs do not turn black in the JPEG
  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, width, height)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(bitmap, 0, 0, width, height)
  bitmap.close()

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9))
  if (!blob) throw new PhotoProblem('corrupt', CORRUPT)

  return {
    blob,
    url: URL.createObjectURL(blob),
    width,
    height,
    name: file.name,
    originalBytes: file.size,
    originalWidth,
    originalHeight,
    sample,
  }
}

/** Frees the temporary address made for a prepared photo. */
export function releasePhoto(photo: PreparedPhoto | null | undefined) {
  if (photo) URL.revokeObjectURL(photo.url)
}

// ------------------------------------------------------------------ built-in sample photos

export type SampleKind = 'clear' | 'blurry' | 'dark' | 'cropped' | 'small' | 'not_a_palm'

export const SAMPLE_LABEL: Record<SampleKind, string> = {
  clear: 'A clear palm',
  blurry: 'A blurry palm',
  dark: 'A palm in dim light',
  cropped: 'A cropped palm',
  small: 'A very small photo',
  not_a_palm: 'Not a palm',
}

/**
 * Makes a picture of a palm out of nothing but the hand geometry, so the screens can be tried (and the
 * photo checks shown) without a real photo. The left sample is the right one mirrored.
 */
export async function makeSamplePhoto(kind: SampleKind, side: HandSide): Promise<File> {
  // drawn at 520 x 660, then enlarged so the sample is a realistic size and passes the "large enough" check
  const SCALE = kind === 'small' ? 0.7 : 1.6
  const W = Math.round(520 * SCALE)
  const H = Math.round(660 * SCALE)
  const out = document.createElement('canvas')
  out.width = W
  out.height = H
  const ctx = out.getContext('2d')!

  if (kind === 'not_a_palm') {
    // a plain brick wall: plenty of detail, no hand in sight
    ctx.fillStyle = '#3b444a'
    ctx.fillRect(0, 0, W, H)
    const rand = rng(11)
    const rows = 16
    const bh = H / rows
    const bw = W / 5
    for (let r = 0; r < rows; r++) {
      const shift = (r % 2) * (bw / 2)
      for (let x = -bw; x < W + bw; x += bw) {
        ctx.fillStyle = `hsl(205 ${12 + rand() * 6}% ${34 + rand() * 14}%)`
        ctx.fillRect(x + shift + 2, r * bh + 2, bw - 4, bh - 4)
      }
    }
  } else {
    // a cool grey tabletop, so the skin tones stand out from it as they would on a real desk
    const base = drawDemoPalm(520, 660, ['#56646c', '#262e33'])
    ctx.save()
    if (side === 'left') {
      ctx.translate(W, 0)
      ctx.scale(-1, 1)
    }
    if (kind === 'blurry') ctx.filter = `blur(${Math.round(7 * SCALE)}px)`
    if (kind === 'dark') ctx.filter = 'brightness(0.5) contrast(0.95)'
    if (kind === 'cropped') {
      // zoom in on the lower palm so the fingertips and one edge fall outside the frame
      const cx = W * 0.5
      const cy = H * 0.9
      ctx.translate(cx, cy)
      ctx.scale(1.55, 1.55)
      ctx.translate(-cx, -cy)
    }
    ctx.drawImage(base, 0, 0, W, H)
    ctx.restore()
  }

  const blob = await new Promise<Blob | null>((resolve) => out.toBlob(resolve, 'image/jpeg', 0.92))
  if (!blob) throw new PhotoProblem('corrupt', CORRUPT)
  return new File([blob], `sample-${side}-palm-${kind.replace(/_/g, '-')}.jpg`, { type: 'image/jpeg' })
}
