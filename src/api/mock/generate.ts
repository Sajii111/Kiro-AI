// SAMPLE BACKEND ONLY. Builds findings and a report in exactly the shapes the real backend returns.
//
// The "detected" lines are made from the same hand geometry that draws the sample palm photo, so on the
// sample photos they land exactly on the creases. On a real photo they cannot (no detection happens here):
// the screens say so, and the real OpenCV detector replaces this module without any screen changing.

import { DISCLAIMER_LONG } from '../../app/copy'
import { getStroke, handFrame, sampleSpline, type P2 } from '../../lib/handGeometry'
import { rng } from '../../lib/rand'
import type {
  FeatureId,
  FeatureResult,
  FeatureStatus,
  FeatureTraits,
  HandAnalysis,
  HandSide,
  NormBox,
  NormPoint,
  OtherCrease,
  PalmShape,
  PalmShapeTraits,
  PhotoQuality,
  Reading,
  ReadingMeta,
  Report,
  ReportSection,
  ShapeSection,
  ThemeSection,
  ThemeSource,
} from '../types'
import { countStatuses } from '../../lib/readings'
import {
  FEATURE_NAMES,
  FEATURE_ORDER,
  KB_VERSION,
  lineClause,
  listWords,
  shapeClause,
  shapeTraditionalText,
  sourceName,
  THEMES,
  traditionalText,
} from './knowledge'

export const PIPELINE_VERSION = 'sample-pipeline 0.2'
export const DETECTOR_VERSION = 'sample-detector 0.2'

export const MOCK_META: ReadingMeta = {
  provider: 'mock',
  model: 'sample-reader',
  knowledgeBase: KB_VERSION,
  prompt: 'sample-prompt 0.2',
  pipeline: PIPELINE_VERSION,
  mock: true,
}

type Length = NonNullable<FeatureTraits['length']>
type Curve = NonNullable<FeatureTraits['curve']>

// ------------------------------------------------------------------ choosing what "was found"

const STATUS_WEIGHTS: Record<FeatureId, [number, number, number]> = {
  heart: [0.82, 0.14, 0.04],
  head: [0.78, 0.17, 0.05],
  life: [0.88, 0.1, 0.02],
  fate: [0.3, 0.3, 0.4],
  sun: [0.24, 0.3, 0.46],
}

const CURVE_WEIGHTS: Record<FeatureId, [Curve, number][]> = {
  heart: [['gentle', 0.5], ['pronounced', 0.3], ['straight', 0.2]],
  head: [['gentle', 0.45], ['straight', 0.35], ['pronounced', 0.2]],
  life: [['gentle', 0.45], ['pronounced', 0.4], ['straight', 0.15]],
  fate: [['straight', 0.6], ['gentle', 0.3], ['pronounced', 0.1]],
  sun: [['straight', 0.7], ['gentle', 0.25], ['pronounced', 0.05]],
}

function pick<T>(rand: () => number, options: [T, number][]): T {
  let r = rand() * options.reduce((a, [, w]) => a + w, 0)
  for (const [value, w] of options) {
    r -= w
    if (r <= 0) return value
  }
  return options[options.length - 1][0]
}

type Plan = Record<HandSide, Record<FeatureId, FeatureStatus>>

/**
 * Decides, from a seed and the photo quality, how each line comes out. Worse photos find less.
 * For demonstration, every reading shows at least one uncertain and one not-visible line, so the honest
 * handling of unclear features is always on screen.
 */
