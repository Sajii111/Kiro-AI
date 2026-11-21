// SAMPLE BACKEND ONLY. A rule-based stand-in for the grounded language model.
//
// It behaves the way the real chat must:
//   - it answers only from this reading's findings and report (never invents a line),
//   - it uses earlier messages of the same conversation for follow-ups ("and the left hand?"),
//   - it says plainly when a line was uncertain or not visible,
//   - it says what the tradition says about a theme (personality, career, money, relationships, future),
//     from the report's themes, always as a traditional reading and never as advice or a forecast,
//   - it declines medical diagnosis, financial, employment and relationship advice, lifespan, and predictions,
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

// Asking what WILL happen, or to be told the future.
const PREDICT = /\b(will i|am i going to|is it going to|going to happen|what will happen|predict\w*|tell me my future|my future|forecast\w*|fortune ?tell\w*|what does the future)\b/
// Asking what to DO.
const ADVICE = /\b(should i|what should i|is it (a good|the right)|can i trust|advice|advise|recommend\w*)\b/
const ASKS_TO_DECIDE = (t: string) => PREDICT.test(t) || ADVICE.test(t)

// Questions a reading never answers, whatever the wording.
const HARD_BOUNDARIES: { kind: BoundaryKind; test: (t: string) => boolean; reply: string }[] = [
  {
    kind: 'medical',
    test: (t) => /\b(health|healthy|sick|illness|disease|cancer|diabetes|heart attack|heart disease|heart problem|(see|visit|consult|ask|call) (a|my|the) doctor|my doctor|doctors? (said|says|told)|diagnos\w*|symptom\w*|pregnan\w*|medicine|medication|surgery|mental health|depress\w*)\b/.test(t),
    reply:
      'I can’t say anything about health or medical questions, and a palm can’t diagnose anything. Palmistry is a traditional practice for reflection, not a way to see the body, and it should never replace a doctor. If you are worried about your health, please speak to a medical professional.',
  },
  {
    kind: 'lifespan',
    test: (t) => /\b(how long (will|do|am) i (live|last)|when (will|am) i (die|going to die)|lifespan|life expectancy|live to|die|death)\b/.test(t),
    reply:
      'The life line is not a measure of how long anyone will live. That is a common myth. In the tradition it is read as a theme of energy and vitality, and I can tell you what was found about it in your photos if you like.',
  },
  {
    kind: 'financial',
    test: (t) => /\b(invest\w*|stocks?|crypto\w*|bitcoin|lottery|gambl\w*|salary|debts?|loans?|tax(es)?)\b/.test(t),
    reply:
      'I can’t give money or financial guidance, and your palms can’t tell you anything about it. This reading is for reflection and entertainment only. A qualified adviser is the right place for financial questions.',
  },
  {
    kind: 'employment',
    test: (t) => /\b(hired|hiring|promotion|interview\w*|employer|employment|resign\w*)\b/.test(t),
    reply:
      'I can’t advise on jobs or careers, and a palm reading shouldn’t be used to make decisions about work. The reading speaks only in general traditional themes, such as temperament, and I can explain any of those.',
  },
  {
    kind: 'relationship',
    test: (t) => /\b(marry|marries|married|marriage|divorc\w*|soul ?mate|break ?up|cheat\w*|boyfriend|girlfriend|husband|wife|fianc\w*|spouse)\b/.test(t),
    reply:
      'I can’t give relationship advice or say what will happen with another person. The heart line is traditionally read as a theme of emotional style, and I can tell you what was found on yours. Decisions about people are best made with people you trust.',
  },
]

// Topics a reading CAN speak about as a traditional theme, but not as advice or a forecast. These only decline
// when the question asks what will happen or what to do.
const SOFT_BOUNDARIES: { kind: BoundaryKind; test: (t: string) => boolean; reply: string }[] = [
  {
    kind: 'financial',
    test: (t) => /\b(money|finance\w*|rich|wealth\w*|income|prosper\w*|fortune)\b/.test(t),
    reply:
      'I can’t give money or financial guidance, and your palms can’t tell you how things will go with money. This reading is for reflection and entertainment only. A qualified adviser is the right place for financial questions.',
  },
  {
    kind: 'employment',
    test: (t) => /\b(job|jobs|career|profession\w*|work|business|employed)\b/.test(t),
    reply:
      'I can’t advise on jobs or careers, and a palm reading shouldn’t be used to make decisions about work or to say how a career will go. The reading speaks only in general traditional themes, such as temperament, and I can explain any of those.',
  },
  {
    kind: 'relationship',
    test: (t) => /\b(partner|relationships?|love|dating|romance|romantic)\b/.test(t),
    reply:
      'I can’t give relationship advice or say what will happen with another person. The heart line is traditionally read as a theme of emotional style, and I can tell you what was found on yours. Decisions about people are best made with people you trust.',
  },
]

