import { useEffect, useRef } from 'react'

// A few small stars that fall away behind the mouse, and a little burst when the mouse lands on something that can be
// pressed. On a touch screen a tap leaves a tiny burst instead. It is only decoration: it never takes a click, it
// stops itself when nothing is moving, and it is off entirely with "reduce motion".

type Spark = { x: number; y: number; vx: number; vy: number; age: number; life: number; size: number; spin: number; colour: number; star: boolean }

const MAX = 70

export default function SparkleTrail() {
  const canvas = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    let W = 0
    let H = 0
    let dpr = 1
    let colours = ['#ffffff', '#ffd27a', '#9f8cff']
    const sparks: Spark[] = []
    let raf = 0
    let last = 0
    let lastX = 0
    let lastY = 0
    let travelled = 0
    let seen = false
    let lastHot: Element | null = null

    const readColours = () => {
      const css = getComputedStyle(document.documentElement)
      const c = (n: string, d: string) => css.getPropertyValue(n).trim() || d
      colours = document.documentElement.dataset.theme === 'light' ? [c('--star-warm', '#f2a63c'), c('--accent2', '#ffd166'), c('--accent', '#ffb287')] : [c('--star', '#ffffff'), c('--accent2', '#ffd27a'), c('--accent', '#9f8cff')]
    }
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      W = window.innerWidth
      H = window.innerHeight
      el.width = Math.round(W * dpr)
      el.height = Math.round(H * dpr)
    }

    const add = (x: number, y: number, burst: boolean) => {
      if (sparks.length >= MAX) sparks.shift()
      const a = Math.random() * Math.PI * 2
      const speed = burst ? 30 + Math.random() * 70 : 6 + Math.random() * 22
      sparks.push({
        x: x + (Math.random() - 0.5) * 8,
        y: y + (Math.random() - 0.5) * 8,
        vx: Math.cos(a) * speed,
        vy: Math.sin(a) * speed + (burst ? 0 : 14),
        age: 0,
        life: burst ? 0.55 + Math.random() * 0.4 : 0.7 + Math.random() * 0.55,
        size: burst ? 3 + Math.random() * 4 : 2 + Math.random() * 3.6,
        spin: (Math.random() - 0.5) * 3,
        colour: Math.floor(Math.random() * colours.length),
        star: Math.random() < 0.7,
      })
      if (!raf) {
        last = performance.now()
        raf = requestAnimationFrame(frame)
      }
    }

    const burst = (x: number, y: number, n: number) => {
      for (let i = 0; i < n; i++) add(x, y, true)
    }

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, W, H)
      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i]
        s.age += dt
        const u = s.age / s.life
        if (u >= 1) {
          sparks.splice(i, 1)
          continue
        }
        s.x += s.vx * dt
        s.y += s.vy * dt
        s.vx *= 1 - 1.6 * dt
        s.vy *= 1 - 1.6 * dt
        const grow = Math.sin(Math.PI * Math.min(1, u * 1.1))
        const r = s.size * (0.35 + grow * 0.65)
        ctx.globalAlpha = Math.max(0, (1 - u) ** 0.7) * 0.95
        ctx.fillStyle = colours[s.colour]
        if (s.star) {
          ctx.save()
          ctx.translate(s.x, s.y)
          ctx.rotate(s.spin * s.age)
          const k = r * 0.22
          ctx.beginPath()
          ctx.moveTo(0, -r)
          ctx.quadraticCurveTo(k, -k, r, 0)
          ctx.quadraticCurveTo(k, k, 0, r)
          ctx.quadraticCurveTo(-k, k, -r, 0)
          ctx.quadraticCurveTo(-k, -k, 0, -r)
          ctx.fill()
          ctx.restore()
        } else {
          ctx.beginPath()
          ctx.arc(s.x, s.y, r * 0.5, 0, Math.PI * 2)
          ctx.fill()
        }
      }
      ctx.globalAlpha = 1
      // stop drawing when nothing is left
      raf = sparks.length ? requestAnimationFrame(frame) : 0
      if (!sparks.length) ctx.clearRect(0, 0, W, H)
    }

    const onMove = (e: PointerEvent) => {
      if (e.pointerType === 'touch') return
      if (!seen) {
        seen = true
        lastX = e.clientX
        lastY = e.clientY
      }
      travelled += Math.hypot(e.clientX - lastX, e.clientY - lastY)
      lastX = e.clientX
      lastY = e.clientY
      // one spark for every ~22 px of travel, so a slow hand leaves a thin trail and a fast one a longer one
      let n = 0
      while (travelled > 22 && n < 3) {
        travelled -= 22
        n++
        add(e.clientX, e.clientY, false)
      }
      if (travelled > 120) travelled = 0
    }

    // landing on a button, link or card gives a small burst
    const onOver = (e: PointerEvent) => {
      if (e.pointerType === 'touch') return
      const target = e.target instanceof Element ? e.target.closest('a, button, summary, label, [role="button"]') : null
      if (target && target !== lastHot) burst(e.clientX, e.clientY, 5)
      lastHot = target
    }
    const onDown = (e: PointerEvent) => {
      if (e.pointerType === 'touch') burst(e.clientX, e.clientY, 7)
    }
    const onHide = () => {
      sparks.length = 0
    }

    readColours()
    resize()
    const theme = new MutationObserver(readColours)
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    window.addEventListener('resize', resize)
    window.addEventListener('pointermove', onMove, { passive: true })
    window.addEventListener('pointerover', onOver, { passive: true })
    window.addEventListener('pointerdown', onDown, { passive: true })
    document.addEventListener('visibilitychange', onHide)
    return () => {
      cancelAnimationFrame(raf)
      theme.disconnect()
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerover', onOver)
      window.removeEventListener('pointerdown', onDown)
      document.removeEventListener('visibilitychange', onHide)
    }
  }, [])

  return <canvas ref={canvas} className="sparkle-layer" aria-hidden="true" />
}
