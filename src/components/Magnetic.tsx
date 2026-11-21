import { useEffect, useRef, type ReactNode } from 'react'
import gsap from 'gsap'

/** Wraps a button or link so it leans towards the pointer when it gets close. Mouse devices only. */
export default function Magnetic({ children, strength = 0.35, reach = 70 }: { children: ReactNode; strength?: number; reach?: number }) {
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const xTo = gsap.quickTo(el, 'x', { duration: 0.7, ease: 'elastic.out(1, 0.45)' })
    const yTo = gsap.quickTo(el, 'y', { duration: 0.7, ease: 'elastic.out(1, 0.45)' })
    let active = false

    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      const near =
        e.clientX > r.left - reach && e.clientX < r.right + reach && e.clientY > r.top - reach && e.clientY < r.bottom + reach
      if (near) {
        active = true
        xTo((e.clientX - cx) * strength)
        yTo((e.clientY - cy) * strength)
      } else if (active) {
        active = false
        xTo(0)
        yTo(0)
      }
    }
    window.addEventListener('pointermove', move, { passive: true })
    return () => window.removeEventListener('pointermove', move)
  }, [strength, reach])

  return (
    <span ref={ref} className="inline-block">
      {children}
    </span>
  )
}
