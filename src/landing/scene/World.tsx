import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import FilmSet from './FilmSet'
import Galaxy from './Galaxy'
import Hand, { type StatusMap } from './Hand'
import { PaletteDriver, palette } from './palette'
import { PickDriver } from './pick'
import Planet from './Planet'
import { BUBBLES, HERO_HAND, SCAN, SUN, TWO_HANDS } from './journey'
import {
  glowMaterial,
  particleGeometry,
  particleMaterial,
  ribbonGeometry,
  ribbonMaterial,
  shared,
  sunMaterial,
  sweepMaterial,
} from './materials'
import { rng } from '../../lib/rand'
import { world } from './state'
import Wishes from './Wishes'
import ZodiacWheel from './Zodiac'

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a))
  return t * t * (3 - 2 * t)
}
const easeOut = (u: number) => 1 - Math.pow(1 - u, 3)

type Disposable = { dispose(): void }

// ---------------------------------------------------------------- housekeeping

function Clock() {
  const gl = useThree((s) => s.gl)
  useFrame((state) => {
    shared.time.value = world.reduced ? 0 : state.clock.elapsedTime
    shared.pixelRatio.value = gl.getPixelRatio()
    shared.res.value.set(gl.domElement.width, gl.domElement.height)
    // text sits on the left of the screen on desktop and at the bottom on phones (the opening film has no text yet)
    if (world.narrow) shared.safe.value.set(0, 1, 0.1, 0.5)
    else shared.safe.value.set(1, 0, 0.1, 0.62)
    shared.safeMin.value = 1 - 0.84 * world.safe * world.film.text
  })
  return null
}

// ---------------------------------------------------------------- hero

function HeroGlow() {
  const material = useMemo(() => glowMaterial(0.45), [])
  useEffect(() => () => material.dispose(), [material])
  useFrame(() => {
    material.uniforms.uOpacity.value = 0.46 - palette.dark * 0.12
  })
  return (
    <mesh position={[HERO_HAND.pos[0] + 0.1, HERO_HAND.pos[1] + 0.25, -2.6]} material={material}>
      <planeGeometry args={[12, 12]} />
    </mesh>
  )
}

function HeroHand({ narrow }: { narrow: boolean }) {
  // During the opening film the hand draws itself in step with the loading bar (the gate's drawing is this same hand), so it is
  // complete the moment the loader reaches 100%. Without a film it draws itself when the page opens, as before.
  const progress = useMemo(() => (world.film.on ? () => world.film.load : undefined), [])
  // far away at the start of the film, so its lines may not fade until much further out
  const fog = useMemo<[number, number]>(() => [40, 90], [])
  return (
    <Hand
      position={HERO_HAND.pos}
      rotation={HERO_HAND.rot}
      scale={narrow ? HERO_HAND.narrowScale : HERO_HAND.scale}
      particles={narrow ? 900 : 2600}
      gate
      delay={0.15}
      follow={1}
      float={1}
      fog={fog}
      progress={progress}
      film
      interactive
    />
  )
}

// ---------------------------------------------------------------- chapter 1: two hands

function TwoHands({ narrow }: { narrow: boolean }) {
  const camera = useThree((s) => s.camera)
  const progress = useMemo(() => () => clamp01((-camera.position.z - 4.5) / 6), [camera])
  const fog = useMemo<[number, number]>(() => [9, 24], [])
  const scale = narrow ? TWO_HANDS.scale * 0.8 : TWO_HANDS.scale
  return (
    <>
      <Hand
        mirror
        position={[TWO_HANDS.xs[0], TWO_HANDS.y, TWO_HANDS.z]}
        rotation={[0.04, 0.3, -0.07]}
        scale={scale}
        particles={narrow ? 120 : 380}
        progress={progress}
        follow={0.25}
        float={1}
        fog={fog}
      />
      <Hand
        position={[TWO_HANDS.xs[1], TWO_HANDS.y, TWO_HANDS.z - 0.3]}
        rotation={[0.04, -0.3, 0.07]}
        scale={scale}
        particles={narrow ? 120 : 380}
        progress={progress}
        follow={0.25}
        float={1}
        fog={fog}
      />
    </>
  )
}

// ---------------------------------------------------------------- chapter 2: the scanner

