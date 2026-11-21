import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { BRAND } from '../brand'
import Cosmos from './Cosmos'
import { ambient } from '../lib/ambient'
import { HAND_STROKES, toSvgPath } from '../lib/handGeometry'
import { startPreload, useLoadProgress } from '../lib/loading'
import { startWarp, type WarpFx } from '../lib/warp'
import { FILM, filmAt, smooth } from '../landing/scene/film'
import { world } from '../landing/scene/state'

// The gate shows a hand drawing itself while real loading happens behind it (fonts, the 3D scene, and a wake-up ping
// to the backend). It never makes anyone wait longer than the loading takes, but it holds for a moment so the drawing
// can finish.
//
// When loading reaches 100% the opening film plays, and it flows straight into the landing page. It is one camera move
// through the real 3D scene (landing/scene/film.ts, CameraRig.tsx, FilmSet.tsx):
//   1. the percentage steps aside and the hand lights up
//   2. the gate's sky and drawing melt away. Under them the 3D scene has been waiting with the very same hand, in the same
//      place and as big as the drawing (and drawn in step with the loading bar), so nobody sees one swapped for the other
//   3. the camera sets out: a great wheel of the zodiac is drawn around the hand, the camera flies through it, a planet
//      rises, the galaxy turns, the stars streak past, and the camera slows into the hero view
//   4. the page's header and headline come in while it settles
// This component owns the film's clock (world.film.clock): it can be sped up for a skip without anything else noticing.
//
// "Skip" (the small button at the bottom, or Esc) speeds everything up: while loading it drops the short hold that lets the
// drawing finish; during the film it plays the rest about four times as fast. Nothing is cut: it still ends on the hero view.
// With "reduce motion" there is no film, only a soft fade.
//
// The page is entered by itself, and the music starts by itself (lib/ambient.ts): a click on Skip counts as the first click.

const MIN_SECONDS = 2.6
/** how fast the film plays once Skip has been pressed */
const SKIP_RATE = 4
/** how strong the streaks of stars get at the fastest point of the flight (0..1) */
const WARP_PEAK = 0.78

// each palm line knows its own position (0..4) so the lines can be drawn one after another
let lines = 0
const PATHS = HAND_STROKES.map((s) => ({
  id: s.id,
  kind: s.kind,
  lineIndex: s.kind === 'line' ? lines++ : -1,
  d: toSvgPath(s, { size: 200, perSegment: 6 }),
}))
const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

type Props = {
  /** the gate starts to lift: the landing page is let in (`fast` when the visitor skipped ahead) */
  onReveal: (opts: { fast: boolean }) => void
  /** the gate is gone */
  onDone: () => void
}

