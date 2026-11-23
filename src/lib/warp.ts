import { rng } from './rand'

// Stars seen at speed: they stream outward from a point on the screen as streaks, as if the camera were flying
// forward through the sky. `fx.warp` (0..1) is how fast the flight is; at 0 nothing is drawn at all.
// Used by the intro film (components/IntroGate.tsx). Not used with "reduce motion".

export type WarpFx = {
  warp: number
  /** where the stars fly out of, as a share of the window (0..1, y down); the middle if left out */
  cx?: number
  cy?: number
  /**
   * Something nearer than the stars that they must pass behind (a planet): [how much of it is shown (0..1), a circle's centre x, y and
   * radius in px, then an outline as x, y pairs in px]. Leave it out, or empty, for nothing.
   */
  mask?: number[]
}

type Star = { x: number; y: number; z: number; warm: boolean; weight: number }

const COUNT = 190

/** Starts drawing onto `canvas`. Returns a function that stops it. */
export function startWarp(canvas: HTMLCanvasElement, fx: WarpFx): () => void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return () => undefined

  const rand = rng(8128)
  const css = getComputedStyle(document.documentElement)
  const dark = document.documentElement.dataset.theme !== 'light'
  const colour = {
    star: css.getPropertyValue('--star').trim() || '#ffffff',
    warm: css.getPropertyValue('--star-warm').trim() || '#ffe3a8',
  }

  const spawn = (star: Star, anywhere: boolean) => {
    // not too close to the very middle, where the hand is
    const angle = rand() * Math.PI * 2
    const radius = 0.1 + Math.sqrt(rand()) * 0.9
    star.x = Math.cos(angle) * radius
    star.y = Math.sin(angle) * radius
    star.z = anywhere ? 0.06 + rand() * 0.94 : 1
    star.warm = rand() < 0.3
    star.weight = 0.5 + rand() * 0.5
  }
  const stars: Star[] = Array.from({ length: COUNT }, () => {
    const s: Star = { x: 0, y: 0, z: 1, warm: false, weight: 1 }
    spawn(s, true)
    return s
  })

  let W = 0
  let H = 0
  let dpr = 1
  const resize = () => {
    dpr = Math.min(window.devicePixelRatio || 1, 2)
    W = window.innerWidth
    H = window.innerHeight
    canvas.width = Math.round(W * dpr)
    canvas.height = Math.round(H * dpr)
  }
  resize()
  window.addEventListener('resize', resize)

  let raf = 0
  let last = performance.now()
  const frame = (now: number) => {
    raf = requestAnimationFrame(frame)
    const dt = Math.min(0.05, (now - last) / 1000)
    last = now
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W, H)
    const warp = Math.min(1, Math.max(0, fx.warp))
    if (warp < 0.01) return

    const speed = 0.12 * warp + 2.4 * warp * warp // how much of the way to the viewer a star covers each second
    const trail = 0.014 + speed * 0.075 // the streak behind it, in the same units
    const scale = Math.max(W, H) * 0.17
    const cx = W * (fx.cx ?? 0.5)
    const cy = H * (fx.cy ?? 0.5)
    const strength = Math.min(1, warp * 1.7) * (dark ? 1 : 0.8)

    ctx.lineCap = 'round'
    for (const s of stars) {
      s.z -= speed * dt * (0.7 + s.weight * 0.6)
      if (s.z <= 0.05) {
        spawn(s, false)
        continue
      }
      const x1 = cx + (s.x / s.z) * scale
      const y1 = cy + (s.y / s.z) * scale
      if (x1 < -80 || x1 > W + 80 || y1 < -80 || y1 > H + 80) {
        spawn(s, false)
        continue
      }
      const zTail = Math.min(1, s.z + trail)
      const x0 = cx + (s.x / zTail) * scale
      const y0 = cy + (s.y / zTail) * scale
      const near = 1 - s.z
      ctx.globalAlpha = Math.min(1, near * 1.5 + 0.12) * strength * (0.55 + s.weight * 0.45)
      ctx.strokeStyle = s.warm ? colour.warm : colour.star
      ctx.lineWidth = (0.5 + near * 1.9) * (0.7 + s.weight * 0.5)
      ctx.beginPath()
      ctx.moveTo(x0, y0)
      ctx.lineTo(x1, y1)
      ctx.stroke()
    }
    ctx.globalAlpha = 1

    // The stars are far behind a planet: wipe the streaks off the part of the screen it covers
    const m = fx.mask
    if (m && m.length >= 4 && m[0] > 0.01) {
      ctx.save()
      ctx.globalCompositeOperation = 'destination-out'
      ctx.globalAlpha = Math.min(1, m[0] * 1.4)
      ctx.fillStyle = '#000'
      ctx.beginPath()
      ctx.arc(m[1], m[2], m[3], 0, Math.PI * 2)
      ctx.fill()
      if (m.length >= 10) {
        ctx.beginPath()
        ctx.moveTo(m[4], m[5])
        for (let i = 6; i + 1 < m.length; i += 2) ctx.lineTo(m[i], m[i + 1])
        ctx.closePath()
        ctx.fill()
      }
      ctx.restore()
    }
  }
  raf = requestAnimationFrame(frame)

  return () => {
    cancelAnimationFrame(raf)
    window.removeEventListener('resize', resize)
  }
}
