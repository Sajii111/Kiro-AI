import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { filmAt, filmPath, SWING, type FilmPath } from './film'
import { KEYS } from './journey'
import { world } from './state'

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
const smooth = (u: number) => u * u * (3 - 2 * u)
const UP = new THREE.Vector3(0, 1, 0)

type Resolved = {
  ys: number[]
  shifts: number[]
  lifts: number[]
  pos: THREE.CatmullRomCurve3
  focus: THREE.CatmullRomCurve3
}

/**
 * Moves the camera along the journey as the page scrolls.
 * Each camera stop (journey.ts) is tied to a measured scroll position; between stops the camera glides.
 *
 * While the opening film plays (world.film.on) the camera instead follows the film's path (film.ts): it starts far away, with
 * the hand as small as the loader's drawing, and flies to the ordinary hero view, which is where the scroll-driven journey
 * begins. The rig also turns the film's clock into the values the rest of the scene reads (world.film.sky, .tilt, ...).
 */
export default function CameraRig() {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const resolved = useRef<Resolved | null>(null)
  const seenVersion = useRef(-1)
  const smoothY = useRef(0)
  const shift = useRef({ x: 0, y: 0 })
  const path = useRef<{ key: string; value: FilmPath } | null>(null)
  const tmp = useMemo(
    () => ({
      pos: new THREE.Vector3(),
      focus: new THREE.Vector3(),
      fwd: new THREE.Vector3(),
      right: new THREE.Vector3(),
      up: new THREE.Vector3(),
      look: new THREE.Vector3(),
      hand: new THREE.Vector3(),
    }),
    [],
  )

  const resolve = () => {
    const keys = KEYS.filter((k) => world.marks[k.at] !== undefined)
    if (keys.length < 2) {
      resolved.current = null
      return
    }
    const ys: number[] = []
    keys.forEach((k, i) => {
      const y = world.marks[k.at]
      ys.push(i === 0 ? y : Math.max(y, ys[i - 1] + 1))
    })
    resolved.current = {
      ys,
      shifts: keys.map((k) => k.shift),
      lifts: keys.map((k) => k.lift ?? 0.5),
      pos: new THREE.CatmullRomCurve3(keys.map((k) => new THREE.Vector3(...k.pos)), false, 'centripetal'),
      focus: new THREE.CatmullRomCurve3(keys.map((k) => new THREE.Vector3(...k.focus)), false, 'centripetal'),
    }
  }

  useFrame((state, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1)
    const t = state.clock.elapsedTime
    const film = world.film

    // the opening film: its clock (written by the intro gate) becomes the values the rest of the scene reads
    const fr = film.on ? filmAt(film.clock) : null
    film.speed = fr ? fr.speed : 0
    film.sky = fr ? fr.sky : 1
    film.tilt = fr ? fr.tilt : 1
    film.live = fr ? fr.live : 1
    film.text = fr ? fr.text : 1
    film.props = fr ? fr.props : 0
    film.boost.value = fr ? fr.boost : 1

    if (seenVersion.current !== world.version) {
      seenVersion.current = world.version
      resolve()
    }
    const r = resolved.current
    if (!r) return

    // ease the scroll position so the camera glides
    smoothY.current = world.reduced
      ? world.scrollY
      : smoothY.current + (world.scrollY - smoothY.current) * (1 - Math.exp(-6 * dt))
    const y = smoothY.current

    // the closing sunrise has centred text and no text side, so the quieting of lines eases off there
    const m = world.marks
    if (m.ch3c !== undefined && m.ctac !== undefined) {
      world.safe = 1 - clamp01((y - m.ch3c - (m.ctac - m.ch3c) * 0.25) / ((m.ctac - m.ch3c) * 0.6))
    }

    let k = 0
    while (k < r.ys.length - 2 && y >= r.ys[k + 1]) k++
    const span = r.ys[k + 1] - r.ys[k]
    const u = span > 0 ? clamp01((y - r.ys[k]) / span) : 0
    const ue = u + (smooth(u) - u) * 0.55
    const T = (k + ue) / (r.ys.length - 1)

    r.pos.getPoint(T, tmp.pos)
    r.focus.getPoint(T, tmp.focus)
    const sideShift = r.shifts[k] + (r.shifts[k + 1] - r.shifts[k]) * ue
    const lift = r.lifts[k] + (r.lifts[k + 1] - r.lifts[k]) * ue

    // phones are narrow, so the camera backs away a little to keep whole objects in view
    if (world.narrow) tmp.pos.sub(tmp.focus).multiplyScalar(1.3).add(tmp.focus)

    tmp.fwd.subVectors(tmp.focus, tmp.pos)
    const dist = tmp.fwd.length()
    tmp.fwd.normalize()
    tmp.right.crossVectors(tmp.fwd, UP).normalize()
    tmp.up.crossVectors(tmp.right, tmp.fwd).normalize()

    // a slow idle drift plus a touch of pointer parallax (held still while the film's camera is on its way)
    if (!world.reduced) {
      const k2 = 1 - Math.exp(-2.5 * dt)
      shift.current.x += (world.pointer.x - shift.current.x) * k2
      shift.current.y += (world.pointer.y - shift.current.y) * k2
      tmp.pos
        .addScaledVector(tmp.right, (shift.current.x * 0.38 + Math.sin(t * 0.31) * 0.07) * film.live)
        .addScaledVector(tmp.up, (shift.current.y * 0.24 + Math.cos(t * 0.27) * 0.05) * film.live)
    }

    // the focus point is slid sideways so the object sits beside the text
    tmp.look.copy(tmp.focus)
    if (world.narrow) {
      const halfH = dist * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
      tmp.look.addScaledVector(tmp.up, -halfH * lift)
    } else {
      tmp.look.addScaledVector(tmp.right, -sideShift)
    }

    // the opening film: until now this was the hero view; the film's camera starts far back, with the hand in the middle of
    // the screen, and arrives here. It flies in a straight line, bows to the right on the way (so it passes through the
    // middle of the zodiac wheel and the things beside it slide by), banks a little, and turns its gaze from the hand to the
    // hero composition over the second half.
    let roll = 0
    if (fr) {
      const key = `${state.size.height}|${camera.fov}|${world.narrow}|${film.handPx}`
      if (!path.current || path.current.key !== key) {
        path.current = { key, value: filmPath(state.size.height, camera.fov, world.narrow, film.handPx) }
      }
      const { p0, h0 } = path.current.value
      const d = fr.d
      const bow = Math.sin(Math.PI * d)
      const amp = world.narrow ? 0.6 : 1
      tmp.pos.set(
        p0[0] + (tmp.pos.x - p0[0]) * d + SWING.x * amp * bow,
        p0[1] + (tmp.pos.y - p0[1]) * d + SWING.y * amp * Math.pow(bow, 1.3),
        p0[2] + (tmp.pos.z - p0[2]) * d,
      )
      const gaze = smooth(clamp01((d - 0.25) / 0.75))
      tmp.look.set(h0[0] + (tmp.look.x - h0[0]) * gaze, h0[1] + (tmp.look.y - h0[1]) * gaze, h0[2] + (tmp.look.z - h0[2]) * gaze)
      roll = world.reduced ? 0 : SWING.roll * bow * (world.narrow ? 0.7 : 1)
    }

    camera.position.copy(tmp.pos)
    camera.up.set(Math.sin(roll), Math.cos(roll), 0)
    camera.lookAt(tmp.look)

    // where the hand is on the screen: the stars of the flight fly out of there
    if (fr && path.current) {
      camera.updateMatrixWorld()
      const h0 = path.current.value.h0
      tmp.hand.set(h0[0], h0[1], h0[2]).project(camera)
      film.vx = tmp.hand.x * 0.5 + 0.5
      film.vy = 0.5 - tmp.hand.y * 0.5
    }
  })

  return null
}