const THEME_PATTERNS: Record<ThemeId, RegExp> = {
  personality: /\b(personality|character|temperament|traits?|what am i like|who am i|my nature)\b/,
  career: /\b(career|careers|profession\w*|work|working|job|jobs|vocation|business|occupation)\b/,
  financial: /\b(financ\w*|money|wealth\w*|prosper\w*|rich|riches|income|abundance)\b/,
  relationships: /\b(relationships?|love|romance|romantic|emotion\w*|feelings?|partner|dating|family|friendships?)\b/,
  future: /\b(future|outlook|direction|life direction)\b/,
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
      parts.push(`${sideName(side)} hand: the ${name} was not visible in this photo, so I won’t describe it or say what it means.`)
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

/** Declines to predict, and offers the one thing the tradition does say: the future outlook theme, as a reflection. */
function declinePrediction(reading: Reading): ChatAnswer {
  const base = 'I can’t predict the future. Palmistry here is a traditional practice for reflection and entertainment, and no line says what will happen to anyone.'
  const theme = themeOf(reading, 'future')
  if (!theme?.traditional) return { text: base, flags: { boundary: 'prediction', disclaimer: true } }
  return {
    text: `${base}\n\nWhat the tradition does say, as a theme to reflect on:\n\n${theme.traditional}`,
    refs: { featureIds: theme.basedOn.filter((x): x is FeatureId => x !== 'shape'), section: 'themes' },
    flags: { boundary: 'prediction', disclaimer: true },
  }
}

/** What the tradition says about a theme, from the report's themes. Never about a line that was not seen. */
function explainTheme(reading: Reading, ids: ThemeId[]): ChatAnswer {
  const parts: string[] = []
  const lines = new Set<FeatureId>()
  let anyClaim = false
  for (const id of ids) {
    const th = themeOf(reading, id)
    if (!th) continue
    if (th.traditional) {
      anyClaim = true
      parts.push(`${th.title}, as the tradition reads it:\n${th.traditional}`)
      for (const x of th.basedOn) if (x !== 'shape') lines.add(x)
    } else {
      const names = th.leftOut.map((x) => (x === 'shape' ? 'hand shape' : FEATURE_NAMES[x].toLowerCase()))
      parts.push(`${th.title}: nothing is said, because the ${names.join(', ')} ${names.length === 1 ? 'was' : 'were'} not clearly seen in this reading.`)
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
    if (o.status === 'not_visible') parts.push(`${sideName(side)} hand: the shape of the hand could not be measured in this photo, so I won’t describe it.`)
    else {
      anyClaim = true
      parts.push(`${sideName(side)} hand (${STATUS_LABEL[o.status].toLowerCase()}): ${o.text}${trad ? `\n${trad}` : ''}`)
    }
  }
  if (sides.length === 2 && sh.comparison) parts.push(`Side by side: ${sh.comparison}`)
  return { text: parts.join('\n\n'), refs: { section: 'shape' }, flags: { disclaimer: anyClaim, boundary: anyClaim ? undefined : 'not_seen' } }
}

const MORE = /\b(more|why|elaborate|explain|what do you mean|how so|go on|and (the )?(left|right)|other hand|what about)\b/

export function answer(raw: string, ctx: ChatContext): ChatAnswer {
  const t = raw.toLowerCase().replace(/[’]/g, "'")
  const { reading, profile } = ctx

  // 1. Someone else's name: this chat belongs to one profile
  for (const other of ctx.otherProfiles) {
    if (other.name.trim().length >= 2 && other.name.toLowerCase() !== profile.name.toLowerCase() && new RegExp(`\\b${escapeRegExp(other.name.toLowerCase())}\\b`).test(t)) {
      return {
        text: `That sounds like a question about ${other.name}. Each chat here belongs to one hand profile and one reading, so I can’t use ${other.name}’s findings in ${profile.name}’s chat. Switch to ${other.name}’s profile and ask there, and nothing will get mixed up.`,
        flags: { switchProfileId: other.id },
      }
    }
  }

  // 2. Things this reading never does, whatever the wording
  for (const b of HARD_BOUNDARIES) {
    if (b.test(t)) return { text: b.reply, flags: { boundary: b.kind, disclaimer: true } }
  }
  // 2b. A theme the tradition does speak about, but asked as "will I..." or "should I...": decline the forecast or the advice
  if (ASKS_TO_DECIDE(t)) {
    for (const b of SOFT_BOUNDARIES) {
      if (b.test(t)) return { text: b.reply, flags: { boundary: b.kind, disclaimer: true } }
    }
    if (PREDICT.test(t)) return declinePrediction(reading)
    return {
      text: 'I can’t tell you what to do or whether something is a good idea. Palmistry here is a traditional practice for reflection and entertainment. I can describe what was found in your photos and what the tradition says about each line.',
      flags: { boundary: 'off_topic', disclaimer: true },
    }
  }

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
  if (themes.length > 0 && !asksUnclear) return explainTheme(reading, themes)

  // 6. Questions about the reading as a whole
  if (asksUnclear) {
    const items = reading.report.uncertainty
    return {
      text: items.length
        ? `Here is what was unclear or missing in this reading:\n\n${items.map((i) => `• ${i}`).join('\n')}\n\nI won’t guess at any of these. A clearer photo (daylight, palm flat, in focus) usually helps.`
        : 'Every principal line was found clearly on both hands, so there is nothing unclear to report.',
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
      text: `${DISCLAIMER_SHORT} Finding lines in a photo is also genuinely hard, which is why every line is marked detected, uncertain or not visible, and why I only talk about what was found.`,
      flags: { disclaimer: true },
    }
  }
  if (greets) {
    return { text: `Hello. This chat is about ${profile.name}’s reading. Ask about any line, ask for a summary, or ask me to compare the two hands.` }
  }
  if (thanks) {
    return { text: 'You’re welcome. Ask about any line, or ask me to compare your hands.' }
  }

  // 7. Anything else
  const status = FEATURE_ORDER.map((id) => {
    const s = reading.report.sections.find((x) => x.featureId === id)!
    const bits = (['right', 'left'] as const).map((side) => `${side} ${STATUS_LABEL[s.observed[side].status].toLowerCase()}`)
    return `• ${s.title}: ${bits.join(', ')}`
  })
  return {
    text: `I can only talk about what was found in this reading. Try asking about one of the lines, or ask me to compare your hands.\n\n${status.join('\n')}`,
    flags: { boundary: 'off_topic' },
  }
}