const SCAN_STATUS: StatusMap = { heart: 'detected', head: 'detected', life: 'detected', fate: 'uncertain', sun: 'missing' }

function ScanObject() {
  const camera = useThree((s) => s.camera)
  const theta = 1.1
  const sweepMat = useMemo(() => sweepMaterial(theta), [])
  const sweep = useRef<THREE.Mesh>(null)
  useEffect(() => () => sweepMat.dispose(), [sweepMat])

  const progress = useMemo(
    () => () => {
      const approach = smoothstep(-14, -19, camera.position.z) * 0.2
      return clamp01(approach + world.howProgress / 0.55)
    },
    [camera],
  )
  const hand = useMemo<[number, number]>(() => [7, 20], [])

  useFrame((_state, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1)
    if (sweep.current) sweep.current.rotation.z -= world.reduced ? 0 : dt * 0.9
    sweepMat.uniforms.uOpacity.value = 0.5 * smoothstep(-17, -20, camera.position.z)
  })

  return (
    <group position={SCAN.pos}>
      <ZodiacWheel />
      <mesh ref={sweep} material={sweepMat}>
        <circleGeometry args={[3.0, 48, 0, theta]} />
      </mesh>
      <Hand scale={1.25} status={SCAN_STATUS} nodes progress={progress} follow={0.3} float={0.6} fog={hand} />
    </group>
  )
}

// ---------------------------------------------------------------- chapter 3: conversation bubbles

const BUBBLE_SPECS = [
  { x: -0.7, y: -1.75, z: 0.0, w: 2.3, h: 0.95, bot: true, lines: 2 },
  { x: 0.95, y: -0.6, z: 0.35, w: 1.7, h: 0.7, bot: false, lines: 1 },
  { x: -0.55, y: 0.55, z: -0.25, w: 2.6, h: 1.15, bot: true, lines: 3 },
  { x: 1.0, y: 1.7, z: 0.2, w: 1.55, h: 0.62, bot: false, lines: 1 },
]

function bubbleOutline(w: number, h: number, bot: boolean): THREE.Vector3[] {
  const r = Math.min(0.22, h * 0.4)
  const n = 8
  const pts: THREE.Vector3[] = []
  const v = (x: number, y: number) => new THREE.Vector3(x, y, 0)
  const arc = (cx: number, cy: number, a0: number, a1: number) => {
    for (let k = 0; k <= n; k++) {
      const a = a0 + ((a1 - a0) * k) / n
      pts.push(v(cx + Math.cos(a) * r, cy + Math.sin(a) * r))
    }
  }
  const x0 = -w / 2
  const x1 = w / 2
  const y0 = -h / 2
  const y1 = h / 2
  if (bot) {
    const tx = x0 + r + 0.28
    pts.push(v(x0 + r, y0), v(tx - 0.14, y0), v(tx - 0.2, y0 - 0.2), v(tx + 0.1, y0), v(x1 - r, y0))
  } else {
    const tx = x1 - r - 0.28
    pts.push(v(x0 + r, y0), v(tx - 0.1, y0), v(tx + 0.2, y0 - 0.2), v(tx + 0.14, y0), v(x1 - r, y0))
  }
  arc(x1 - r, y0 + r, -Math.PI / 2, 0)
  arc(x1 - r, y1 - r, 0, Math.PI / 2)
  arc(x0 + r, y1 - r, Math.PI / 2, Math.PI)
  arc(x0 + r, y0 + r, Math.PI, Math.PI * 1.5)
  return pts
}

