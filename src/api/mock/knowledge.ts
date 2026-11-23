// SAMPLE BACKEND ONLY. A tiny stand-in for the curated palmistry knowledge base.
// The real backend grounds a language model in a curated knowledge base (backend/app/llm/kb/*.json). Here the same entries'
// short clauses are copied as fixed sentences, in the same fortune teller's voice and the same plain, everyday words: every
// line speaks to "you", foretells what the line promises about love, work and success, creativity, travel and change, keeps
// time soft ("soon", "in time"), and never touches health, length of life, money advice or misfortune. Keep it in step with
// backend/app/llm/knowledge.py (the data parts are generated from the JSON files, so the two cannot drift apart by hand).

import type { FeatureId, FeatureStatus, FeatureTraits, PalmShapeTraits, ThemeId, ThemeSource } from '../types'

export const KB_VERSION = 'sample-kb 3.0'

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
  /** what the line is the line of, finishing the sentence "Your heart line ..." */
  theme: string
  length: Record<Length, string>
  curve: Record<Curve, string>
  clarity: Record<Clarity, string>
}

const KB: Record<FeatureId, Entry> = {
  heart: {
    theme: 'is the line of love: it shows how you love, and how easily people get close to you',
    length: {
      long: 'a long heart line means an open, generous heart: love comes to you easily, and you give plenty back',
      medium: 'a heart line of medium length means a steady heart: you give love freely without losing yourself, and your relationships grow warm and close',
      short: 'a shorter heart line means a private heart: love comes to you slowly, and it means more because you waited for it',
    },
    curve: {
      straight: 'its straight course shows you love in a direct, honest way: you say what you feel, and the people close to you trust you',
      gentle: 'its gentle curve shows you are warm and easy to be around: people feel at home with you, and affection follows you',
      pronounced: 'its strong curve shows you love out loud: your feelings are easy to see, and passion will mark the most important relationships of your life',
    },
    clarity: {
      clear: 'clearly marked, it means you understand your own feelings: you know what you want in love, and you are sure of your way',
      deep: 'cut deep, it means your feelings run deep: when you love, you love completely, and you are loved the same way in return',
    },
  },
  head: {
    theme: 'is the line of the mind: it shows how you think, what you are curious about, and where your ideas will take you',
    length: {
      long: 'a long head line means a thorough mind that sees the whole picture: your ideas will take you far',
      medium: 'a head line of medium length means a mind that is both practical and imaginative: you will find a way through almost any problem',
      short: 'a shorter head line means a quick, direct mind that goes straight to the point: you decide fast, and your decisions turn out well',
    },
    curve: {
      straight: 'its straight course shows a practical, logical mind: you think things through, and other people will come to rely on you',
      gentle: 'its gentle slope shows a mind that mixes logic with imagination: you adjust easily when things change, and good ideas come to you from unexpected places',
      pronounced: 'its steeper slope shows an imaginative, creative mind: you dream big, and what you imagine will find its way into the real world',
    },
    clarity: {
      clear: 'clearly marked, it means a clear, orderly way of thinking: your mind knows where it is going',
      deep: 'cut deep, it means strong focus: once you set your mind on something, very little will turn you away from it',
    },
  },
  life: {
    theme: 'is the line of your energy: it shows how much drive you carry and how well you handle change',
    length: {
      long: 'a long life line means plenty of stamina: you will meet every change with strength to spare',
      medium: 'a life line of medium length means an even rhythm of work and rest: you will find a good balance between pushing on and slowing down',
      short: 'a shorter life line means energy that you spend wisely: you do not waste yourself, and whatever you put your effort into will do well',
    },
    curve: {
      straight: 'its straight course shows a calm, even pace: you move through life without rushing, and change will find you ready',
      gentle: 'its gentle, wide sweep shows a generous, enthusiastic nature: you give a lot of yourself, and the world gives back',
      pronounced: 'its strong curve around the thumb shows you love to be on the move: you like action, and adventure will keep finding you',
    },
    clarity: {
      clear: 'clearly marked, it means energy you can count on: it is there when you need it',
      deep: 'cut deep, it means a strong nature: you bounce back quickly after setbacks, and you carry other people along with you',
    },
  },
  fate: {
    theme: 'is the line of direction: it shows what you are aiming for in life and how your path takes shape',
    length: {
      long: 'a long fate line means a strong sense of direction: you will know what you want, and your path rises steadily toward it',
      medium: 'a fate line of medium length means a direction that takes shape over time: what you want becomes clearer with every step you take',
      short: 'a shorter fate line means a free path that you make up as you go: you follow what interests you, and doors open for people who stay curious',
    },
    curve: {
      straight: 'its straight course shows a steady purpose: once you choose a road, you walk it with confidence',
      gentle: 'its gentle drift shows plans that can change: you will change course smoothly, and each turn leads somewhere good',
      pronounced: 'its winding course shows changes of direction along the way: your path will turn more than once, and each turn will open up your world',
    },
    clarity: {
      clear: 'clearly marked, it means you know what matters to you: you know your own mind, and it guides you well',
      deep: 'cut deep, it means strong determination: whatever you set out to do, you will see it through',
    },
  },
  sun: {
    theme: 'is the line of success and recognition: it shows where your creativity shines and where people will notice you',
    length: {
      long: 'a long sun line means a big appetite for creative things: your talents will be seen, and applause will find you',
      medium: 'a sun line of medium length means a quiet joy in beautiful things: the people who matter will notice your talents',
      short: 'a shorter sun line means you find happiness in small, private things: your best moments will be your own, and there will be many',
    },
    curve: {
      straight: 'its straight course shows steady, easy creativity: your gifts come naturally, and they last',
      gentle: 'its gentle bend shows a playful, varied imagination: you will try your hand at many things, and enjoy each one',
      pronounced: 'its strong bend shows sudden bursts of creativity: your best ideas will arrive when you least expect them',
    },
    clarity: {
      clear: 'clearly marked, it means creativity that shows in everyday life: other people notice the spark you bring to what you do',
      deep: 'cut deep, it means a strong creative drive: you will keep making things, and what you make will make you stand out',
    },
  },
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/**
 * What a line's length, curve and (when asked for) clarity foretell, one capitalised clause each. A clause that carries on from
 * the one before ("Its straight course ...") is given its noun when it comes first.
 */
function sentencesFor(id: FeatureId, traits: FeatureTraits, clarity: boolean): string[] {
  const e = KB[id]
  const parts: string[] = []
  if (traits.length) parts.push(cap(e.length[traits.length]))
  if (traits.curve) parts.push(cap(e.curve[traits.curve]))
  if (clarity && traits.clarity && traits.clarity !== 'faint') parts.push(cap(e.clarity[traits.clarity]))
  if (parts.length && parts[0].startsWith('Its ')) parts[0] = `Your ${FEATURE_NAMES[id].toLowerCase()}’s ${parts[0].slice(4)}`
  return parts
}

/**
 * What a line foretells, for one line on one hand. Returns null when the line was not seen, so nothing is claimed. For an
 * uncertain line only a rough hint of its general meaning is offered, with no detail about its shape.
 */
export function traditionalText(id: FeatureId, status: FeatureStatus, traits: FeatureTraits): string | null {
  if (status === 'not_visible') return null
  const name = FEATURE_NAMES[id].toLowerCase()
  const e = KB[id]
  if (status === 'uncertain') {
    return `Only a rough hint, because your ${name} was too faint in the photo to read properly: your ${name} ${e.theme}. Its length and shape could not be read.`
  }
  return `Your ${name} ${e.theme}. ${sentencesFor(id, traits, true).join('. ')}.`
}

// ------------------------------------------------------------------ the shape of the hand

export type Element = 'earth' | 'air' | 'water' | 'fire'

/** The traditional element of a hand, from how broad the palm is and how long the fingers are. null when either was not judged. */
export function elementOf(t: PalmShapeTraits): Element | null {
  if (!t.palm || !t.fingers) return null
  if (t.palm === 'square') return t.fingers === 'short' ? 'earth' : 'air'
  return t.fingers === 'long' ? 'water' : 'fire'
}

const ELEMENT_KB: Record<Element, { named: string; shape: string; theme: string; fortune: string }> = {
  earth: { named: 'an earth hand', shape: 'a square palm with shorter fingers', theme: 'a practical, steady, hands-on nature', fortune: 'what you build with patience will last' },
  air: { named: 'an air hand', shape: 'a square palm with longer fingers', theme: 'a curious, quick mind and a way with words', fortune: 'conversations and new ideas will open doors for you' },
  water: { named: 'a water hand', shape: 'a long palm with longer fingers', theme: 'a sensitive, thoughtful heart with good gut feelings', fortune: 'you will notice what other people miss' },
  fire: { named: 'a fire hand', shape: 'a long palm with shorter fingers', theme: 'an energetic, quick-to-act, enthusiastic nature', fortune: 'your boldness will start things that other people only dream of' },
}

/** What the shape of one hand foretells. null when the shape was not seen, so nothing is claimed. */
export function shapeTraditionalText(status: FeatureStatus, traits: PalmShapeTraits): string | null {
  if (status === 'not_visible') return null
  const el = elementOf(traits)
  if (status === 'uncertain' || !el) {
    return 'Only a rough hint, because your hand was not clearly in view: palmistry sorts hands into four types (earth, air, water and fire), but yours cannot be named from this photo.'
  }
  const e = ELEMENT_KB[el]
  return `${cap(e.shape)} makes ${e.named}. You have ${e.theme}, and ${e.fortune}.`
}

// ------------------------------------------------------------------ how two hands are read together

/** What it foretells when the two hands match, and when they differ (the tail of a line's comparison). */
export const COMPARE_SAME = 'When the two hands match, what you were born with and what you have made of it agree: you are becoming who you were meant to be.'
export const COMPARE_DIFFER = 'When the two hands differ, you have grown beyond where you started: life has changed you, and that change is part of your story.'

// ------------------------------------------------------------------ the themes

export type ThemeDef = {
  id: ThemeId
  title: string
  /** what this theme is read from: one sentence */
  intro: string
  /** the sources, in the order the reader lists them */
  sources: ThemeSource[]
  /** the line that closes every theme */
  outro: string
}

export const THEMES: ThemeDef[] = [
  {
    id: 'personality',
    title: 'Your personality',
    intro: 'Your personality is read from the shape of your hand together with your head, heart and life lines: how you think, how you feel and how you use your energy.',
    sources: ['shape', 'head', 'heart', 'life'],
    outro: 'This is the personality that carries you through everything that comes. You can count on it.',
  },
  {
    id: 'career',
    title: 'Work and career',
    intro: 'Your work life is read from your fate line (your sense of direction), your sun line (what brings you recognition) and your head line (how you work).',
    sources: ['fate', 'sun', 'head'],
    outro: 'Your lines say that doors will open for you in the work you care about.',
  },
  {
    id: 'financial',
    title: 'Money and success',
    intro: 'Money and success are not read from a single mark. They are read from your sun line (what brings you rewards), your head line (your practical sense) and your fate line (how steady your path is).',
    sources: ['sun', 'head', 'fate'],
    outro: 'Good things come to people who use their talents well, and your palm says that you are one of them.',
  },
  {
    id: 'relationships',
    title: 'Love and relationships',
    intro: 'Love is read mainly from your heart line, with your head line (how you put feelings into words) and your life line (how much warmth you carry).',
    sources: ['heart', 'head', 'life'],
    outro: 'Your lines promise love that is real and lasting, to anyone who keeps their heart open.',
  },
  {
    id: 'future',
    title: 'What lies ahead',
    intro: 'What lies ahead is read from your fate line (your direction), your sun line (how satisfied you will feel) and your life line (your energy).',
    sources: ['fate', 'sun', 'life'],
    outro: 'The road ahead is bright for people who walk it with an open heart. A palm shows the shape of the road, not every step: the steps are yours.',
  },
]

export const THEME_ORDER: ThemeId[] = THEMES.map((t) => t.id)

export const sourceName = (src: ThemeSource): string => (src === 'shape' ? 'Hand shape' : FEATURE_NAMES[src])

/** "a, b and c" */
export function listWords(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** What a detected line foretells in a theme, from its length and curve. */
export function lineClause(id: FeatureId, traits: FeatureTraits): string {
  return `${sentencesFor(id, traits, false).join('. ')}.`
}

/** What a detected hand shape foretells in a theme. */
export function shapeClause(traits: PalmShapeTraits): string {
  const el = elementOf(traits)
  if (!el) return ''
  const e = ELEMENT_KB[el]
  return `${cap(e.shape)} makes ${e.named}: you have ${e.theme}, and ${e.fortune}.`
}
