import { HAND_BOUNDS, HAND_CENTRE } from '../../lib/handGeometry'
import { HERO_HAND, KEYS, type V3 } from './journey'

// The opening film, as numbers (no three.js, so the intro gate can use it without loading the 3D chunk).
//
// It is one camera move through the real scene. It starts far from the hero hand, at the distance where the hand is exactly
// as big on the screen as the loader's drawing, and in the middle of the screen (see filmPath): the drawing and the 3D hand
// are then the same picture, and one melts into the other without anyone seeing a swap. From there the camera sets out, flies
// through a great wheel of the zodiac, past a ringed planet, with the galaxy turning behind the hand and the stars streaking
// past, and slows into the ordinary hero view (see CameraRig).
//
// The intro gate owns the clock (world.film.clock, in seconds from the moment loading reaches 100%). Everything else is a
// function of it, so the film plays the same on any computer and can be sped up (skipped) without breaking anything.

/** seconds from the moment loading reaches 100% */
export const FILM = {
  /** the loader's drawing lights up: a first soft note */
  ignite: 0.25,
  /** the cover (the loader's sky) and the drawing melt away over the 3D scene, which is already in place beneath them */
  melt: 0.3,
  meltFor: 0.85,
  /** the camera sets out */
  go: 0.5,
  /** the rush of air, timed to peak when the camera is fastest */
  whoosh: 2.2,
  /** the page's header and headline are let in (the camera is almost there) */
  reveal: 5.3,
  /** three bright notes as the page opens */
  arrive: 5.4,
  /** the last frame: the ordinary hero view */
  end: 6.9,
}

/**
 * How far the camera bows to the right and up while it flies (world units), and how much it banks (radians). The hero view
 * is left of where the flight starts, so the bow to the right keeps the camera close to the line towards the hand while it
 * flies through the zodiac wheel, and then lets it slide left into the hero view.
 */
export const SWING = { x: 2.0, y: 0.8, roll: 0.1 }

/** how much wider than their ordinary width the hand's lines are in the opening shot (keeps them looking as solid as the drawing) */
export const BOOST0 = 4.0

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
export const smooth = (v: number) => {
  const t = clamp01(v)
  return t * t * (3 - 2 * t)
}
const smoother = (v: number) => {
  const t = clamp01(v)
  return t * t * t * (t * (t * 6 - 15) + 10)
}

export type FilmFrame = {
  /** how far along the camera's path (0 = the opening shot, 1 = the hero view) */
  d: number
  speed: number
  sky: number
  tilt: number
  live: number
  text: number
  props: number
  boost: number
}

/** Everything that depends on the clock alone. At `FILM.end` it equals the ordinary, resting scene. */
export function filmAt(t: number): FilmFrame {
  const s = clamp01((t - FILM.go) / (FILM.end - FILM.go))
  const d = smoother(s)
  // the slope of the eased path, scaled so the fastest moment is 1
  const speed = clamp01((30 * s * s * (1 - s) * (1 - s)) / 1.875)
  return {
    d,
    speed,
    sky: smooth((t - 0.7) / 2.2),
    tilt: smooth((d - 0.04) / 0.8),
    live: smooth((d - 0.78) / 0.22),
    text: smooth((t - (FILM.reveal - 0.9)) / 1.9),
    props: 1 - smooth((t - 5.0) / 1.5),
    boost: 1 + (BOOST0 - 1) * (1 - d),
  }
}

export type FilmPath = {
  /** where the camera starts, and the point it looks at there (the middle of the hand) */
  p0: V3
  h0: V3
  /** where the camera comes to rest: the ordinary hero view */
  rest: V3
  /** how far the camera starts from the hand */
  d0: number
}

/**
 * The opening shot. The loader's drawing is `handPx` tall and sits in the middle of the window; the camera is put at the
 * distance where the 3D hand (flat to the viewer, centred) comes out exactly that size.
 */
export function filmPath(viewH: number, fov: number, narrow: boolean, handPx: number): FilmPath {
  const scale = narrow ? HERO_HAND.narrowScale : HERO_HAND.scale
  const b = HAND_BOUNDS
  const h0: V3 = [
    HERO_HAND.pos[0] + ((b.minX + b.maxX) / 2 - HAND_CENTRE.x) * scale,
    HERO_HAND.pos[1] + ((b.minY + b.maxY) / 2 - HAND_CENTRE.y) * scale,
    HERO_HAND.pos[2],
  ]
  const tall = (b.maxY - b.minY) * scale
  const d0 = (tall * viewH) / (handPx * 2 * Math.tan((fov * Math.PI) / 360))
  const key = KEYS[0]
  // phones back away from what they look at (see CameraRig)
  const rest: V3 = narrow
    ? [
        key.focus[0] + (key.pos[0] - key.focus[0]) * 1.3,
        key.focus[1] + (key.pos[1] - key.focus[1]) * 1.3,
        key.focus[2] + (key.pos[2] - key.focus[2]) * 1.3,
      ]
    : key.pos
  return { p0: [h0[0], h0[1], h0[2] + d0], h0, rest, d0 }
}

/** the point on the straight line from the start to the rest position at `fraction` of the way */
export function alongPath(path: FilmPath, fraction: number): V3 {
  const { p0, rest } = path
  return [p0[0] + (rest[0] - p0[0]) * fraction, p0[1] + (rest[1] - p0[1]) * fraction, p0[2] + (rest[2] - p0[2]) * fraction]
}