export default function IntroGate({ onReveal, onDone }: Props) {
  const root = useRef<HTMLDivElement>(null)
  const cover = useRef<HTMLDivElement>(null)
  const loader = useRef<HTMLDivElement>(null)
  const halo = useRef<HTMLDivElement>(null)
  const hand = useRef<HTMLDivElement>(null)
  const hud = useRef<HTMLDivElement>(null)
  const skipButton = useRef<HTMLButtonElement>(null)
  const warp = useRef<HTMLCanvasElement>(null)
  const skipped = useRef(false)
  const calls = useRef({ onReveal, onDone })
  useEffect(() => {
    calls.current = { onReveal, onDone }
  })
  const real = useLoadProgress()
  const realRef = useRef(real)
  useEffect(() => {
    realRef.current = real
  }, [real])
  const [p, setP] = useState(0)
  const [ready, setReady] = useState(false)
  // the gate's own sky is only needed until the film has melted it away
  const [showSky, setShowSky] = useState(true)

  useEffect(() => {
    startPreload()
  }, [])

  // The 3D hand is put exactly where the drawing is and as big as it is: tell the scene how tall the drawing is on this screen
  // (the hand takes up 90% of the box it is drawn in).
  useEffect(() => {
    const measure = () => {
      const box = hand.current
      if (box) world.film.handPx = box.getBoundingClientRect().height * 0.9
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])

  // Skip: the button, or Esc
  const skip = () => {
    skipped.current = true
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') skipped.current = true
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // The loading bar and then the film, both driven from one ticker.
  useGSAP(
    () => {
      const started = performance.now()
      const state = { v: 0, clock: 0, rate: 1, fade: 0 }
      let last = started
      let phase: 'loading' | 'film' | 'done' = 'loading'
      let shown = -1
      const fired = { ignite: false, whoosh: false, reveal: false, arrive: false, sky: false }
      const still = reduced()
      const fx: WarpFx = { warp: 0, mask: world.film.mask }
      let stopWarp = () => undefined as void
      const accent = getComputedStyle(root.current ?? document.documentElement).getPropertyValue('--accent').trim() || '#9F8CFF'

      /** Everything on the page that depends on the film's clock. */
      const paint = (c: number) => {
        const lift = smooth(c / 0.5)
        if (hud.current) {
          hud.current.style.opacity = String(1 - lift)
          hud.current.style.transform = `translateY(${14 * lift}px)`
        }
        if (halo.current) {
          halo.current.style.opacity = String(smooth(c / 0.8))
          halo.current.style.transform = `scale(${1 + 0.2 * smooth(c / 0.9)})`
        }
        if (hand.current) hand.current.style.filter = `drop-shadow(0px 0px ${16 * smooth(c / 0.7)}px ${accent})`
        // the cover (sky, glow) and the drawing melt away over the 3D scene beneath
        const solid = 1 - smooth((c - FILM.melt) / FILM.meltFor)
        if (cover.current) {
          cover.current.style.opacity = String(solid)
          if (solid <= 0.001) cover.current.style.visibility = 'hidden'
        }
        if (loader.current) {
          loader.current.style.opacity = String(solid)
          if (solid <= 0.001) loader.current.style.visibility = 'hidden'
        }
        if (solid <= 0.001 && !fired.sky) {
          fired.sky = true
          setShowSky(false)
        }
        // the skip button stays until the page is about to open, then the whole gate lets clicks through
        const away = 1 - smooth((c - (FILM.reveal - 0.3)) / 0.5)
        if (skipButton.current) {
          skipButton.current.style.opacity = String(away)
          if (away <= 0.01) skipButton.current.style.visibility = 'hidden'
        }
        if (root.current) root.current.style.pointerEvents = c >= FILM.reveal ? 'none' : ''
        // the stars of the flight (not at full strength: the hand and the zodiac must stay readable while they fly)
        const fr = filmAt(c)
        fx.warp = WARP_PEAK * Math.pow(fr.speed, 1.6)
        fx.cx = world.film.vx
        fx.cy = world.film.vy
      }

      const events = (c: number) => {
        if (!fired.ignite && c >= FILM.ignite) {
          fired.ignite = true
          ambient.chime(987.77, 0.055)
        }
        if (!fired.whoosh && c >= FILM.whoosh) {
          fired.whoosh = true
          ambient.whoosh()
        }
        if (!fired.reveal && c >= FILM.reveal) {
          fired.reveal = true
          calls.current.onReveal({ fast: skipped.current })
        }
        if (!fired.arrive && c >= FILM.arrive) {
          fired.arrive = true
          ambient.arrive()
        }
      }

      const tick = () => {
        const now = performance.now()
        const dt = Math.min((now - last) / 1000, 0.25)
        last = now

        if (phase === 'loading') {
          const elapsed = (now - started) / 1000
          // Skip drops the hold that lets the drawing finish: the bar then simply follows the real loading
          const target = skipped.current ? realRef.current : Math.min(realRef.current, elapsed / MIN_SECONDS)
          // eases towards the target at the same pace at any frame rate (a slow computer is not held at the gate for longer)
          state.v += (target - state.v) * (1 - Math.exp(-(skipped.current ? 12 : 6.3) * dt))
          if (target - state.v < 0.002) state.v = target
          world.film.load = state.v
          const percent = Math.round(state.v * 100)
          if (percent !== shown) {
            shown = percent
            setP(percent)
          }
          if (state.v >= 1) {
            phase = 'film'
            setReady(true)
            if (!still) stopWarp = startWarp(warp.current as HTMLCanvasElement, fx)
          }
          return
        }

        if (phase !== 'film') return
        state.rate += ((skipped.current ? SKIP_RATE : 1) - state.rate) * (1 - Math.exp(-9 * dt))

        if (still) {
          // no flight: the gate just melts away
          state.fade += dt * state.rate
          const f = state.fade
          if (!fired.reveal && f >= 0.25) {
            fired.reveal = true
            calls.current.onReveal({ fast: true })
          }
          const o = 1 - smooth((f - 0.25) / 0.6)
          if (root.current) root.current.style.opacity = String(o)
          if (f >= 0.25 && root.current) root.current.style.pointerEvents = 'none'
          if (skipButton.current) {
            skipButton.current.style.opacity = String(o)
            if (f >= 0.25) skipButton.current.style.visibility = 'hidden'
          }
          if (f >= 0.85) {
            phase = 'done'
            gsap.ticker.remove(tick)
            calls.current.onDone()
          }
          return
        }

        state.clock = Math.min(FILM.end, state.clock + dt * state.rate)
        world.film.clock = state.clock
        paint(state.clock)
        events(state.clock)
        if (state.clock >= FILM.end) {
          phase = 'done'
          gsap.ticker.remove(tick)
          calls.current.onDone()
        }
      }
      gsap.ticker.add(tick)
      return () => {
        gsap.ticker.remove(tick)
        stopWarp()
      }
    },
    { scope: root },
  )

  // how much of each stroke is drawn: outline first, then the palm lines one by one, then the finger creases
  const amount = (kind: string, lineIndex: number) => {
    const q = p / 100
    if (kind === 'outline') return clamp01(q / 0.55)
    if (kind === 'line') return clamp01((q - 0.3 - lineIndex * 0.09) / 0.3)
    return clamp01((q - 0.78) / 0.22)
  }

  return (
    <>
      <div ref={root} role="status" aria-label={`Loading ${BRAND.name}`} data-ui data-gate={ready ? 'film' : 'loading'} className="fixed inset-0 z-[100] overflow-hidden">
        {/* the cover: the gate's own sky, opaque so the page's sky behind it cannot show through, and the glow behind the hand */}
        <div ref={cover} className="absolute inset-0 isolate bg-paper">
          <div className="absolute inset-0">{showSky && <Cosmos />}</div>
          <div aria-hidden="true" className="pointer-events-none absolute inset-0 grid place-items-center">
            <div
              ref={halo}
              className="h-[34rem] w-[34rem] max-w-[120vw] rounded-full opacity-0"
              style={{ background: 'radial-gradient(closest-side, color-mix(in srgb, var(--accent) 42%, transparent), transparent)' }}
            />
          </div>
        </div>

        {/* the hand sits exactly in the middle of the window: the 3D hand is put right under it, as big as this drawing */}
        <div ref={loader} className="absolute left-1/2 top-[calc(50%-6.5rem)] flex -translate-x-1/2 flex-col items-center gap-5">
          <div ref={hand}>
            <svg viewBox="0 0 200 200" className="h-52 w-52" fill="none" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              {PATHS.map((s) => {
                const a = amount(s.kind, s.lineIndex)
                return (
                  <path
                    key={s.id}
                    d={s.d}
                    pathLength={1}
                    strokeDasharray={1}
                    strokeDashoffset={1 - a}
                    opacity={a > 0 ? 1 : 0}
                    strokeWidth={s.kind === 'outline' ? 2.2 : s.kind === 'line' ? 2.4 : 1.1}
                    className={s.kind === 'outline' ? 'stroke-ink' : s.kind === 'line' ? 'stroke-accent-ink' : 'stroke-muted'}
                  />
                )
              })}
            </svg>
          </div>
          <div ref={hud} className="flex flex-col items-center gap-5">
            <h1 className="font-display text-6xl tracking-tight">{BRAND.short}</h1>
            <p className="tabular-nums text-sm text-muted" aria-hidden="true">
              {p}%
            </p>
          </div>
        </div>

      </div>
      {/* the stars of the flight: above the gate, so they carry on over the landing page while it opens */}
      <canvas ref={warp} aria-hidden="true" className="pointer-events-none fixed inset-0 z-[101] h-full w-full" />
      {/* a small, quiet way out: low in the window, and it blends into the loader until it is looked at (above the stars, so they pass behind it) */}
      <button ref={skipButton} type="button" onClick={skip} className="skip-button" aria-label="Skip the intro">
        Skip
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2 2.5 6 6 2 9.5M7 2.5 11 6 7 9.5" />
        </svg>
      </button>
    </>
  )
}
