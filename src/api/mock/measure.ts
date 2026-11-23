// SAMPLE BACKEND ONLY. Rough, quick checks on a photo so the "photo check" screen reacts to what was
// actually chosen (a blurry or dark photo gets a warning) before the real backend exists.
// The real checks (OpenCV on the server) replace all of this; the screens do not change.

import type { CheckStatus, HandSide, PhotoCheck, PhotoQuality, QualityLevel, ValidationResult } from '../types'

export type Measures = {
  width: number
  height: number
  /** average brightness, 0 to 255 */
  meanLuma: number
  /** brightest quarter of the picture divided by the darkest quarter */
  unevenness: number
  /** how much fine detail there is (variance of the Laplacian). Low means blurry. */
  sharpness: number
  /** share of the picture that looks like skin, 0 to 1 */
  skinFraction: number
  /** skin reaching the top / side edges suggests fingers or the hand are cut off */
  cutOffTop: boolean
  cutOffSides: boolean
}

// Thresholds picked by trying the built-in samples; good enough for a demonstration.
const SHARP_FAIL = 14
const SHARP_WARN = 40
const DARK_FAIL = 38
const DARK_WARN = 70
const BRIGHT_WARN = 205
const BRIGHT_FAIL = 238
const UNEVEN_WARN = 3.4
const SHORT_SIDE_FAIL = 500
const SHORT_SIDE_WARN = 800
const SKIN_MIN = 0.09
const SKIN_NONE = 0.005

export async function measurePhoto(blob: Blob): Promise<Measures> {
  const bmp = await createImageBitmap(blob)
  const width = bmp.width
  const height = bmp.height
  const scale = Math.min(1, 320 / Math.max(width, height))
  const w = Math.max(8, Math.round(width * scale))
  const h = Math.max(8, Math.round(height * scale))
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const ctx = c.getContext('2d', { willReadFrequently: true })!
  ctx.drawImage(bmp, 0, 0, w, h)
  bmp.close()
  const { data } = ctx.getImageData(0, 0, w, h)

  const luma = new Float32Array(w * h)
  let sum = 0
  let skin = 0
  const quad = [0, 0, 0, 0]
  const quadN = [0, 0, 0, 0]
  const skinTop = new Uint8Array(w)
  const topRows = Math.max(1, Math.round(h * 0.03))
  let leftSkin = 0
  let rightSkin = 0
  const sideCols = Math.max(1, Math.round(w * 0.02))

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4
      const r = data[i]
      const g = data[i + 1]
      const b = data[i + 2]
      const l = 0.299 * r + 0.587 * g + 0.114 * b
      luma[y * w + x] = l
      sum += l
      const q = (y < h / 2 ? 0 : 2) + (x < w / 2 ? 0 : 1)
      quad[q] += l
      quadN[q]++
      // classic skin range in YCbCr space
      const cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
      const cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
      const isSkin = cb >= 77 && cb <= 127 && cr >= 133 && cr <= 180 && l > 30
      if (isSkin) {
        skin++
        if (y < topRows) skinTop[x] = 1
        if (x < sideCols) leftSkin++
        if (x >= w - sideCols) rightSkin++
      }
    }
  }

  // Laplacian variance: sharp pictures have lots of fine contrast, blurry ones do not
  let lapSum = 0
  let lapSq = 0
  let n = 0
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const k = y * w + x
      const lap = 4 * luma[k] - luma[k - 1] - luma[k + 1] - luma[k - w] - luma[k + w]
      lapSum += lap
      lapSq += lap * lap
      n++
    }
  }
  const sharpness = lapSq / n - (lapSum / n) ** 2

  const means = quad.map((q, i) => q / Math.max(1, quadN[i]))
  const unevenness = Math.max(...means) / Math.max(1, Math.min(...means))

  const topShare = skinTop.reduce((a, b) => a + b, 0) / w
  return {
    width,
    height,
    meanLuma: sum / (w * h),
    unevenness,
    sharpness,
    skinFraction: skin / (w * h),
    cutOffTop: topShare > 0.12,
    cutOffSides: leftSkin / (h * sideCols) > 0.3 || rightSkin / (h * sideCols) > 0.3,
  }
}

const level = (s: CheckStatus): QualityLevel => (s === 'pass' ? 'good' : s === 'warn' ? 'fair' : 'poor')