export function planStatuses(seed: number, quality: Record<HandSide, PhotoQuality>): Plan {
  const rand = rng(seed)
  const plan = { left: {}, right: {} } as Plan
  for (const side of ['left', 'right'] as const) {
    const penalty = Math.min(0.7, Math.max(0, (0.85 - quality[side].score) * 1.2))
    for (const id of FEATURE_ORDER) {
      const [d0, u0, n0] = STATUS_WEIGHTS[id]
      const moved = d0 * penalty
      const d = d0 - moved
      const u = u0 + moved * 0.65
      const n = n0 + moved * 0.35
      plan[side][id] = pick<FeatureStatus>(rand, [['detected', d], ['uncertain', u], ['not_visible', n]])
      if ((id === 'heart' || id === 'life') && quality[side].score >= 0.6) plan[side][id] = 'detected'
    }
  }
  const all = [...Object.values(plan.left), ...Object.values(plan.right)]
  if (!all.includes('uncertain')) plan.left.head = 'uncertain'
  if (!all.includes('not_visible')) plan.right.sun = 'not_visible'
  return plan
}

// ------------------------------------------------------------------ one hand

const LEN_WORD: Record<Length, string> = { short: 'short', medium: 'medium-length', long: 'long' }
const CLARITY_WORD = { clear: 'clearly marked', deep: 'deeply marked', faint: 'faint' } as const
const CURVE_WORD: Record<Curve, string> = { straight: 'runs almost straight', gentle: 'curves gently', pronounced: 'curves strongly' }

function observationFor(id: FeatureId, status: FeatureStatus, t: FeatureTraits): string {
  const name = FEATURE_NAMES[id].toLowerCase()
  if (status === 'not_visible') {
    return `No clear line was found where the ${name} usually runs. It may be absent, very faint, or lost to lighting or focus.`
  }
  if (status === 'uncertain') {
    return `Something line-like runs here, but it is faint or broken, so it may or may not be the ${name}. Its length and shape cannot be judged reliably.`
  }
  const len = LEN_WORD[t.length!]
  const clr = CLARITY_WORD[t.clarity!]
  const curve = CURVE_WORD[t.curve!]
  switch (id) {
    case 'heart': {
      const end = t.length === 'long' ? 'beneath the index finger' : t.length === 'medium' ? 'beneath the middle finger' : 'beneath the ring finger'
      return `A ${len}, ${clr} line across the upper palm. It ${curve} and ends ${end}.`
    }
    case 'head': {
      const tail = t.length === 'long' ? ', reaching close to it' : t.length === 'short' ? ', stopping well short of it' : ''
      return `A ${len}, ${clr} line across the middle of the palm. It ${curve} as it heads toward the outer edge${tail}.`
    }
    case 'life': {
      const tail = t.length === 'long' ? 'reaches down toward the wrist' : t.length === 'short' ? 'fades out partway down the palm' : 'runs about two thirds of the way to the wrist'
      return `A ${len}, ${clr} line that arcs around the base of the thumb. It ${curve} and ${tail}.`
    }
    case 'fate':
      return `A ${len}, ${clr} line rising from the wrist toward the middle finger. It ${curve}.`
    case 'sun':
      return `A ${len}, ${clr} line below the ring finger. It ${curve}.`
  }
}

const KEEP: Record<Length, number> = { short: 0.66, medium: 0.86, long: 1 }

/** Hand space to the 0-1 picture space of a w x h photo. A left hand is the right one mirrored. */
function normaliser(side: HandSide, photo: { width: number; height: number }) {
  const { width: w, height: h } = photo
  const frame = handFrame(w, h)
  return ([x, y]: P2): NormPoint => {
    const [px, py] = frame.toPx([x, y])
    const nx = px / w
    return [round(side === 'left' ? 1 - nx : nx), round(py / h)]
  }
}