function Bubbles() {
  const camera = useThree((s) => s.camera)
  const built = useMemo(() => {
    const root = new THREE.Group()
    const disposables: Disposable[] = []
    const bubbles = BUBBLE_SPECS.map((spec, i) => {
      const group = new THREE.Group()
      group.position.set(spec.x, spec.y, spec.z)
      const mats: THREE.ShaderMaterial[] = []
      const col = spec.bot ? palette.ink : palette.lineA
      const geometry = ribbonGeometry(bubbleOutline(spec.w, spec.h, spec.bot), true)
      const material = ribbonMaterial({
        width: 0.04,
        opacity: spec.bot ? 0.78 : 0.95,
        colorA: col,
        colorB: col,
        glow: 0.7,
        core: 0.45,
        closed: true,
        fogNear: 9,
        fogFar: 26,
        draw: 0,
      })
      const mesh = new THREE.Mesh(geometry, material)
      mesh.frustumCulled = false
      group.add(mesh)
      disposables.push(geometry, material)
      mats.push(material)
      for (let l = 0; l < spec.lines; l++) {
        const y = spec.h / 2 - 0.27 - l * 0.2
        const xEnd = spec.w / 2 - 0.3 - (l === spec.lines - 1 && spec.lines > 1 ? spec.w * 0.25 : 0)
        const lg = ribbonGeometry([new THREE.Vector3(-spec.w / 2 + 0.3, y, 0), new THREE.Vector3(0, y, 0), new THREE.Vector3(xEnd, y, 0)])
        const lm = ribbonMaterial({ width: 0.03, opacity: 0.6, colorA: palette.muted, colorB: palette.muted, glow: 0.2, core: 0.5, fogNear: 9, fogFar: 26, draw: 0 })
        const lmesh = new THREE.Mesh(lg, lm)
        lmesh.frustumCulled = false
        group.add(lmesh)
        disposables.push(lg, lm)
        mats.push(lm)
      }
      root.add(group)
      return { group, mats, baseY: spec.y, i }
    })
    return { root, bubbles, dispose: () => disposables.forEach((d) => d.dispose()) }
  }, [])
  useEffect(() => () => built.dispose(), [built])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    const p = clamp01((-camera.position.z - 24.5) / 5.5)
    for (const b of built.bubbles) {
      const d = easeOut(clamp01(p * 1.9 - b.i * 0.28))
      for (const m of b.mats) m.uniforms.uDraw.value = d
      if (!world.reduced) b.group.position.y = b.baseY + Math.sin(t * 0.6 + b.i * 1.3) * 0.1
    }
  })
  return (
    <group position={BUBBLES.pos} scale={0.82} rotation={[0, -0.18, 0]}>
      <primitive object={built.root} />
    </group>
  )
}

// ---------------------------------------------------------------- the horizon

function Sun() {
  const camera = useThree((s) => s.camera)
  const material = useMemo(() => sunMaterial(), [])
  useEffect(() => () => material.dispose(), [material])
  useFrame(() => {
    material.uniforms.uDark.value = palette.dark
    // the Night Sky has the ringed planet instead, so the sun fades out as the sky darkens
    material.uniforms.uOpacity.value = clamp01((-camera.position.z - 24) / 14) * (1 - palette.dark)
  })
  return (
    <mesh position={SUN.pos} material={material}>
      <planeGeometry args={[SUN.size, SUN.size]} />
    </mesh>
  )
}

// ---------------------------------------------------------------- floating dust through the whole world

function Dust({ narrow }: { narrow: boolean }) {
  const built = useMemo(() => {
    const rand = rng(99)
    const geometry = particleGeometry(narrow ? 500 : 1300, (_i, out) => {
      out.set(-5 + rand() * 13, -3.5 + rand() * 7, -60 + rand() * 66)
    })
    const material = particleMaterial({
      size: 2.4,
      opacity: 0.6,
      rise: 0.6,
      sway: 0.18,
      speed: 0.035,
      colorA: palette.lineA,
      colorB: palette.muted,
      fogNear: 16,
      fogFar: 46,
    })
    return { geometry, material }
  }, [narrow])
  useEffect(
    () => () => {
      built.geometry.dispose()
      built.material.dispose()
    },
    [built],
  )
  return <points geometry={built.geometry} material={built.material} frustumCulled={false} />
}

// ---------------------------------------------------------------- everything

export default function World({ narrow }: { narrow: boolean }) {
  return (
    <>
      <PaletteDriver />
      <PickDriver />
      <Clock />
      <Galaxy narrow={narrow} />
      <HeroGlow />
      <HeroHand narrow={narrow} />
      <TwoHands narrow={narrow} />
      <ScanObject />
      <Bubbles />
      <Sun />
      <Planet />
      <Dust narrow={narrow} />
      <FilmSet />
      {/* last, so it only gets the taps that nothing else in the scene wanted */}
      <Wishes />
    </>
  )
}
