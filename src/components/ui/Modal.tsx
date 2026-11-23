import { useEffect, useId, useRef, type ReactNode } from 'react'
import Icon from './icons'

type Props = {
  open: boolean
  onClose: () => void
  title: string
  /** a line under the title */
  lead?: string
  children: ReactNode
  /** hide the corner close button, e.g. while a delete is running */
  locked?: boolean
}

/**
 * A dialog built on the browser's own <dialog>: it traps focus, closes on Escape and stays accessible without extra code.
 * Its contents are only rendered while open, so a form inside always starts empty.
 */
export default function Modal({ open, onClose, title, lead, children, locked = false }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={(e) => locked && e.preventDefault()}
      onClick={(e) => {
        if (e.target === ref.current && !locked) onClose()
      }}
      className="m-auto w-[min(92vw,34rem)] rounded-3xl border border-ink/10 bg-surface p-0 text-ink shadow-2xl backdrop:bg-ink/40 backdrop:backdrop-blur-sm"
    >
      {open && (
        <div className="relative p-6 md:p-8">
          {!locked && (
            <button type="button" onClick={onClose} aria-label="Close" className="absolute right-4 top-4 grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-ink/5 hover:text-ink">
              <Icon name="x" />
            </button>
          )}
          <h2 id={titleId} className="pr-8 font-display text-2xl font-normal tracking-tight">
            {title}
          </h2>
          {lead && <p className="mt-2 text-sm text-muted">{lead}</p>}
          <div className="mt-5">{children}</div>
        </div>
      )}
    </dialog>
  )
}