function buildFeature(id: FeatureId, side: HandSide, status: FeatureStatus, photo: { width: number; height: number }, rand: () => number): FeatureResult {
  const toNorm = normaliser(side, photo)

  // every hand is a little different: nudge the control points
  const shift: P2 = [(rand() - 0.5) * 0.04, (rand() - 0.5) * 0.04]
  const wobble = status === 'uncertain' ? 0.045 : 0.025
  const pts = getStroke(id).pts.map(([x, y]): P2 => [x + shift[0] + (rand() - 0.5) * wobble, y + shift[1] + (rand() - 0.5) * wobble])

  // the zone searched: the usual place of the line, with some room around it
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  const pad = 0.07
  const corners = [toNorm([Math.min(...xs) - pad, Math.max(...ys) + pad]), toNorm([Math.max(...xs) + pad, Math.min(...ys) - pad])]
  const x0 = clamp01(Math.min(corners[0][0], corners[1][0]))
  const x1 = clamp01(Math.max(corners[0][0], corners[1][0]))
  const y0 = clamp01(Math.min(corners[0][1], corners[1][1]))
  const y1 = clamp01(Math.max(corners[0][1], corners[1][1]))
  const searchArea: NormBox = { x: round(x0), y: round(y0), w: round(x1 - x0), h: round(y1 - y0) }

  const method = DETECTOR_VERSION
  const name = FEATURE_NAMES[id]

  if (status === 'not_visible') {
    return { id, name, status, path: [], searchArea, confidence: null, observation: observationFor(id, status, {}), traits: {}, method }
  }

  const detected = status === 'detected'
  const length: Length = pick<Length>(rand, [['short', 0.25], ['medium', 0.45], ['long', 0.3]])
  const traits: FeatureTraits = detected
    ? { length, curve: pick(rand, CURVE_WEIGHTS[id]), clarity: pick(rand, [['clear', 0.6], ['deep', 0.4]]) }
    : { clarity: 'faint' }

  const samples = sampleSpline(pts, 6)
  const keep = detected ? KEEP[length] : 0.82
  const count = Math.min(samples.length, Math.max(12, Math.round(samples.length * keep)))
  const path = samples.slice(0, count).map(toNorm)

  return {
    id,
    name,
    status,
    path,
    searchArea,
    confidence: round(detected ? 0.78 + rand() * 0.17 : 0.4 + rand() * 0.22),
    observation: observationFor(id, status, traits),
    traits,
    method,
  }
}

// ------------------------------------------------------------------ hand shape and other creases

const PALM_SQUARE_AT = 0.88
const FINGERS_LONG_AT = 0.9

function buildPalmShape(quality: PhotoQuality, seed: number, rand: () => number): PalmShape {
  const method = DETECTOR_VERSION
  if (!quality.palmVisible) {
    return { status: 'not_visible', traits: {}, palmRatio: null, fingerRatio: null, confidence: null, observation: 'The hand could not be measured in this photo, so nothing is said about its shape.', method }
  }
  // both photos show the same person, so both hands share one base shape; only a small difference comes from each photo
  const base = rng(seed + 7)
  const square = base() < 0.5
  const longFingers = base() < 0.5
  const jitter = [base(), base()]
  const palmRatio = round((square ? 0.92 + jitter[0] * 0.1 : 0.74 + jitter[0] * 0.1) + (rand() - 0.5) * 0.04)
  const fingerRatio = round((longFingers ? 0.95 + jitter[1] * 0.13 : 0.76 + jitter[1] * 0.1) + (rand() - 0.5) * 0.04)
  if (quality.score < 0.6) {
    return { status: 'uncertain', traits: {}, palmRatio: null, fingerRatio: null, confidence: round(0.4 + rand() * 0.2), observation: 'Parts of the hand are soft or cut off in this photo, so its shape can only be guessed.', method }
  }
  const traits: PalmShapeTraits = { palm: palmRatio >= PALM_SQUARE_AT ? 'square' : 'long', fingers: fingerRatio >= FINGERS_LONG_AT ? 'long' : 'short' }
  return {
    status: 'detected',
    traits,
    palmRatio,
    fingerRatio,
    confidence: round(0.72 + rand() * 0.18),
    observation: `A ${traits.palm} palm (width to length ${palmRatio.toFixed(2)}) with ${traits.fingers} fingers (finger length to palm length ${fingerRatio.toFixed(2)}).`,
    method,
  }
}

