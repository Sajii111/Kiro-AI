// SAMPLE BACKEND ONLY. A rule-based stand-in for the grounded language model, in the reader's voice. Keep it in step with
// backend/app/llm/chat.py, which is the same thing in Python.
//
// It behaves the way the real chat must:
//   - it answers only from this reading's findings and report (never invents a line),
//   - it uses earlier messages of the same conversation for follow-ups ("and the left hand?"),
//   - it says plainly when a line was uncertain or not visible,
//   - it foretells: "will I ...?" about love, work, success or what lies ahead is answered from the report's themes, which are
//     written as predictions in soft time (never an age, a date or a count of months),
//   - it declines, in the reader's voice, what a palm never tells: health, pregnancy and children, how long anyone will live,
//     sums and investments, other people's hearts, and misfortune; it gives no orders or advice ("should I ...?"),
//   - it asks the person to switch profile when they ask about someone else.

import { DISCLAIMER_SHORT, PHOTO_TIPS } from '../../app/copy'
import { STATUS_LABEL } from '../../lib/status'
import type { BoundaryKind, FeatureId, HandProfile, HandSide, Message, MessageFlags, MessageRefs, Reading, ThemeId, ThemeSection } from '../types'
import { FEATURE_NAMES, FEATURE_ORDER, THEME_ORDER } from './knowledge'

export type ChatContext = {
  reading: Reading
  profile: HandProfile
  otherProfiles: HandProfile[]
  /** earlier messages of this conversation, oldest first */
  history: Message[]
}

export type ChatAnswer = { text: string; refs?: MessageRefs; flags?: MessageFlags }

const FEATURE_PATTERNS: Record<FeatureId, RegExp> = {
  heart: /\bheart\b/,
  head: /\bhead\b|\bintellect\b/,
  life: /\blife\b|\bvitality\b|\benergy\b/,
  fate: /\bfate\b|\bdestiny\b/,
  sun: /\bsun\b|\bapollo\b/,
}

