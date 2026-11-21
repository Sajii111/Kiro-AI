// SAMPLE BACKEND ONLY. A tiny stand-in for the curated palmistry knowledge base.
// The real backend grounds a language model in a much larger, curated knowledge base. Here the same idea is
// shown with fixed, cautious sentences: every claim is phrased as "in traditional palmistry...", is about
// general temperament, and never gives medical, financial, employment or relationship advice.

import type { FeatureId, FeatureStatus, FeatureTraits, PalmShapeTraits, ThemeId, ThemeSource } from '../types'

export const KB_VERSION = 'sample-kb 0.2'

export { FEATURE_ORDER } from '../../lib/features'

export const FEATURE_NAMES: Record<FeatureId, string> = {
  heart: 'Heart line',
  head: 'Head line',
  life: 'Life line',
  fate: 'Fate line',
  sun: 'Sun line',
}

type Length = NonNullable<FeatureTraits['length']>
type Curve = NonNullable<FeatureTraits['curve']>
type Clarity = Exclude<NonNullable<FeatureTraits['clarity']>, 'faint'>

type Entry = {
  /** the traditional theme, finishing the sentence "...is linked with" */
  theme: string
  length: Record<Length, string>
  curve: Record<Curve, string>
  clarity: Record<Clarity, string>
}

