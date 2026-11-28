import { Fragment, type ReactNode } from 'react'
import { t } from './index'

/**
 * A whole sentence with pieces of the page in it (a name in bold, a link, a number), in the chosen language.
 * `tx('Unlock {name} first', { name: <strong>Sam</strong> })`: the dictionary may move `{name}` anywhere, because Sinhala and
 * Tamil put the words in a different order from English. Without this a sentence would be glued together from English-ordered
 * pieces around the name.
 */
export function tx(key: string, parts: Record<string, ReactNode>): ReactNode {
  const pieces = t(key).split(/\{(\w+)\}/)
  return pieces.map((piece, i) => {
    if (i % 2 === 0) return piece ? <Fragment key={i}>{piece}</Fragment> : null
    const part = piece in parts ? parts[piece] : `{${piece}}`
    return <Fragment key={i}>{typeof part === 'string' ? t(part) : part}</Fragment>
  })
}