// Asking what WILL happen, or to be told the future: the reading's own business, answered from the report's themes.
const PREDICT = /\b(will i|am i going to|is it going to|going to happen|what will happen|predict\w*|tell me my future|my future|forecast\w*|fortune ?tell\w*|what does the future|what lies ahead|what is coming|what's coming)\b/
// Asking what to DO: a reader foretells, and does not decide for anyone.
const ADVICE = /\b(should i|what should i|is it (a good|the right)|can i trust|advice|advise|recommend\w*)\b/

// Questions a reading never answers, whatever the wording. Each reply is the reader declining in her own voice, and pointing to
// what she does read.
const HARD_BOUNDARIES: { kind: BoundaryKind; test: (t: string) => boolean; reply: string }[] = [
  {
    kind: 'medical',
    test: (t) => /\b(health|healthy|sick|illness|disease|cancer|diabetes|heart attack|heart disease|heart problem|(see|visit|consult|ask|call) (a|my|the) doctor|my doctor|doctors? (said|says|told)|diagnos\w*|symptom\w*|pregnan\w*|fertil\w*|babies|baby|children|kids|have a child|medicine|medication|surgery|mental health|depress\w*)\b/.test(t),
    reply:
      'I don’t read health, pregnancy or children. A palm can’t tell you anything about your body, and I’m no substitute for a doctor. If something is worrying you, please talk to a doctor. Ask me about love, work, creativity or what lies ahead instead, and I’ll tell you what your lines say.',
  },
  {
    kind: 'lifespan',
    test: (t) => /\b(how long (will|do|am) i (live|last)|when (will|am) i (die|going to die)|lifespan|life expectancy|live to|die|death)\b/.test(t),
    reply:
      'The life line is not a clock. It shows your energy and how you handle change, not how long you will live, and nobody can read that from a palm. Ask me what your life line says about your energy and I’ll tell you.',
  },
  {
    kind: 'financial',
    test: (t) => /\b(invest\w*|stocks?|crypto\w*|bitcoin|lottery|gambl\w*|salary|debts?|loans?|tax(es)?)\b/.test(t),
    reply:
      'I don’t read sums, stocks or lotteries, and a palm can’t say how much money you will have. For money questions, ask a qualified adviser. Ask me about doing well in general and I’ll tell you what your lines say.',
  },
  {
    kind: 'employment',
    test: (t) => /\b(hired|hiring|interview\w*|employer|employment|resign\w*|quit my|fired|laid off)\b/.test(t),
    reply:
      'Who will hire you, or when, isn’t written in a palm, and I won’t pretend it is. What your lines do show is your drive and the recognition you will get. Ask me about your work in general and I’ll tell you.',
  },
  {
    kind: 'relationship',
    test: (t) => /\b(divorc\w*|break ?up|cheat\w*|unfaithful|affair|boyfriend|girlfriend|husband|wife|fianc\w*|spouse|my ex)\b/.test(t),
    reply:
      'I read your hands, not another person’s heart, so I can’t say what will happen between you and someone else, least of all break-ups or divorce. Your heart line shows how you love. Ask me about it and I’ll tell you what it says.',
  },
]

// Topics a reading CAN foretell, but not decide: these decline only when the question asks what to DO ("should I ...?").
const SOFT_BOUNDARIES: { kind: BoundaryKind; test: (t: string) => boolean; reply: string }[] = [
  {
    kind: 'financial',
    test: (t) => /\b(money|finance\w*|rich|wealth\w*|income|prosper\w*|fortune)\b/.test(t),
    reply:
      'What to do with your money isn’t for a palm to decide, so ask a qualified adviser. What I can tell you is what your lines say about doing well in general. Ask me and I’ll tell you.',
  },
  {
    kind: 'employment',
    test: (t) => /\b(job|jobs|career|profession\w*|work|business|employed)\b/.test(t),
    reply:
      'Whether to take a job or leave one is your choice, not a palm’s. What I can tell you is what your lines say about your drive and the recognition you will get. Ask me about your work and I’ll tell you.',
  },
  {
    kind: 'relationship',
    test: (t) => /\b(partner|relationships?|love|dating|romance|romantic|marry|marries|married|marriage|wedding|soul ?mate)\b/.test(t),
    reply:
      'Whether to stay or go, to trust or part, is your choice, not a palm’s. What I can tell you is what your heart line says about how you love. Ask me about it and I’ll tell you.',
  },
]

const THEME_PATTERNS: Record<ThemeId, RegExp> = {
  personality: /\b(personality|character|temperament|traits?|what am i like|who am i|my nature)\b/,
  career: /\b(career|careers|profession\w*|work|working|job|jobs|vocation|business|occupation)\b/,
  financial: /\b(financ\w*|money|wealth\w*|prosper\w*|rich|riches|income|abundance)\b/,
  relationships: /\b(relationships?|love|romance|romantic|emotion\w*|feelings?|partner|dating|family|friendships?|marry|marries|married|marriage|wedding|soul ?mate)\b/,
  future: /\b(future|outlook|direction|life direction|road ahead|what lies ahead|what is coming|what's coming)\b/,
}

const SHAPE_PATTERN = /\b(hand shape|palm shape|shape of (my|the) (hand|palm|hands|palms)|my hand type|hand type|earth hand|air hand|water hand|fire hand|four elements|elements?)\b/

function escapeRegExp(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const sideName = (s: HandSide) => (s === 'left' ? 'Left' : 'Right')

function lastRefs(history: Message[]): MessageRefs | undefined {
  for (let i = history.length - 1; i >= 0; i--) {
    const m = history[i]
    if (m.role === 'assistant' && m.refs?.featureIds?.length) return m.refs
  }
  return undefined
}

function explainFeature(reading: Reading, id: FeatureId, sides: HandSide[]): ChatAnswer {
  const section = reading.report.sections.find((s) => s.featureId === id)!
  const name = FEATURE_NAMES[id].toLowerCase()
  const parts: string[] = []
  let anyUnseen = false
  let anyClaim = false
  for (const side of sides) {
    const o = section.observed[side]
    const trad = section.traditional[side]
    if (o.status === 'not_visible') {
      anyUnseen = true
      parts.push(`${sideName(side)} hand: your ${name} was not clear enough in this photo, so I will not read it.`)
    } else {
      anyClaim = true
      parts.push(`${sideName(side)} hand (${STATUS_LABEL[o.status].toLowerCase()}): ${o.text}${trad ? `\n${trad}` : ''}`)
    }
  }
  if (sides.length === 2 && section.comparison) parts.push(`Side by side: ${section.comparison}`)
  return {
    text: parts.join('\n\n'),
    refs: { featureIds: [id], section: id, side: sides.length === 1 ? sides[0] : undefined },
    flags: { disclaimer: anyClaim, boundary: anyUnseen && !anyClaim ? 'not_seen' : undefined },
  }
}

const themeOf = (reading: Reading, id: ThemeId): ThemeSection | undefined => reading.report.themes.find((x) => x.themeId === id)

/** What the lines foretell about a theme, from the report's themes. Never about a line that was not seen. */
function explainTheme(reading: Reading, ids: ThemeId[]): ChatAnswer {
  const parts: string[] = []
  const lines = new Set<FeatureId>()
  let anyClaim = false
  for (const id of ids) {
    const th = themeOf(reading, id)
    if (!th) continue
    if (th.traditional) {
      anyClaim = true
      parts.push(`${th.title}, as your lines tell it:\n${th.traditional}`)
      for (const x of th.basedOn) if (x !== 'shape') lines.add(x)
    } else {
      const names = th.leftOut.map((x) => (x === 'shape' ? 'hand shape' : FEATURE_NAMES[x].toLowerCase()))
      parts.push(`${th.title}: I will say nothing about this, because the ${names.join(', ')} could not be seen clearly in your photos.`)
    }
  }
  return {
    text: parts.join('\n\n'),
    refs: { featureIds: FEATURE_ORDER.filter((x) => lines.has(x)), section: 'themes' },
    flags: { disclaimer: anyClaim, boundary: anyClaim ? undefined : 'not_seen' },
  }
}

function explainShape(reading: Reading, sides: HandSide[]): ChatAnswer {
  const sh = reading.report.shape
  const parts: string[] = []
  let anyClaim = false
  for (const side of sides) {
    const o = sh.observed[side]
    const trad = sh.traditional[side]
    if (o.status === 'not_visible') parts.push(`${sideName(side)} hand: the shape of the hand was not clear enough in this photo, so I will not read it.`)
    else {
      anyClaim = true
      parts.push(`${sideName(side)} hand (${STATUS_LABEL[o.status].toLowerCase()}): ${o.text}${trad ? `\n${trad}` : ''}`)
    }
  }
  if (sides.length === 2 && sh.comparison) parts.push(`Side by side: ${sh.comparison}`)
  return { text: parts.join('\n\n'), refs: { section: 'shape' }, flags: { disclaimer: anyClaim, boundary: anyClaim ? undefined : 'not_seen' } }
}

const MORE = /\b(more|why|elaborate|explain|what do you mean|how so|go on|and (the )?(left|right)|other hand|what about)\b/

const normalise = (raw: string) => raw.toLowerCase().replace(/[’]/g, "'")

function declineAdvice(): ChatAnswer {
  return {
    text: 'I don’t give orders or advice. What you choose is up to you: I tell you what your lines say. Ask me about any line, or about love, work, creativity or what lies ahead.',
    flags: { boundary: 'off_topic', disclaimer: true },
  }
}

/**
 * The answer to a question this reading never answers, or undefined when the question is one it may answer. Another profile's
 * name, health, lifespan, sums of money, a job offer, another person's heart, and "should I ...": each has fixed wording, in the
 * reader's voice. "Will I ...?" about love, work, success or what lies ahead is not declined: it is what a reading is for.
 */
export function boundaryAnswer(raw: string, ctx: ChatContext): ChatAnswer | undefined {
  const t = normalise(raw)
  const { profile } = ctx

  // 1. Someone else's name: this chat belongs to one profile
  for (const other of ctx.otherProfiles) {
    if (other.name.trim().length >= 2 && other.name.toLowerCase() !== profile.name.toLowerCase() && new RegExp(`\\b${escapeRegExp(other.name.toLowerCase())}\\b`).test(t)) {
      return {
        text: `That sounds like a question about ${other.name}. Each chat here belongs to one hand profile and one reading, so I can’t use ${other.name}’s reading in ${profile.name}’s chat. Switch to ${other.name}’s profile and ask there, and nothing will get mixed up.`,
        flags: { switchProfileId: other.id },
      }
    }
  }

  // 2. Things this reading never does, whatever the wording
  for (const b of HARD_BOUNDARIES) {
    if (b.test(t)) return { text: b.reply, flags: { boundary: b.kind, disclaimer: true } }
  }
  // 2b. A choice to make ("should I ...?"): a reader foretells and does not decide. A topic she does read gets words of its own
  if (ADVICE.test(t)) {
    for (const b of SOFT_BOUNDARIES) {
      if (b.test(t)) return { text: b.reply, flags: { boundary: b.kind, disclaimer: true } }
    }
    return declineAdvice()
  }
  return undefined
}

/** What is said to a question that has nothing to do with the reading: where the person can start instead. */
function offTopicAnswer(reading: Reading): ChatAnswer {
  const status = FEATURE_ORDER.map((id) => {
    const s = reading.report.sections.find((x) => x.featureId === id)!
    const bits = (['right', 'left'] as const).map((side) => `${side} ${STATUS_LABEL[s.observed[side].status].toLowerCase()}`)
    return `• ${s.title}: ${bits.join(', ')}`
  })
  return {
    text: `I only read palms, so I can’t help with that. Ask about one of your lines, about love, work or what lies ahead, or ask me to compare your hands.\n\n${status.join('\n')}`,
    flags: { boundary: 'off_topic' },
  }
}

/** The whole rule-based answer: the boundaries first, then the reading. */
export function answer(raw: string, ctx: ChatContext): ChatAnswer {
  return boundaryAnswer(raw, ctx) ?? ruleAnswer(raw, ctx)
}

/** The answer to a question that passed `boundaryAnswer`, from the reading and the conversation, in fixed wording. */
export function ruleAnswer(raw: string, ctx: ChatContext): ChatAnswer {
  const t = normalise(raw)
  const { reading, profile } = ctx

  // 3. Which lines and which hands are being asked about
  let ids = FEATURE_ORDER.filter((id) => FEATURE_PATTERNS[id].test(t))
  const wantLeft = /\bleft\b/.test(t)
  const wantRight = /\bright\b/.test(t)
  const wantBoth = /\b(both|compare|comparison|difference|differ\w*|side by side|each hand|left and right)\b/.test(t) || (wantLeft && wantRight)
  const sides: HandSide[] = wantBoth || (!wantLeft && !wantRight) ? ['left', 'right'] : wantLeft ? ['left'] : ['right']

  const asksUnclear =
    /\b(uncertain|unclear|not visible|missing|couldn't|could not|not clear|which lines|what wasn't|what was not)\b/.test(t) ||
    /\bwhy (wasn't|was not|isn't|is not|can't|couldn't|were|are)\b.*\b(lines?|shown|found|seen|visible)\b/.test(t)
  const asksPhoto = /\b(photo|photos|picture|image|retake|lighting|focus|blurry|better)\b/.test(t)
  const asksSummary = /\b(summary|summarise|summarize|overview|overall|findings|what did you find|tell me about (my|the) reading)\b/.test(t) || t.trim().length === 0
  const asksAccuracy = /\b(accurate|accuracy|science|scientific|true|real|reliable)\b/.test(t)
  const greets = /^(hello|hi|hey|good (morning|afternoon|evening))\b/.test(t.trim())
  const thanks = /\b(thanks|thank you|cheers)\b/.test(t)
  const wholeReading = asksUnclear || asksPhoto || asksSummary || asksAccuracy || greets || thanks || (wantBoth && ids.length === 0)

  // 4. A follow-up with no line named: use what the last answer was about
  const prev = lastRefs(ctx.history)
  if (ids.length === 0 && prev && !wholeReading && (MORE.test(t) || wantLeft || wantRight)) {
    ids = prev.featureIds ?? []
  }

  // 5. Questions about one or more lines
  if (ids.length === 1) return explainFeature(reading, ids[0], sides)
  if (ids.length > 1) {
    const results = ids.map((id) => explainFeature(reading, id, sides))
    return {
      text: results.map((r) => r.text).join('\n\n'),
      refs: { featureIds: ids, side: sides.length === 1 ? sides[0] : undefined },
      flags: { disclaimer: results.some((r) => r.flags?.disclaimer) },
    }
  }

  // 5b. Questions about the shape of the hand, and about a theme such as personality, career or relationships
  if (SHAPE_PATTERN.test(t) && !asksUnclear) return explainShape(reading, sides)
  const themes = THEME_ORDER.filter((id) => THEME_PATTERNS[id].test(t))
  if (themes.length === 0 && PREDICT.test(t)) themes.push('future') // "will I ...?" with no topic named is a question about the road ahead
  if (themes.length > 0 && !asksUnclear) return explainTheme(reading, themes)

  // 6. Questions about the reading as a whole
  if (asksUnclear) {
    const items = reading.report.uncertainty
    return {
      text: items.length
        ? `Here is what could not be seen clearly:\n\n${items.map((i) => `• ${i}`).join('\n')}\n\nI will not guess at what I cannot see. A clearer photo (daylight, palm flat, in focus) will help.`
        : 'Every main line was clear on both hands, so nothing is missing.',
      refs: { section: 'uncertainty' },
      flags: { boundary: items.length ? 'not_seen' : undefined },
    }
  }
  if (wantBoth) {
    const lines = reading.report.sections.map((s) => `• ${s.title}: ${s.comparison ?? 'not compared, because it was not seen clearly enough.'}`)
    return { text: `Here is how your two hands compare, line by line:\n\n${lines.join('\n')}`, refs: { section: 'comparison', featureIds: FEATURE_ORDER }, flags: { disclaimer: true } }
  }
  if (asksPhoto) {
    return { text: `A good photo makes the biggest difference. Try this:\n\n${PHOTO_TIPS.map((x) => `• ${x}`).join('\n')}` }
  }
  if (asksSummary) {
    return { text: reading.report.summary, refs: { section: 'summary', featureIds: FEATURE_ORDER }, flags: { disclaimer: true } }
  }
  if (asksAccuracy) {
    return {
      text: `${DISCLAIMER_SHORT} Finding lines in a photo is also genuinely hard, which is why every line is marked detected, uncertain or not visible, and why I speak only of what was found.`,
      flags: { disclaimer: true },
    }
  }
  if (greets) {
    return { text: `Welcome. Let us read ${profile.name}’s hands. Ask about any line, about love, work or what lies ahead, or ask me to compare the two hands.` }
  }
  if (thanks) {
    return { text: 'You are welcome. Ask about any line, about what lies ahead, or ask me to compare your hands.' }
  }

  // 7. Anything else
  return offTopicAnswer(reading)
}

