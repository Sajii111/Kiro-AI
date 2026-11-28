// Lists the website text that has no Sinhala or Tamil translation yet, and translations nothing uses any more.
//   node scripts/i18n_check.mjs          (or: npm run i18n:check)
// The keys are the English sentences passed to t('...') in src/, plus src/i18n/server-text.json: sentences the server
// writes (error messages, notes, check results) that the website shows in the chosen language when it knows them, and the
// tagline from src/brand.ts (kept free of t() because vite.config.ts imports that file).
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const root = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const src = join(root, 'src')

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.tsx?$/.test(name)) out.push(p)
  }
  return out
}

// t("..."), t('...'), tx('...', parts), plural(n, 'one', 'many')
const CALL = /\btx?\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g
const PLURAL = /\bplural\([^,()]+(?:\([^()]*\))?,\s*('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")(?:,\s*('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"))?\)/g
const unquote = (q) => (q.startsWith('"') ? JSON.parse(q) : JSON.parse('"' + q.slice(1, -1).replace(/\\'/g, "'").replace(/"/g, '\\"') + '"'))

export function collectKeys() {
  const keys = new Set()
  for (const file of walk(src)) {
    if (file.includes(join('src', 'i18n'))) continue
    const text = readFileSync(file, 'utf8')
    for (const m of text.matchAll(CALL)) keys.add(unquote(m[1]))
    for (const m of text.matchAll(PLURAL)) {
      const one = unquote(m[1])
      const many = m[2] ? unquote(m[2]) : `${one}s`
      keys.add(`{n} ${one}`)
      keys.add(`{n} ${many}`)
    }
  }
  for (const k of JSON.parse(readFileSync(join(src, 'i18n', 'server-text.json'), 'utf8'))) keys.add(k)
  return [...keys]
}

if (process.argv[1] && process.argv[1].endsWith('i18n_check.mjs')) {
  const keys = collectKeys()
  let bad = 0
  for (const lang of ['si', 'ta']) {
    const dict = JSON.parse(readFileSync(join(src, 'i18n', `${lang}.json`), 'utf8'))
    const missing = keys.filter((k) => !dict[k])
    const unused = Object.keys(dict).filter((k) => !keys.includes(k))
    const placeholders = keys.filter((k) => dict[k] && (k.match(/\{\w+\}/g) || []).sort().join() !== (dict[k].match(/\{\w+\}/g) || []).sort().join())
    console.log(`${lang}: ${keys.length - missing.length} of ${keys.length} translated, ${unused.length} unused, ${placeholders.length} with different {placeholders}`)
    for (const k of missing) console.log(`  missing: ${k}`)
    for (const k of placeholders) console.log(`  placeholders differ: ${k}`)
    if (process.argv.includes('--unused')) for (const k of unused) console.log(`  unused: ${k}`)
    bad += missing.length + placeholders.length
  }
  process.exit(bad ? 1 : 0)
}