const CREASE_CANDIDATES: { pts: P2[]; where: string }[] = [
  { pts: [[-0.47, 0.62], [-0.4, 0.5], [-0.33, 0.38], [-0.26, 0.26]], where: 'on the outer edge of the palm, running down towards the wrist' },
  { pts: [[-0.2, 0.7], [-0.1, 0.76], [0.0, 0.8]], where: 'between the heart line and the head line, below the ring finger' },
  { pts: [[-0.3, 0.2], [-0.15, 0.14], [0.0, 0.12], [0.12, 0.16]], where: 'across the lower palm, above the wrist' },
]

/** Strong creases left over once the five lines are named. Worse photos find fewer. */
function buildOtherCreases(side: HandSide, photo: { width: number; height: number }, quality: PhotoQuality, rand: () => number): OtherCrease[] {
  const toNorm = normaliser(side, photo)
  const out: OtherCrease[] = []
  for (const c of CREASE_CANDIDATES) {
    if (rand() > 0.6 * Math.min(1, quality.score + 0.1)) continue
    const pts = c.pts.map(([x, y]): P2 => [x + (rand() - 0.5) * 0.03, y + (rand() - 0.5) * 0.03])
    out.push({
      id: `c${out.length + 1}`,
      path: sampleSpline(pts, 5).map(toNorm),
      confidence: round(0.42 + rand() * 0.24),
      observation: `A short, faint crease ${c.where}. It does not match any of the five main lines, so it is shown but not named.`,
    })
  }
  return out
}

export function buildAnalysis(side: HandSide, plan: Plan[HandSide], photo: { width: number; height: number }, quality: PhotoQuality, seed: number): HandAnalysis {
  const rand = rng(seed + (side === 'left' ? 17 : 101))
  const features = FEATURE_ORDER.map((id) => buildFeature(id, side, plan[id], photo, rand))
  return {
    side,
    photo,
    quality,
    outline: sampleSpline(getStroke('outline').pts, 5).map(normaliser(side, photo)),
    features,
    palmShape: buildPalmShape(quality, seed, rand),
    otherCreases: buildOtherCreases(side, photo, quality, rand),
    methodVersion: DETECTOR_VERSION,
  }
}

const round = (n: number) => Math.round(n * 1000) / 1000
const clamp01 = (n: number) => Math.min(1, Math.max(0, n))

// ------------------------------------------------------------------ the report

const RANK_LENGTH: Record<Length, number> = { short: 0, medium: 1, long: 2 }
const RANK_CURVE: Record<Curve, number> = { straight: 0, gentle: 1, pronounced: 2 }

function compareFeature(name: string, left: FeatureResult, right: FeatureResult): string | null {
  const lower = name.toLowerCase()
  if (left.status === 'detected' && right.status === 'detected') {
    const bits: string[] = []
    const l = RANK_LENGTH[left.traits.length!]
    const r = RANK_LENGTH[right.traits.length!]
    bits.push(l === r ? `The ${lower} looks similar in length on both hands` : `The ${lower} looks longer on the ${l > r ? 'left' : 'right'} hand`)
    const cl = RANK_CURVE[left.traits.curve!]
    const cr = RANK_CURVE[right.traits.curve!]
    if (cl !== cr) bits.push(`and more curved on the ${cl > cr ? 'left' : 'right'}`)
    const same = l === r && cl === cr
    return `${bits.join(' ')}. ${
      same
        ? 'Traditionally, hands that match are read as consistency between what you start with and how life has shaped you.'
        : 'Traditionally, a difference between the hands is read as change between what you start with and how life has shaped you.'
    }`
  }
  if (left.status === 'detected' || right.status === 'detected') {
    const side = left.status === 'detected' ? 'left' : 'right'
    return `Only the ${side} hand showed this line clearly, so the two hands are not compared on it.`
  }
  return null
}