/** Turns the raw numbers into the checklist the photo screen shows. */
export function buildValidation(side: HandSide, m: Measures): ValidationResult {
  const shortSide = Math.min(m.width, m.height)

  const dims: CheckStatus = shortSide < SHORT_SIDE_FAIL ? 'fail' : shortSide < SHORT_SIDE_WARN ? 'warn' : 'pass'
  const blur: CheckStatus = m.sharpness < SHARP_FAIL ? 'fail' : m.sharpness < SHARP_WARN ? 'warn' : 'pass'
  const light: CheckStatus =
    m.meanLuma < DARK_FAIL || m.meanLuma > BRIGHT_FAIL ? 'fail' : m.meanLuma < DARK_WARN || m.meanLuma > BRIGHT_WARN || m.unevenness > UNEVEN_WARN ? 'warn' : 'pass'
  const cut = m.cutOffTop || m.cutOffSides
  const palm: CheckStatus = m.skinFraction < SKIN_NONE ? 'fail' : m.skinFraction < SKIN_MIN || cut ? 'warn' : 'pass'

  const checks: PhotoCheck[] = [
    { id: 'file_type', label: 'File type', status: 'pass', message: 'A JPG or PNG photo.' },
    { id: 'integrity', label: 'File opens', status: 'pass', message: 'The photo opened normally.' },
    {
      id: 'dimensions',
      label: 'Size',
      status: dims,
      message:
        dims === 'fail'
          ? `Only ${m.width} × ${m.height} px, which is too small to find fine lines. Please use a photo at least ${SHORT_SIDE_WARN} px on its short side. Phone cameras do this by default.`
          : dims === 'warn'
            ? `${m.width} × ${m.height} px is on the small side. It can work, but a larger photo shows the lines better.`
            : `${m.width} × ${m.height} px.`,
    },
    {
      id: 'blur',
      label: 'Focus',
      status: blur,
      message:
        blur === 'fail'
          ? 'This photo is too blurry to see the creases. Tap the palm to focus, hold still, and retake it.'
          : blur === 'warn'
            ? 'A little soft. Fine lines may be marked uncertain. A sharper photo gives a better reading.'
            : 'Sharp enough to see fine lines.',
    },
    {
      id: 'lighting',
      label: 'Lighting',
      status: light,
      message:
        light === 'fail'
          ? m.meanLuma < 128
            ? 'This photo is too dark. Move to daylight or a bright room and retake it.'
            : 'This photo is washed out by bright light. Move out of direct light, turn the flash off and retake it.'
          : light === 'warn'
            ? m.unevenness > UNEVEN_WARN
              ? 'The light is uneven, with strong shadow on part of the hand. Even light works best.'
              : m.meanLuma < DARK_WARN
                ? 'A bit dim. Faint lines may be hard to find. More light would help.'
                : 'Quite bright. Avoid flash and direct sun so creases do not wash out.'
            : 'Even and bright enough.',
    },
    {
      id: 'palm_visible',
      label: 'Palm in view',
      status: palm,
      message:
        palm === 'fail'
          ? 'We could not find a palm in this photo. Hold the whole palm flat to the camera in even light, then take it again.'
          : cut
            ? 'Parts of the hand look cut off by the edge of the photo. Step back so the whole hand fits, fingertips to wrist.'
            : m.skinFraction < SKIN_MIN
              ? 'We could not clearly see a palm in this photo. Is the whole palm facing the camera?'
              : 'A palm is in view.',
    },
  ]

  return {
    side,
    ok: !checks.some((c) => c.status === 'fail'),
    width: m.width,
    height: m.height,
    checks,
  }
}

export function qualityFrom(v: ValidationResult, m: Measures): PhotoQuality {
  const get = (id: PhotoCheck['id']) => v.checks.find((c) => c.id === id)!.status
  const pts = (s: CheckStatus) => (s === 'pass' ? 1 : s === 'warn' ? 0.62 : 0.25)
  const score = (pts(get('blur')) * 0.4 + pts(get('lighting')) * 0.3 + pts(get('dimensions')) * 0.15 + pts(get('palm_visible')) * 0.15)
  return {
    sharpness: level(get('blur')),
    lighting: level(get('lighting')),
    resolution: level(get('dimensions')),
    palmVisible: m.skinFraction >= SKIN_MIN,
    score: Math.round(score * 100) / 100,
  }
}
