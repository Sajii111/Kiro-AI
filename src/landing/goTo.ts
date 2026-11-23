import type { MouseEvent } from 'react'
import { lenis } from '../lib/smoothScroll'
import { world } from './scene/state'

/** Smooth-scroll to a section. The pinned "how it works" section is reached through its recorded start. */
export function goTo(id: string) {
  return (e: MouseEvent) => {
    e.preventDefault()
    const el = document.getElementById(id)
    if (!el) return
    const y =
      id === 'how' && world.marks.howStart !== undefined ? world.marks.howStart : el.getBoundingClientRect().top + window.scrollY - 12
    if (lenis) lenis.scrollTo(y, { duration: 1.8 })
    else window.scrollTo({ top: y, behavior: 'smooth' })
  }
}
