// The website's languages: English (the source), Sinhala and Tamil.
//
// Every sentence on screen is written in English in the code and passed through t(). The English sentence is the key:
// si.json and ta.json map it to the Sinhala and Tamil wording. A sentence missing from a dictionary simply shows in
// English, so a new screen never breaks; `npm run i18n:check` lists what still needs translating.
//
// The chosen language is kept in this browser (localStorage). main.tsx loads its dictionary before the app starts, and
// changing the language reloads the page, so every screen (also text worked out once when a file loads) follows it.

export type Lang = 'en' | 'si' | 'ta'

export const LANGUAGES: { code: Lang; name: string; native: string; short: string }[] = [
  { code: 'en', name: 'English', native: 'English', short: 'EN' },
  { code: 'si', name: 'Sinhala', native: 'සිංහල', short: 'සිං' },
  { code: 'ta', name: 'Tamil', native: 'தமிழ்', short: 'த' },
]

const STORAGE_KEY = 'kiro-lang'

function savedLang(): Lang {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'si' || v === 'ta' || v === 'en') return v
  } catch {
    // storage blocked: English
  }
  return 'en'
}

/** The language this page shows. It changes only through setLanguage(), which reloads the page. */
export const lang: Lang = savedLang()

/** The locale used for dates and numbers. */
export const locale = lang === 'si' ? 'si-LK' : lang === 'ta' ? 'ta-LK' : 'en-GB'

let dict: Record<string, string> = {}

/** Loads the dictionary of the chosen language. main.tsx waits for it before importing the app. */
export async function loadLanguage(): Promise<void> {
  document.documentElement.lang = lang
  if (lang === 'si') dict = (await import('./si.json')).default as Record<string, string>
  else if (lang === 'ta') dict = (await import('./ta.json')).default as Record<string, string>
}

/** Saves the choice and reloads, so the whole site (and the next readings) use it. */
export function setLanguage(next: Lang): void {
  if (next === lang) return
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    return
  }
  window.location.reload()
}

/**
 * The words for `key` in the chosen language. `{name}` in the key is filled from `vars`; a value that is itself a known
 * word (for example the hand side "left") is translated too.
 */
export function t(key: string, vars?: Record<string, string | number | null | undefined>): string {
  const text = dict[key] || key
  if (!vars) return text
  return text.replace(/\{(\w+)\}/g, (m, k: string) => {
    if (!(k in vars)) return m
    const v = vars[k]
    if (v === null || v === undefined) return ''
    return typeof v === 'string' ? dict[v] || v : String(v)
  })
}

/**
 * A text the server wrote in English (a note, a reason, a step's detail): translated whole when the dictionary knows it, else
 * sentence by sentence (a note can be two fixed sentences in a row). A sentence the dictionary does not know stays English.
 */
export function tServer(text: string | null | undefined): string {
  if (!text) return ''
  if (lang === 'en' || dict[text]) return t(text)
  const whole = byPattern(text)
  if (whole !== null) return whole
  return text
    .split(/(?<=[.!?])\s+/)
    .map((s) => dict[s] || byPattern(s) || s)
    .join(' ')
}

let patterns: { re: RegExp; names: string[]; key: string }[] | null = null

/** A server sentence with numbers in it ("Both photos are 1056 px or less ..."), read against the keys that have {placeholders}. */
function byPattern(text: string): string | null {
  patterns ??= Object.keys(dict)
    .filter((k) => /\{\w+\}/.test(k))
    .map((key) => {
      const names: string[] = []
      const source = key
        .split(/(\{\w+\})/)
        .map((part) => {
          const m = /^\{(\w+)\}$/.exec(part)
          if (!m) return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
          names.push(m[1])
          return '(.+?)'
        })
        .join('')
      return { re: new RegExp(`^${source}$`), names, key }
    })
    // the key with the most fixed words wins ("{d} of 10 lines detected, ..." before "{detected} detected, ...")
    .sort((a, b) => b.key.replace(/\{\w+\}/g, '').length - a.key.replace(/\{\w+\}/g, '').length)
  for (const p of patterns) {
    const m = p.re.exec(text)
    if (!m) continue
    // a part that is itself a known sentence ("Sample result: 7 of 10 lines ...") is translated too
    const part = (v: string) => (/[A-Za-z]{2}/.test(v) ? dict[v] || byPattern(v) || v : v)
    return t(p.key, Object.fromEntries(p.names.map((n, i) => [n, part(m[i + 1])])))
  }
  return null
}

/** "1 reading", "3 readings", in the chosen language. */
export function plural(n: number, one: string, many = `${one}s`): string {
  return t(`{n} ${n === 1 ? one : many}`, { n })
}
