import { useEffect, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { ambient } from '../../lib/ambient'
import { shared } from './materials'
import { palette } from './palette'
import { pick, rayAt } from './pick'
import { world } from './state'

// Shooting stars.
//  - click or tap open sky and a star streaks across it from where you pointed, with a little burst of sparkles and one soft
//    note (when the music is on). It is the one thing here that answers a click on nothing: a wish. A planet, a zodiac sign or
//    a palm line that is tapped keeps the tap for itself, and text, buttons and cards never lose a click to the sky.
//  - the opening film sends a few across the sky on its own
// At most a few are alive at once, and they cost a hundred points in all. With reduced motion there are none.

const MAX = 4
const TRAIL = 24
const BURST = 10
const PER = TRAIL + BURST

/** the opening film's own shooting stars: when (film seconds), where (share of the window, y down) and which way they go */
const FILM_METEORS = [
  { at: 1.3, x: 0.14, y: 0.14, dir: 1 },
  { at: 2.9, x: 0.9, y: 0.22, dir: -1 },
  { at: 4.3, x: 0.22, y: 0.3, dir: 1 },
]
/** the notes a wish sings (a pentatonic scale, so any of them goes with the music) */
const NOTES = [659.25, 783.99, 880, 987.77, 1174.66]
/** the least time between two wishes made by clicking (ms) */
const GAP = 380

const VERT = /* glsl */ `
attribute float aAlpha;
attribute float aSize;
uniform float uPixelRatio;
uniform float uScale;
varying float vAlpha;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  vAlpha = aAlpha;
  gl_PointSize = min(aSize * uScale * uPixelRatio * (8.0 / max(0.6, -mv.z)), 46.0 * uPixelRatio);
}
`

const FRAG = /* glsl */ `
uniform vec3 uHead;
uniform vec3 uTail;
varying float vAlpha;
void main() {
  float r = length(gl_PointCoord - 0.5) * 2.0;
  if (r > 1.0 || vAlpha < 0.01) discard;
  float core = 1.0 - smoothstep(0.0, 0.5, r);
  float halo = pow(1.0 - r, 2.2);
  gl_FragColor = vec4(mix(uTail, uHead, core), (core * 0.9 + halo * 0.6) * vAlpha);
}
`

type Meteor = {
  alive: boolean
  age: number
  life: number
  origin: THREE.Vector3
  dir: THREE.Vector3
  length: number
  burst: boolean
  /** the sparkles of the burst fly off in these directions (unit vectors, 3 numbers each) and at these speeds */
  spray: number[]
}

const easeOut = (u: number) => 1 - (1 - u) * (1 - u)
const smooth = (u: number) => {
  const t = Math.min(1, Math.max(0, u))
  return t * t * (3 - 2 * t)
}

export default function Wishes() {
  const camera = useThree((s) => s.camera)
  const built = useMemo(() => {
    const n = MAX * PER
    const geometry = new THREE.BufferGeometry()
    const position = new THREE.BufferAttribute(new Float32Array(n * 3), 3)
    const alpha = new THREE.BufferAttribute(new Float32Array(n), 1)
    const size = new THREE.BufferAttribute(new Float32Array(n), 1)
    position.setUsage(THREE.DynamicDrawUsage)
    alpha.setUsage(THREE.DynamicDrawUsage)
    size.setUsage(THREE.DynamicDrawUsage)
    geometry.setAttribute('position', position)
    geometry.setAttribute('aAlpha', alpha)
    geometry.setAttribute('aSize', size)
    const material = new THREE.ShaderMaterial({
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      uniforms: {
        uPixelRatio: shared.pixelRatio,
        uScale: { value: 11 },
        uHead: { value: palette.hot },
        uTail: { value: palette.accent },
      },
    })
    const meteors: Meteor[] = Array.from({ length: MAX }, () => ({
      alive: false,
      age: 0,
      life: 1,
      origin: new THREE.Vector3(),
      dir: new THREE.Vector3(),
      length: 6,
      burst: false,
      spray: Array.from({ length: BURST * 4 }, () => 0),
    }))
    return { geometry, position, alpha, size, material, meteors }
  }, [])
  useEffect(
    () => () => {
      built.geometry.dispose()
      built.material.dispose()
    },
    [built],
  )

  const st = useMemo(
    () => ({
      lastWish: 0,
      lastClock: 0,
      wasAny: false,
      right: new THREE.Vector3(),
      up: new THREE.Vector3(),
      point: new THREE.Vector3(),
    }),
    [],
  )

  /** A shooting star that starts at a screen position (share of the window, y down) and runs across the sky. */
  const spawn = (fx: number, fy: number, dir: number, burst: boolean) => {
    const m = built.meteors.find((e) => !e.alive)
    if (!m) return
    const ray = rayAt(camera, fx * window.innerWidth, fy * window.innerHeight)
    m.origin.copy(ray.ray.origin).addScaledVector(ray.ray.direction, 13)
    st.right.setFromMatrixColumn(camera.matrixWorld, 0)
    st.up.setFromMatrixColumn(camera.matrixWorld, 1)
    const angle = ((18 + Math.random() * 18) * Math.PI) / 180
    m.dir.copy(st.right).multiplyScalar(Math.cos(angle) * dir).addScaledVector(st.up, -Math.sin(angle)).normalize()
    m.length = 6.5
    m.life = 1.05
    m.age = 0
    m.burst = burst
    for (let i = 0; i < BURST; i++) {
      const a = Math.random() * Math.PI * 2
      const b = (Math.random() - 0.5) * 1.6
      m.spray[i * 4] = Math.cos(a) * Math.cos(b)
      m.spray[i * 4 + 1] = Math.sin(a) * Math.cos(b)
      m.spray[i * 4 + 2] = Math.sin(b)
      m.spray[i * 4 + 3] = 0.5 + Math.random() * 0.9
    }
    m.alive = true
  }

  useFrame((_state, dtRaw) => {
    if (world.reduced) return
    const dt = Math.min(dtRaw, 0.1)
    const now = performance.now()

    // ---- new ones: a tap on open sky that nothing else wanted, and the opening film's own
    if (pick.tapNow && !pick.tapUsed && world.entered && !world.film.on && now - st.lastWish > GAP) {
      st.lastWish = now
      pick.tapUsed = true
      spawn(pick.tapNow.x / window.innerWidth, pick.tapNow.y / window.innerHeight, Math.random() < 0.5 ? 1 : -1, true)
      ambient.chime(NOTES[Math.floor(Math.random() * NOTES.length)], 0.05)
    }
    if (world.film.on) {
      const clock = world.film.clock
      for (const f of FILM_METEORS) if (st.lastClock < f.at && clock >= f.at) spawn(f.x, f.y, f.dir, false)
      st.lastClock = clock
    }

    // ---- move them
    const pos = built.position
    const alpha = built.alpha
    const size = built.size
    let any = false
    built.meteors.forEach((m, mi) => {
      const base = mi * PER
      if (m.alive) {
        m.age += dt
        if (m.age >= m.life) m.alive = false
      }
      if (!m.alive) {
        for (let j = 0; j < PER; j++) alpha.setX(base + j, 0)
        return
      }
      any = true
      const a = m.age / m.life
      const envelope = smooth(a * 7) * (1 - smooth((a - 0.62) / 0.38))
      for (let j = 0; j < TRAIL; j++) {
        const aj = Math.max(0, a - j * 0.013)
        const s = easeOut(aj) * m.length
        st.point.copy(m.origin).addScaledVector(m.dir, s)
        pos.setXYZ(base + j, st.point.x, st.point.y, st.point.z)
        alpha.setX(base + j, Math.pow(1 - j / TRAIL, 1.7) * envelope)
        size.setX(base + j, j === 0 ? 1.9 : 1.2 * (1 - 0.75 * (j / TRAIL)))
      }
      for (let i = 0; i < BURST; i++) {
        const k = base + TRAIL + i
        if (!m.burst) {
          alpha.setX(k, 0)
          continue
        }
        const travel = (1 - Math.pow(1 - Math.min(1, a * 1.6), 3)) * m.spray[i * 4 + 3] * 1.1
        pos.setXYZ(k, m.origin.x + m.spray[i * 4] * travel, m.origin.y + m.spray[i * 4 + 1] * travel, m.origin.z + m.spray[i * 4 + 2] * travel)
        alpha.setX(k, Math.pow(Math.max(0, 1 - a * 1.25), 1.5) * smooth(a * 12))
        size.setX(k, 0.9)
      }
    })
    // upload only while something is flying, and once more after the last one has gone (to clear it)
    if (any || st.wasAny) {
      pos.needsUpdate = true
      alpha.needsUpdate = true
      size.needsUpdate = true
    }
    st.wasAny = any
  })

  return <points geometry={built.geometry} material={built.material} frustumCulled={false} renderOrder={10} />
}
