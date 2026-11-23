import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { rng } from '../lib/rand'

// The sky behind every page: a gradient (in CSS, see .cosmos in index.css) with stars drawn on a canvas on top.
//
//  - stars twinkle, and sit at different depths: they drift a little as the page scrolls and shift with the mouse,
//    so the sky has some distance to it
//  - stars near the mouse brighten, grow and lean away a little, like dust being disturbed
//  - now and then a shooting star crosses the top of the screen (a little more often on the landing page)
//
// With "reduce motion" switched on, the stars are drawn once and hold still.

type Star = { x: number; y: number; z: number; r: number; a: number; speed: number; phase: number; warm: boolean; sparkle: boolean }
type Shot = { x: number; y: number; vx: number; vy: number; age: number; life: number; len: number }

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

function makeStars(count: number): Star[] {
  const rand = rng(20261108)
  return Array.from({ length: count }, () => {
    const z = 0.15 + rand() * 0.85
    return {
      x: rand(),
      y: rand(),
      z,
      r: 0.35 + z * 1.05 + (rand() < 0.1 ? 0.55 : 0),
      a: 0.3 + rand() * 0.7,
      speed: 0.5 + rand() * 1.9,
      phase: rand() * Math.PI * 2,
      warm: rand() < 0.22,
      sparkle: rand() < 0.07,
    }
  })
}

/** A four-point star: tall, thin points and a small body. */
function sparkle(ctx: CanvasRenderingContext2D, x: number, y: number, len: number) {
  const k = len * 0.2
  ctx.beginPath()
  ctx.moveTo(x, y - len)
  ctx.quadraticCurveTo(x + k, y - k, x + len, y)
  ctx.quadraticCurveTo(x + k, y + k, x, y + len)
  ctx.quadraticCurveTo(x - k, y + k, x - len, y)
  ctx.quadraticCurveTo(x - k, y - k, x, y - len)
  ctx.fill()
}

