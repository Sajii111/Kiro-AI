import { useEffect, useRef } from 'react'
import gsap from 'gsap'

export default function Cursor() {
  const dot = useRef<HTMLDivElement>(null)
  const ring = useRef<HTMLDivElement>(null)
  const label = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return
    const d = dot.current!
    const r = ring.current!
    const l = label.current!
    document.documentElement.classList.add('has-cursor')
    gsap.set([d, r, l], { xPercent: -50, yPercent: -50 })

    const dx = gsap.quickTo(d, 'x', { duration: 0.08, ease: 'power3' })
    const dy = gsap.quickTo(d, 'y', { duration: 0.08, ease: 'power3' })
    const rx = gsap.quickTo(r, 'x', { duration: 0.5, ease: 'power3' })
    const ry = gsap.quickTo(r, 'y', { duration: 0.5, ease: 'power3' })
    const lx = gsap.quickTo(l, 'x', { duration: 0.5, ease: 'power3' })
    const ly = gsap.quickTo(l, 'y', { duration: 0.5, ease: 'power3' })

    let shown = false
    const move = (e: MouseEvent) => {
      if (!shown) {
        shown = true
        gsap.set([d, r, l], { x: e.clientX, y: e.clientY })
        gsap.to([d, r], { opacity: 1, duration: 0.3 })
      }
      dx(e.clientX)
      dy(e.clientY)
      rx(e.clientX)
      ry(e.clientY)
      lx(e.clientX)
      ly(e.clientY)
    }
    const over = (e: MouseEvent) => {
      const el = e.target as Element
      if (!el.closest) return
      const typing = !!el.closest('input, textarea, [contenteditable="true"]')
      const labelled = el.closest('[data-cursor-label]')
      const hot = !typing && (!!labelled || !!el.closest('a, button, [data-cursor]'))
      r.classList.toggle('is-hover', hot)
      gsap.to(r, { scale: labelled ? 2.5 : hot ? 1.9 : 1, duration: 0.35, ease: 'power3.out' })
      gsap.to(d, { scale: hot ? 0 : 1, duration: 0.2 })
      if (labelled) l.textContent = labelled.getAttribute('data-cursor-label')
      gsap.to(l, { opacity: labelled ? 1 : 0, duration: 0.2 })
      // Over a text field the normal caret takes over, so fade the custom cursor out.
      if (shown) gsap.to([d, r], { opacity: typing ? 0 : 1, duration: 0.2, overwrite: 'auto' })
    }

    window.addEventListener('mousemove', move)
    window.addEventListener('mouseover', over)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseover', over)
      document.documentElement.classList.remove('has-cursor')
    }
  }, [])

  return (
    <>
      <div ref={ring} className="cursor-ring" aria-hidden="true" />
      <div ref={dot} className="cursor-dot" aria-hidden="true" />
      <div ref={label} className="cursor-label" aria-hidden="true" />
    </>
  )
}
