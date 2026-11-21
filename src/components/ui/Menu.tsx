import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

type Props = {
  /** what the button shows */
  button: ReactNode
  ariaLabel: string
  children: (close: () => void) => ReactNode
  align?: 'left' | 'right'
  className?: string
  panelClassName?: string
}

/** A small pop-up menu. Closes on Escape, on a click outside, and when an item asks it to. */
export default function Menu({ button, ariaLabel, children, align = 'right', className = '', panelClassName = '' }: Props) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={root} className={`relative ${className}`}>
      <button type="button" aria-label={ariaLabel} aria-haspopup="true" aria-expanded={open} aria-controls={open ? panelId : undefined} onClick={() => setOpen((o) => !o)}>
        {button}
      </button>
      {open && (
        <div
          id={panelId}
          className={`absolute top-full z-50 mt-2 min-w-64 max-w-[calc(100vw-2rem)] rounded-2xl border border-ink/10 bg-surface p-2 shadow-xl ${align === 'right' ? 'right-0' : 'left-0'} ${panelClassName}`}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}
