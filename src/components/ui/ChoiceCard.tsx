import type { ChangeEventHandler, ReactNode } from 'react'
import Icon from './icons'

/**
 * One option in a group of radio buttons, drawn as a card. The radio itself is hidden from the eye but is what the
 * keyboard and screen readers use, so arrow keys move between the cards. The chosen card says so three ways: a dark
 * border, a tint and a tick, so it never rests on colour alone.
 */
export default function ChoiceCard({
  name,
  value,
  checked,
  onChange,
  title,
  note,
  extra,
}: {
  name: string
  value: string
  checked: boolean
  onChange: ChangeEventHandler<HTMLInputElement>
  title: string
  note: string
  /** a small picture or swatch under the text (decorative) */
  extra?: ReactNode
}) {
  return (
    <label
      className={`cursor-pointer rounded-2xl border px-4 py-3 text-sm transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus ${
        checked ? 'border-ink bg-accent/15' : 'border-ink/15 hover:border-ink/30'
      }`}
    >
      <input type="radio" name={name} value={value} checked={checked} onChange={onChange} className="sr-only" />
      <span className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block font-medium">{title}</span>
          <span className="mt-0.5 block text-xs text-muted">{note}</span>
        </span>
        {checked && <Icon name="check" size={16} className="mt-0.5 shrink-0" />}
      </span>
      {extra}
    </label>
  )
}
