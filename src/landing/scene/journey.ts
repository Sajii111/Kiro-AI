// The layout of the 3D world and the camera's path through it.
// Numbers only (no three.js) so it is easy to tweak: x right, y up, z towards the viewer.
// The camera starts in front of the hero hand, dives through the palm, drifts through the stars past
// two hands, circles the scanning hand, passes floating chat bubbles and ends at the planet (or the sun).

export type V3 = [number, number, number]

export const HERO_HAND = { pos: [2.25, 0.4, 0] as V3, scale: 1.6, narrowScale: 1.35, rot: [0.02, -0.32, 0.05] as V3 }
export const TWO_HANDS = { y: 0.1, z: -14.5, xs: [1.05, 3.05] as [number, number], scale: 0.9 }
export const SCAN = { pos: [1.6, 0, -25] as V3 }
export const BUBBLES = { pos: [1.7, 0, -38] as V3 }
export const SUN = { pos: [0, 2.2, -64] as V3, size: 13 }
/** The ringed planet that takes the Sun's place in the Night Sky: its size, ring (inner, outer radius) and moon. */
export const PLANET = { pos: [0, 2.1, -64] as V3, radius: 1.6, ring: [2.25, 3.6] as [number, number], moonOrbit: 4.8, moonRadius: 0.25 }

/**
 * A camera stop. `at` names a scroll position measured from the page layout (see Landing.tsx):
 *   top, near, dive  - the first screen, leaning towards the palm, passing through it
 *   ch1c             - chapter 1 centred on screen
 *   howStart/Mid/End - the pinned "how it works" section
 *   ch3c, ctac       - chapter 3 and the closing call to action, centred
 * `focus` is what the camera looks at. On desktop `shift` slides that point sideways on screen so the
 * object sits next to the text; on phones `lift` (in half-screen heights, default 0.5) raises the object
 * into the top part of the screen so the text can sit underneath it.
 */
export type Key = { at: string; pos: V3; focus: V3; shift: number; lift?: number }

const orbit = (c: V3, deg: number, radius: number, height: number): V3 => {
  const a = (deg * Math.PI) / 180
  return [c[0] + radius * Math.sin(a), c[1] + height, c[2] + radius * Math.cos(a)]
}

export const KEYS: Key[] = [
  { at: 'top', pos: [0.0, 0.2, 8.6], focus: HERO_HAND.pos, shift: 2.2 },
  { at: 'near', pos: [1.2, 0.35, 5.0], focus: HERO_HAND.pos, shift: 1.4 },
  { at: 'dive', pos: [2.2, 0.45, 0.6], focus: [2.0, 0.4, -6], shift: 0, lift: 0 },
  { at: 'ch1c', pos: [0.1, 0.3, -8.6], focus: [2.05, 0.1, -14.5], shift: 1.7 },
  { at: 'howStart', pos: orbit(SCAN.pos, -48, 5.8, 0.7), focus: SCAN.pos, shift: 2.1 },
  { at: 'howMid', pos: orbit(SCAN.pos, 0, 5.8, 1.0), focus: SCAN.pos, shift: 2.1 },
  { at: 'howEnd', pos: orbit(SCAN.pos, 46, 5.8, 0.6), focus: SCAN.pos, shift: 2.1 },
  { at: 'ch3c', pos: [0.0, 0.3, -31.6], focus: BUBBLES.pos, shift: 2.1 },
  { at: 'ctac', pos: [0.0, 0.9, -46], focus: [0, -1.45, -64], shift: 0, lift: 0.3 },
]
