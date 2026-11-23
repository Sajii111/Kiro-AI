import { useCallback, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'

type Props = {
  before: ReactNode
  after: ReactNode
  beforeLabel?: string
  afterLabel?: string
  /** CSS aspect-ratio, e.g. "4 / 5" */
  aspect?: string
  className?: string
}

/**
 * Original-versus-processed slider. Drag the handle (or use the arrow keys) to wipe between two layers.
 * Both layers should fill their box (an <img> or <canvas> with object-cover).
 */
export default function CompareSlider({ before, after, beforeLabel = 'Original', afterLabel = 'Processed', aspect = '4 / 5', className = '' }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState(50)
  const dragging = useRef(false)

  const setFromEvent = useCallback((e: PointerEvent) => {
    const r = box.current?.getBoundingClientRect()
    if (!r) return
    setPos(Math.min(100, Math.max(0, ((e.clientX - r.left) / r.width) * 100)))
  }, [])

  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') setPos((p) => Math.max(0, p - 5))
    else if (e.key === 'ArrowRight') setPos((p) => Math.min(100, p + 5))
    else if (e.key === 'Home') setPos(0)
    else if (e.key === 'End') setPos(100)
    else return
    e.preventDefault()
  }

  return (
    <div
      ref={box}
      role="slider"
      tabIndex={0}
      aria-label={`${beforeLabel} versus ${afterLabel}`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pos)}
      aria-valuetext={`${Math.round(pos)}% ${beforeLabel}`}
      data-cursor-label="Drag"
      onKeyDown={onKey}
      onPointerDown={(e) => {
        dragging.current = true
        e.currentTarget.setPointerCapture(e.pointerId)
        setFromEvent(e)
      }}
      onPointerMove={(e) => dragging.current && setFromEvent(e)}
      onPointerUp={() => (dragging.current = false)}
      onPointerCancel={() => (dragging.current = false)}
      className={`relative w-full touch-none select-none overflow-hidden rounded-2xl border border-ink/10 bg-ink/5 ${className}`}
      style={{ aspectRatio: aspect }}
    >
      <div className="absolute inset-0">{before}</div>
      {/* the processed layer is revealed from the right, so the handle starts in the middle */}
      <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${pos}%)` }}>
        {after}
      </div>

      <span className="pointer-events-none absolute left-3 top-3 rounded-full bg-paper/80 px-3 py-1 text-xs backdrop-blur">{beforeLabel}</span>
      <span className="pointer-events-none absolute right-3 top-3 rounded-full bg-paper/80 px-3 py-1 text-xs backdrop-blur">{afterLabel}</span>

      <div className="pointer-events-none absolute inset-y-0 w-px bg-paper shadow-[0_0_0_1px_rgba(0,0,0,0.15)]" style={{ left: `${pos}%` }}>
        <span className="absolute left-1/2 top-1/2 grid h-10 w-10 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-paper text-ink shadow-lg">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 5 2.5 9 6 13M12 5l3.5 4L12 13" />
          </svg>
        </span>
      </div>
    </div>
  )
}