/** The detected source that scored best on either hand, with a clause about it. null when it was detected on neither. */
function bestDetected(src: ThemeSource, hands: Record<HandSide, HandAnalysis>): { side: HandSide; text: string } | null {
  let best: { side: HandSide; text: string; score: number } | null = null
  for (const side of ['left', 'right'] as const) {
    if (src === 'shape') {
      const sh = hands[side].palmShape
      if (sh.status === 'detected' && (!best || (sh.confidence ?? 0) > best.score)) best = { side, text: shapeClause(sh.traits), score: sh.confidence ?? 0 }
    } else {
      const f = hands[side].features.find((x) => x.id === src)!
      if (f.status === 'detected' && (!best || (f.confidence ?? 0) > best.score)) best = { side, text: lineClause(src, f.traits), score: f.confidence ?? 0 }
    }
  }
  return best && { side: best.side, text: best.text }
}

/** The "by theme" view: each theme is written only from the lines (and hand shape) that were detected, and says what it left out. */
export function buildThemes(hands: Record<HandSide, HandAnalysis>): ThemeSection[] {
  return THEMES.map((def): ThemeSection => {
    const used: { src: ThemeSource; side: HandSide; text: string }[] = []
    const leftOut: ThemeSource[] = []
    for (const src of def.sources) {
      const pick = bestDetected(src, hands)
      if (pick) used.push({ src, ...pick })
      else leftOut.push(src)
    }
    if (!used.length) return { themeId: def.id, title: def.title, label: 'traditional', traditional: null, basedOn: [], leftOut }
    const sentences = used.map((u) => `${sourceName(u.src)} (${u.side} hand): ${u.text}`)
    const skipped = leftOut.length
      ? `Left out, because ${leftOut.length === 1 ? 'it was' : 'they were'} not clearly seen: the ${listWords(leftOut.map((x) => sourceName(x).toLowerCase()))}.`
      : ''
    return {
      themeId: def.id,
      title: def.title,
      label: 'traditional',
      // one short paragraph per line of text: the introduction, one for each source that was used, what was left out, the reminder
      traditional: [def.intro, ...sentences, skipped, def.outro].filter(Boolean).join('\n'),
      basedOn: used.map((u) => u.src),
      leftOut,
    }
  })
}

function buildShapeSection(hands: Record<HandSide, HandAnalysis>): ShapeSection {
  const l = hands.left.palmShape
  const r = hands.right.palmShape
  let comparison: string | null = null
  if (l.status === 'detected' && r.status === 'detected') {
    comparison =
      l.traits.palm === r.traits.palm && l.traits.fingers === r.traits.fingers
        ? 'The hand shape looks the same on both hands, as it normally does.'
        : `The two photos suggest slightly different proportions (left: ${l.traits.palm} palm, ${l.traits.fingers} fingers; right: ${r.traits.palm} palm, ${r.traits.fingers} fingers). That usually comes from the angle of each photo, so no meaning is read into it.`
  } else if (l.status === 'detected' || r.status === 'detected') {
    comparison = `Only the ${l.status === 'detected' ? 'left' : 'right'} hand was clear enough to judge its shape, so the two hands are not compared.`
  }
  return {
    observed: { left: { status: l.status, text: l.observation }, right: { status: r.status, text: r.observation } },
    traditional: { left: shapeTraditionalText(l.status, l.traits), right: shapeTraditionalText(r.status, r.traits) },
    comparison,
  }
}