export default function Cosmos() {
  const canvas = useRef<HTMLCanvasElement>(null)
  const landing = useLocation().pathname === '/'
  // read inside the animation loop, so a route change does not restart it
  const calm = useRef(!landing)
  useEffect(() => {
    calm.current = !landing
  }, [landing])

  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return

    const reduced = reducedMotion()
    let W = 0
    let H = 0
    let dpr = 1
    let stars: Star[] = []
    let colour = { star: '#ffffff', warm: '#ffe3a8', dark: true }
    const pointer = { x: -9999, y: -9999, sx: -9999, sy: -9999, until: 0, nx: 0, ny: 0 }
    let shot: Shot | null = null
    let nextShot = performance.now() + 4000 + Math.random() * 5000
    let raf = 0
    let last = performance.now()

    const readColours = () => {
      const css = getComputedStyle(document.documentElement)
      colour = {
        star: css.getPropertyValue('--star').trim() || '#ffffff',
        warm: css.getPropertyValue('--star-warm').trim() || '#ffe3a8',
        dark: document.documentElement.dataset.theme !== 'light',
      }
    }

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      W = window.innerWidth
      H = window.innerHeight
      el.width = Math.round(W * dpr)
      el.height = Math.round(H * dpr)
      const density = colour.dark ? 1 : 0.6
      stars = makeStars(Math.round(Math.min(260, Math.max(70, (W * H) / 8500)) * density))
    }

    const draw = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      const t = now / 1000
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, W, H)

      // the mouse is only "present" for a few seconds after it last moved
      const present = !reduced && now < pointer.until
      if (present) {
        const k = 1 - Math.exp(-8 * dt)
        pointer.sx += (pointer.x - pointer.sx) * k
        pointer.sy += (pointer.y - pointer.sy) * k
      }
      const scroll = window.scrollY
      const base = colour.dark ? 1 : 0.62

      for (const s of stars) {
        const tw = reduced ? 0.8 : 0.55 + 0.45 * Math.sin(t * s.speed + s.phase)
        let x = s.x * W + (reduced ? 0 : pointer.nx * 16 * s.z)
        let y = s.y * H - (reduced ? 0 : scroll * 0.045 * s.z) + (reduced ? 0 : pointer.ny * 10 * s.z)
        y = ((y % H) + H) % H
        let alpha = s.a * tw * base
        let r = s.r

        if (present) {
          const dx = x - pointer.sx
          const dy = y - pointer.sy
          const d = Math.hypot(dx, dy)
          if (d < 150) {
            const f = (1 - d / 150) ** 2
            alpha = Math.min(1, alpha + f * 0.55)
            r *= 1 + f * 0.9
            const push = (f * 9) / Math.max(d, 1)
            x += dx * push
            y += dy * push
          }
        }

        ctx.globalAlpha = Math.max(0, Math.min(1, alpha))
        ctx.fillStyle = s.warm ? colour.warm : colour.star
        if (s.sparkle && r > 0.9) {
          sparkle(ctx, x, y, r * (3.4 + (reduced ? 0 : tw * 2.6)))
        } else {
          ctx.beginPath()
          ctx.arc(x, y, r, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      // a shooting star
      if (!reduced) {
        if (!shot && now > nextShot && !document.hidden) {
          const dir = Math.random() < 0.5 ? 1 : -1
          const speed = 620 + Math.random() * 260
          const angle = (18 + Math.random() * 16) * (Math.PI / 180)
          shot = { x: W * (dir > 0 ? 0.08 + Math.random() * 0.4 : 0.52 + Math.random() * 0.4), y: H * (0.04 + Math.random() * 0.3), vx: Math.cos(angle) * speed * dir, vy: Math.sin(angle) * speed, age: 0, life: 1.1, len: 150 + Math.random() * 90 }
        }
        if (shot) {
          shot.age += dt
          shot.x += shot.vx * dt
          shot.y += shot.vy * dt
          const u = shot.age / shot.life
          if (u >= 1) {
            shot = null
            nextShot = now + (calm.current ? 22000 + Math.random() * 20000 : 9000 + Math.random() * 9000)
          } else {
            const fade = Math.sin(Math.PI * Math.min(1, u * 1.15)) * (colour.dark ? 1 : 0.7)
            const m = Math.hypot(shot.vx, shot.vy)
            const tx = shot.x - (shot.vx / m) * shot.len
            const ty = shot.y - (shot.vy / m) * shot.len
            const g = ctx.createLinearGradient(tx, ty, shot.x, shot.y)
            g.addColorStop(0, 'rgba(255,255,255,0)')
            g.addColorStop(1, colour.dark ? 'rgba(255,255,255,0.95)' : colour.warm)
            ctx.globalAlpha = fade
            ctx.strokeStyle = g
            ctx.lineWidth = 1.5
            ctx.lineCap = 'round'
            ctx.beginPath()
            ctx.moveTo(tx, ty)
            ctx.lineTo(shot.x, shot.y)
            ctx.stroke()
            ctx.fillStyle = colour.dark ? '#ffffff' : colour.warm
            ctx.beginPath()
            ctx.arc(shot.x, shot.y, 1.7, 0, Math.PI * 2)
            ctx.fill()
          }
        }
      }
      ctx.globalAlpha = 1
    }

    const frame = (now: number) => {
      // no need to draw a sky nobody can see
      if (!document.hidden) draw(now)
      raf = requestAnimationFrame(frame)
    }

    const onMove = (e: PointerEvent) => {
      if (e.pointerType === 'touch') return
      if (pointer.until < performance.now()) {
        pointer.sx = e.clientX
        pointer.sy = e.clientY
      }
      pointer.x = e.clientX
      pointer.y = e.clientY
      pointer.until = performance.now() + 2600
      pointer.nx = e.clientX / window.innerWidth - 0.5
      pointer.ny = e.clientY / window.innerHeight - 0.5
    }

    readColours()
    resize()
    const onResize = () => {
      resize()
      if (reduced) draw(performance.now())
    }
    window.addEventListener('resize', onResize)
    // a theme switch changes the star colours (and how many there are)
    const theme = new MutationObserver(() => {
      readColours()
      resize()
      if (reduced) draw(performance.now())
    })
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

    if (reduced) {
      draw(performance.now())
    } else {
      window.addEventListener('pointermove', onMove, { passive: true })
      raf = requestAnimationFrame(frame)
    }
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointermove', onMove)
      theme.disconnect()
    }
  }, [])

  return (
    <div className="cosmos" aria-hidden="true">
      <div className="cosmos-sky" />
      <canvas ref={canvas} />
    </div>
  )
}
