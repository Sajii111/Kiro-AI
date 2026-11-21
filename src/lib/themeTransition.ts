// The change between the dark and light theme is animated: the new theme grows as a circle out of the button that
// was pressed, like the sun coming up (or the lights going down) from that spot.
//
// It uses the browser's View Transitions, which freeze a picture of the old page and let the new one be revealed on
// top of it. Browsers without them get a short colour fade instead, and with "reduce motion" switched on in the
// operating system the theme just changes.

export type Origin = { x: number; y: number }

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** The middle of the button (or card) that was used, in page coordinates. */
export function originOf(el: Element): Origin {
  const target = el.closest('button, label') ?? el
  const r = target.getBoundingClientRect()
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
}

/**
 * Runs `change` (which must switch the theme right away, in one go) inside the animation.
 * `change` is called exactly once, whichever way the animation goes.
 */
export function runThemeChange(change: () => void, origin?: Origin): void {
  if (reduced()) {
    change()
    return
  }

  if (typeof document.startViewTransition === 'function') {
    const x = origin?.x ?? window.innerWidth / 2
    const y = origin?.y ?? 0
    // far enough to cover the whole window from wherever the circle starts
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y))
    // nothing may fade its own colours while the circle is revealing the new theme
    const root = document.documentElement
    root.classList.add('theme-switching')
    const transition = document.startViewTransition(change)
    const done = () => root.classList.remove('theme-switching')
    transition.finished.then(done, done)
    transition.ready
      .then(() => {
        document.documentElement.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
          { duration: 850, easing: 'cubic-bezier(0.65, 0, 0.35, 1)', pseudoElement: '::view-transition-new(root)' },
        )
      })
      // a second press during the animation skips the first one: nothing to do
      .catch(() => {})
    return
  }

  const root = document.documentElement
  root.classList.add('theme-fade')
  change()
  window.setTimeout(() => root.classList.remove('theme-fade'), 750)
}