const KB: Record<FeatureId, Entry> = {
  heart: {
    theme: 'emotional style, and how closeness is approached',
    length: {
      long: 'a long line is often read as openness and warmth in how feelings are shared',
      medium: 'a line of medium length is often read as a balanced way of handling feelings',
      short: 'a shorter line is often read as a more private, self-contained emotional style',
    },
    curve: {
      straight: 'a straighter course is traditionally linked with a measured, direct manner',
      gentle: 'a gentle curve is often associated with an easygoing, affectionate manner',
      pronounced: 'a pronounced curve is often associated with expressive, demonstrative feelings',
    },
    clarity: {
      clear: 'a clearly marked line is read as feelings that are easy to recognise',
      deep: 'a deeply marked line is traditionally read as strongly felt emotions',
    },
  },
  head: {
    theme: 'thinking style, curiosity and attention',
    length: {
      long: 'a long line is often read as thorough, wide-ranging thinking',
      medium: 'a line of medium length is often read as a balance of practical and imaginative thought',
      short: 'a shorter line is often read as quick, direct thinking that likes to get to the point',
    },
    curve: {
      straight: 'a straight course is traditionally linked with practical, logical habits',
      gentle: 'a gentle slope is linked with a flexible mix of logic and imagination',
      pronounced: 'a steeper slope is linked with an imaginative, creative turn of mind',
    },
    clarity: {
      clear: 'a clearly marked line is read as a clear, settled way of thinking',
      deep: 'a deeply marked line is traditionally read as strong focus',
    },
  },
  life: {
    theme: 'energy, vitality and how steadily one moves through change (it says nothing about how long anyone will live)',
    length: {
      long: 'a long line is often read as steady stamina',
      medium: 'a line of medium length is often read as a balanced rhythm of effort and rest',
      short: 'a shorter line is often read as a compact, selective use of energy, and it is not about lifespan',
    },
    curve: {
      straight: 'a straighter course is often linked with a calm, even pace',
      gentle: 'a gentle, wide sweep is linked with generous energy and enthusiasm',
      pronounced: 'a deeply curved sweep around the thumb is linked with zest and a love of activity',
    },
    clarity: {
      clear: 'a clearly marked line is read as energy that is easy to rely on',
      deep: 'a deeply marked line is traditionally read as strong vitality',
    },
  },
  fate: {
    theme: 'sense of direction and self-direction (many hands have no distinct fate line, and that means nothing is missing)',
    length: {
      long: 'a long line is often read as a strong sense of direction',
      medium: 'a line of medium length is often read as direction that firms up over time',
      short: 'a shorter line is often read as a flexible, improvised path',
    },
    curve: {
      straight: 'a straight line is read as a steady sense of purpose',
      gentle: 'a gently drifting line is read as adaptable plans',
      pronounced: 'a curving line is read as changes of course along the way',
    },
    clarity: {
      clear: 'a clearly marked line is read as a clear sense of what matters',
      deep: 'a deeply marked line is traditionally read as strong determination',
    },
  },
  sun: {
    theme: 'creativity, appreciation and what brings a sense of satisfaction',
    length: {
      long: 'a long line is often read as a strong appetite for creative or appreciative pursuits',
      medium: 'a line of medium length is often read as a quiet enjoyment of beauty and recognition',
      short: 'a shorter line is often read as satisfaction found in small, private things',
    },
    curve: {
      straight: 'a straight line is read as steady, unforced creativity',
      gentle: 'a gently bending line is read as a playful, varied imagination',
      pronounced: 'a pronounced bend is read as bursts of inspiration',
    },
    clarity: {
      clear: 'a clearly marked line is read as creativity that is easy to see in everyday life',
      deep: 'a deeply marked line is traditionally read as a strong creative drive',
    },
  },
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/**
 * What the tradition says, for one line on one hand. Returns null when the line was not seen, so nothing
 * is claimed. For an uncertain line only the general theme is offered, with no detail about its shape.
 */
export function traditionalText(id: FeatureId, status: FeatureStatus, traits: FeatureTraits): string | null {
  if (status === 'not_visible') return null
  const name = FEATURE_NAMES[id].toLowerCase()
  const e = KB[id]
  if (status === 'uncertain') {
    return `Only as a loose idea: in traditional palmistry the ${name} is linked with ${e.theme}. Because the line was not clearly seen, nothing is said about its length or shape.`
  }
  const parts: string[] = []
  if (traits.length) parts.push(cap(e.length[traits.length]))
  if (traits.curve) parts.push(cap(e.curve[traits.curve]))
  if (traits.clarity && traits.clarity !== 'faint') parts.push(cap(e.clarity[traits.clarity]))
  return `In traditional palmistry the ${name} is linked with ${e.theme}. ${parts.join('. ')}.`
}

// ------------------------------------------------------------------ the shape of the hand

export type Element = 'earth' | 'air' | 'water' | 'fire'

/** The traditional element of a hand, from how broad the palm is and how long the fingers are. null when either was not judged. */
export function elementOf(t: PalmShapeTraits): Element | null {
  if (!t.palm || !t.fingers) return null
  if (t.palm === 'square') return t.fingers === 'short' ? 'earth' : 'air'
  return t.fingers === 'long' ? 'water' : 'fire'
}

const ELEMENT_KB: Record<Element, { named: string; shape: string; theme: string }> = {
  earth: { named: 'an earth hand', shape: 'a square palm with shorter fingers', theme: 'a practical, steady, hands-on temperament' },
  air: { named: 'an air hand', shape: 'a square palm with longer fingers', theme: 'a curious, communicative, analytical temperament' },
  water: { named: 'a water hand', shape: 'a long palm with longer fingers', theme: 'a sensitive, reflective, intuitive temperament' },
  fire: { named: 'a fire hand', shape: 'a long palm with shorter fingers', theme: 'an energetic, spontaneous, enthusiastic temperament' },
}

/** What the tradition says about the shape of one hand. null when the shape was not seen, so nothing is claimed. */
export function shapeTraditionalText(status: FeatureStatus, traits: PalmShapeTraits): string | null {
  if (status === 'not_visible') return null
  const el = elementOf(traits)
  if (status === 'uncertain' || !el) {
    return 'Only as a loose idea: traditional palmistry sorts hands into four shapes called earth, air, water and fire. Because the hand was not clearly in view, nothing is said about which one this is.'
  }
  const e = ELEMENT_KB[el]
  return `In traditional palmistry ${e.shape} is called ${e.named}, which is linked with ${e.theme}.`
}

// ------------------------------------------------------------------ the themes

export type ThemeDef = {
  id: ThemeId
  title: string
  /** what the tradition reads this theme from: one sentence */
  intro: string
  /** the sources, in the order the tradition lists them */
  sources: ThemeSource[]
  /** the reminder that closes every theme */
  outro: string
}

export const THEMES: ThemeDef[] = [
  {
    id: 'personality',
    title: 'Personality',
    intro: 'In traditional palmistry, personality is read from the overall shape of the hand together with the head, heart and life lines.',
    sources: ['shape', 'head', 'heart', 'life'],
    outro: 'This describes general temperament as a prompt for reflection. It is not a test of character.',
  },
  {
    id: 'career',
    title: 'Career and professional life',
    intro: 'In traditional palmistry, work and professional themes are read from the fate line (sense of direction), the sun line (what feels rewarding) and the head line (working style).',
    sources: ['fate', 'sun', 'head'],
    outro: 'This describes working temperament only. It is not career advice and does not say what job suits anyone.',
  },
  {
    id: 'financial',
    title: 'Financial and prosperity themes',
    intro: 'In traditional palmistry, prosperity is not read from a single mark. It is linked with the sun line (what feels rewarding), the head line (practical thinking) and the fate line (steadiness of direction).',
    sources: ['sun', 'head', 'fate'],
    outro: 'This is a theme about priorities and habits of mind. It says nothing about money, income or financial decisions.',
  },
  {
    id: 'relationships',
    title: 'Relationships and emotional life',
    intro: 'In traditional palmistry, relationships and emotional life are read mainly from the heart line, with the head line (how feelings are put into words) and the life line (warmth and energy).',
    sources: ['heart', 'head', 'life'],
    outro: 'This describes emotional style only. It is not relationship advice and says nothing about any other person.',
  },
  {
    id: 'future',
    title: 'Future outlook',
    intro: 'In traditional palmistry, the future is not read as events. The fate, sun and life lines are read as themes of direction, fulfilment and energy to reflect on.',
    sources: ['fate', 'sun', 'life'],
    outro: 'Nothing here predicts what will happen. The lines describe themes, and the future is not fixed by a palm.',
  },
]

export const THEME_ORDER: ThemeId[] = THEMES.map((t) => t.id)

export const sourceName = (src: ThemeSource): string => (src === 'shape' ? 'Hand shape' : FEATURE_NAMES[src])

/** "a, b and c" */
export function listWords(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** One clause about a detected line, from its length and curve. */
export function lineClause(id: FeatureId, traits: FeatureTraits): string {
  const e = KB[id]
  const parts: string[] = []
  if (traits.length) parts.push(cap(e.length[traits.length]))
  if (traits.curve) parts.push(cap(e.curve[traits.curve]))
  return `${parts.join('. ')}.`
}

/** One clause about a detected hand shape. */
export function shapeClause(traits: PalmShapeTraits): string {
  const el = elementOf(traits)
  if (!el) return ''
  const e = ELEMENT_KB[el]
  return `${cap(e.shape)} is called ${e.named}, linked with ${e.theme}.`
}