export function buildReport(hands: Record<HandSide, HandAnalysis>, createdAt: string): Report {
  const get = (side: HandSide, id: FeatureId) => hands[side].features.find((f) => f.id === id)!

  const sections: ReportSection[] = FEATURE_ORDER.map((id) => {
    const l = get('left', id)
    const r = get('right', id)
    return {
      featureId: id,
      title: FEATURE_NAMES[id],
      observed: {
        left: { status: l.status, text: l.observation },
        right: { status: r.status, text: r.observation },
      },
      traditional: {
        left: traditionalText(id, l.status, l.traits),
        right: traditionalText(id, r.status, r.traits),
      },
      comparison: compareFeature(FEATURE_NAMES[id], l, r),
    }
  })

  const both: string[] = []
  const one: string[] = []
  const none: string[] = []
  for (const id of FEATURE_ORDER) {
    const n = (['left', 'right'] as const).filter((s) => get(s, id).status === 'detected').length
    const name = FEATURE_NAMES[id].toLowerCase()
    if (n === 2) both.push(name)
    else if (n === 1) one.push(name)
    else none.push(name)
  }
  const sentences = ['Both photos were used.']
  if (both.length) sentences.push(`The ${listWords(both)} ${both.length === 1 ? 'was' : 'were'} found clearly on both hands.`)
  if (one.length) sentences.push(`The ${listWords(one)} ${one.length === 1 ? 'was' : 'were'} clear on only one hand.`)
  if (none.length) sentences.push(`The ${listWords(none)} could not be seen clearly, so nothing is said about ${none.length === 1 ? 'it' : 'them'}.`)
  sentences.push('Below, what was seen in the photos is kept apart from what the tradition says about it.')

  const uncertainty: string[] = []
  for (const side of ['left', 'right'] as const) {
    const Side = side === 'left' ? 'Left' : 'Right'
    for (const id of FEATURE_ORDER) {
      const f = get(side, id)
      if (f.status === 'uncertain') uncertainty.push(`${Side} hand, ${FEATURE_NAMES[id].toLowerCase()}: uncertain. Something line-like is there, but it was too faint or broken to judge, so only a tentative note is given.`)
      if (f.status === 'not_visible') uncertainty.push(`${Side} hand, ${FEATURE_NAMES[id].toLowerCase()}: not visible. Nothing is said about it.`)
    }
    const shape = hands[side].palmShape
    if (shape.status === 'uncertain') uncertainty.push(`${Side} hand, shape: uncertain. The hand was not clearly in view, so only a loose note is given.`)
    if (shape.status === 'not_visible') uncertainty.push(`${Side} hand, shape: not measured. Nothing is said about it.`)
    const n = hands[side].otherCreases.length
    if (n) {
      uncertainty.push(
        `${Side} hand: ${n} other ${n === 1 ? 'crease was' : 'creases were'} found that ${n === 1 ? 'does' : 'do'} not match a principal line. ${n === 1 ? 'It is' : 'They are'} drawn thinly and not named, and nothing is said about ${n === 1 ? 'it' : 'them'}.`,
      )
    }
    const q = hands[side].quality
    const issues: string[] = []
    if (q.sharpness !== 'good') issues.push('a little soft')
    if (q.lighting !== 'good') issues.push('not evenly lit')
    if (q.resolution !== 'good') issues.push('on the small side')
    if (issues.length) uncertainty.push(`The ${side} photo was ${issues.join(' and ')}, which can make faint lines harder to find.`)
  }

  return {
    summary: sentences.join(' '),
    sections,
    themes: buildThemes(hands),
    shape: buildShapeSection(hands),
    uncertainty,
    disclaimer: DISCLAIMER_LONG,
    generatedAt: createdAt,
  }
}

// ------------------------------------------------------------------ helpers for lists


/** One line that says what a reading found, for list rows. */
export function headlineFor(reading: Pick<Reading, 'hands'>): string {
  const both = FEATURE_ORDER.filter((id) => (['left', 'right'] as const).every((s) => reading.hands[s].features.find((f) => f.id === id)!.status === 'detected'))
  if (both.length) {
    const text = `${listWords(both.map((id) => FEATURE_NAMES[id].replace(' line', '').toLowerCase()))} ${both.length === 1 ? 'line' : 'lines'} clear on both hands`
    return text.charAt(0).toUpperCase() + text.slice(1)
  }
  const c = countStatuses(reading)
  return `${c.detected} of 10 lines detected, ${c.uncertain} uncertain`
}

