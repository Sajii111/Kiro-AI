import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { HAND_CENTRE, HAND_STROKES, handDepth, sampleSpline, type LineId, type Stroke } from '../../lib/handGeometry'
import { palette } from './palette'
import {
  dotsMaterial,
  particleGeometry,
  particleMaterial,
  ribbonGeometry,
  ribbonMaterial,
  type RibbonStyle,
} from './materials'
import { clearTip, pick, setTip } from './pick'
import { world } from './state'
import { rng } from '../../lib/rand'
import { t } from '../../i18n'

// The signature object: a hand made of flowing line ribbons and rising particles.
// It draws itself in, floats, and leans a little towards the pointer.
//  - the hero hand also takes part in the opening film (film): it draws itself in step with the loader, faces the viewer while
//    the camera is far away, and turns, floats and follows the pointer only as the camera arrives
//  - the hero hand can be explored (interactive): hover one of the five palm lines (or tap it on a touch screen) and it
//    lights up while a small label names it, together with what tradition associates it with

export type LineStatus = 'detected' | 'uncertain' | 'missing'
export type StatusMap = Partial<Record<LineId, LineStatus>>

// centre of the hand so it rotates around its middle
const CX = HAND_CENTRE.x
const CY = HAND_CENTRE.y

/** What the label says for each line: its name and the theme tradition gives it (not a claim, and never advice). */
const LINE_TIPS: Record<string, string> = {
  heart: t("Heart line · tradition: feelings"),
  head: t("Head line · tradition: thinking"),
  life: t("Life line · tradition: life’s journey"),
  fate: t("Fate line · tradition: direction"),
  sun: t("Sun line · tradition: creativity"),
}

type Props = {
  position?: [number, number, number]
  rotation?: [number, number, number]
  scale?: number
  mirror?: boolean
  particles?: number
  /** wait for the intro gate to lift before drawing (hero only) */
  gate?: boolean
  /** seconds to wait before the timed draw-in starts */
  delay?: number
  /** controlled draw-in 0..1, read every frame (overrides the timed draw) */
  progress?: () => number
  /** colour and style each palm line by detected / uncertain / not visible */
  status?: StatusMap
  /** show a marker on each line (for the scanning scene) */
  nodes?: boolean
  follow?: number
  float?: number
  opacity?: number
  /** distance range over which the hand fades out (near, far) */
  fog?: [number, number]
  /** part of the opening film (world.film): flat to the viewer, still and with steady line weight until the camera arrives */
  film?: boolean
  /** the palm lines answer the pointer: hover or tap one to light it up and read its name */
  interactive?: boolean
}

type Item = {
  material: THREE.ShaderMaterial
  t0: number
  dur: number
  a: number
  b: number
  lineId?: string
}

/** A bright copy of one palm line, laid over it while it is being looked at. */
type Glint = {
  material: THREE.ShaderMaterial
  mesh: THREE.Mesh
  lineId: string
  poly: THREE.Vector3[]
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
const smooth = (u: number) => u * u * (3 - 2 * u)
const easeOut = (u: number) => 1 - Math.pow(1 - u, 3)

function lineStyle(status: LineStatus, scale: number, opacity: number, index: number): RibbonStyle {
  const width = 0.03 * scale
  if (status === 'detected') {
    return {
      width,
      colorA: palette.lineA,
      colorB: palette.lineB,
      opacity: opacity,
      glow: 0.9,
      core: 0.4,
      pulse: 1,
      pulseFreq: 1.4,
      pulseSpeed: 0.14 + index * 0.025,
    }
  }
  if (status === 'uncertain') {
    return { width, colorA: palette.uncertain, colorB: palette.uncertain, opacity: 0.95 * opacity, glow: 0.6, core: 0.4, dash: 16, duty: 0.58 }
  }
  return { width: width * 0.8, colorA: palette.missing, colorB: palette.missing, opacity: 0.6 * opacity, glow: 0.15, core: 0.4, dash: 11, duty: 0.3 }
}

function build(
  mirror: boolean,
  scale: number,
  status: StatusMap | undefined,
  opacity: number,
  particles: number,
  nodes: boolean,
  fog: [number, number],
  boost: { value: number } | undefined,
  interactive: boolean,
) {
  const root = new THREE.Group()
  const items: Item[] = []
  const glints: Glint[] = []
  const disposables: { dispose(): void }[] = []
  const local = (x: number, y: number) => new THREE.Vector3(mirror ? -(x - CX) : x - CX, y - CY, handDepth(x, y))

  let lineIndex = 0
  const nodeSpots: { p: THREE.Vector3; status: LineStatus; lineId: string }[] = []

  for (const stroke of HAND_STROKES) {
    const polyline = sampleSpline(stroke.pts, stroke.kind === 'crease' ? 6 : 10).map(([x, y]) => local(x, y))
    const geometry = ribbonGeometry(polyline)
    let style: RibbonStyle
    let t0: number, dur: number, a: number, b: number

    if (stroke.kind === 'outline') {
      style = { width: 0.022 * scale, colorA: palette.ink, colorB: palette.ink, opacity: 0.92 * opacity, glow: 0.35, core: 0.5 }
      t0 = 0; dur = 2.4; a = 0; b = 0.42
    } else if (stroke.kind === 'crease') {
      style = { width: 0.011 * scale, colorA: palette.muted, colorB: palette.muted, opacity: 0.55 * opacity, glow: 0.1, core: 0.6 }
      t0 = 1.9; dur = 1.0; a = 0.7; b = 1
    } else {
      const st = status?.[stroke.id as LineId] ?? 'detected'
      style = lineStyle(st, scale, opacity, lineIndex)
      t0 = 0.8 + lineIndex * 0.32; dur = 1.4; a = 0.3 + lineIndex * 0.085; b = a + 0.3
      if (nodes) {
        for (const f of [0.14, 0.4, 0.66, 0.9]) {
          const i = Math.min(polyline.length - 1, Math.floor(f * (polyline.length - 1)))
          nodeSpots.push({ p: polyline[i], status: st, lineId: stroke.id })
        }
      }
      if (interactive) {
        const glintMaterial = ribbonMaterial({
          width: style.width * 1.8,
          colorA: palette.hot,
          colorB: palette.hot,
          opacity: 0,
          glow: 0.95,
          core: 0.4,
          draw: 1,
          fogNear: fog[0],
          fogFar: fog[1],
          boost,
        })
        const glintMesh = new THREE.Mesh(geometry, glintMaterial)
        glintMesh.frustumCulled = false
        glintMesh.visible = false
        glintMesh.renderOrder = 2
        root.add(glintMesh)
        disposables.push(glintMaterial)
        glints.push({ material: glintMaterial, mesh: glintMesh, lineId: stroke.id, poly: polyline })
      }
      lineIndex++
    }

    const material = ribbonMaterial({ ...style, draw: 0, fogNear: fog[0], fogFar: fog[1], boost })
    const mesh = new THREE.Mesh(geometry, material)
    mesh.frustumCulled = false
    root.add(mesh)
    disposables.push(geometry, material)
    items.push({ material, t0, dur, a, b, lineId: stroke.kind === 'line' ? stroke.id : undefined })
  }

  // rising particles, scattered along the palm lines and the outline
  let points: THREE.Points | undefined
  let pointsMaterial: THREE.ShaderMaterial | undefined
  if (particles > 0) {
    const sources = HAND_STROKES.filter((s: Stroke) => s.kind !== 'crease').map((s: Stroke) => ({
      poly: sampleSpline(s.pts, 8),
      weight: s.kind === 'line' ? 2.4 : 1,
    }))
    const totalWeight = sources.reduce((acc: number, s: { weight: number }) => acc + s.weight, 0)
    const rand = rng(4242 + particles)
    const geo = particleGeometry(particles, (_i, out) => {
      let r = rand() * totalWeight
      let src = sources[0]
      for (const s of sources) {
        r -= s.weight
        if (r <= 0) { src = s; break }
      }
      const f = rand() * (src.poly.length - 1)
      const i = Math.floor(f)
      const j = Math.min(src.poly.length - 1, i + 1)
      const k = f - i
      const x = src.poly[i][0] + (src.poly[j][0] - src.poly[i][0]) * k
      const y = src.poly[i][1] + (src.poly[j][1] - src.poly[i][1]) * k
      out.set(mirror ? -(x - CX) : x - CX, y - CY, handDepth(x, y))
      out.x += (rand() - 0.5) * 0.06
      out.y += (rand() - 0.5) * 0.06
      out.z += (rand() - 0.5) * 0.12
    })
    pointsMaterial = particleMaterial({ size: 3.4, rise: 0.9, sway: 0.05, speed: 0.1, opacity: 0, colorA: palette.lineA, colorB: palette.lineB, fogNear: fog[0], fogFar: fog[1] })
    points = new THREE.Points(geo, pointsMaterial)
    points.frustumCulled = false
    root.add(points)
    disposables.push(geo, pointsMaterial)
  }

  // status markers
  let nodeMaterial: THREE.ShaderMaterial | undefined
  let nodeGeometry: THREE.BufferGeometry | undefined
  if (nodes && nodeSpots.length) {
    const n = nodeSpots.length
    const pos = new Float32Array(n * 3)
    const col = new Float32Array(n * 3)
    const size = new Float32Array(n)
    const pulse = new Float32Array(n)
    nodeSpots.forEach((s, i) => {
      pos.set([s.p.x, s.p.y, s.p.z + 0.01], i * 3)
      const c = s.status === 'detected' ? palette.detected : s.status === 'uncertain' ? palette.uncertain : palette.missing
      col.set([c.r, c.g, c.b], i * 3)
      size[i] = s.status === 'missing' ? 1.1 : 1
      pulse[i] = s.status === 'uncertain' ? 1 : s.status === 'missing' ? -1 : 0
    })
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    g.setAttribute('aColor', new THREE.BufferAttribute(col, 3))
    g.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
    g.setAttribute('aPulse', new THREE.BufferAttribute(pulse, 1))
    nodeMaterial = dotsMaterial(9 * scale + 3, 0)
    const dots = new THREE.Points(g, nodeMaterial)
    dots.frustumCulled = false
    root.add(dots)
    disposables.push(g, nodeMaterial)
    nodeGeometry = g
  }

  return {
    root,
    items,
    glints,
    points,
    pointsMaterial,
    nodeMaterial,
    nodeGeometry,
    nodeSpots,
    dispose: () => disposables.forEach((d) => d.dispose()),
  }
}

export default function Hand({
  position = [0, 0, 0],
  rotation = [0, 0, 0],
  scale = 1,
  mirror = false,
  particles = 0,
  gate = false,
  delay = 0,
  progress,
  status,
  nodes = false,
  follow = 0,
  float = 0,
  opacity = 1,
  fog = [28, 62],
  film = false,
  interactive = false,
}: Props) {
  const group = useRef<THREE.Group>(null)
  const built = useMemo(
    () => build(mirror, scale, status, opacity, particles, nodes, fog, film ? world.film.boost : undefined, interactive),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mirror, scale, status, opacity, particles, nodes, fog[0], fog[1], film, interactive],
  )
  useEffect(() => () => built.dispose(), [built])
  const startedAt = useRef<number | null>(null)
  const lean = useRef({ x: 0, y: 0 })
  const phase = useMemo(() => Math.abs(Math.sin(position[0] * 12.9898 + position[2] * 78.233)) * 6.28, [position])
  // what the pointer is doing to the palm lines
  const look = useMemo(() => ({ lit: built.glints.map(() => 0), tapIndex: -1, tapUntil: 0, v: new THREE.Vector3() }), [built])

  /** The palm line (index into built.glints) that passes closest to a screen position, within `within` px; -1 if none does. */
  const nearestLine = (camera: THREE.Camera, x: number, y: number, within: number): number => {
    const g = group.current
    if (!g) return -1
    let best = -1
    let bestD = within
    built.glints.forEach((gl, i) => {
      for (const p of gl.poly) {
        look.v.copy(p).applyMatrix4(g.matrixWorld).project(camera)
        if (look.v.z > 1) continue
        const d = Math.hypot((look.v.x * 0.5 + 0.5) * window.innerWidth - x, (-look.v.y * 0.5 + 0.5) * window.innerHeight - y)
        if (d < bestD) {
          bestD = d
          best = i
        }
      }
    })
    return best
  }

  useFrame((state, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1)
    const t = state.clock.elapsedTime
    // how far the opening film has got with this hand: 1 for every hand when there is no film
    const tilt = film ? world.film.tilt : 1
    const live = film ? world.film.live : 1

    // ---- draw-in
    let overall = 1
    if (world.reduced) {
      for (const it of built.items) it.material.uniforms.uDraw.value = 1
    } else if (progress) {
      const p = progress()
      for (const it of built.items) it.material.uniforms.uDraw.value = smooth(clamp01((p - it.a) / (it.b - it.a)))
      overall = p
    } else {
      if (startedAt.current === null && (!gate || world.entered)) startedAt.current = t + delay
      const el = startedAt.current === null ? -1 : t - startedAt.current
      for (const it of built.items) it.material.uniforms.uDraw.value = easeOut(clamp01((el - it.t0) / it.dur))
      overall = clamp01(el / 3)
    }
    if (built.pointsMaterial) built.pointsMaterial.uniforms.uOpacity.value = 0.9 * clamp01(overall * 1.4 - 0.2) * opacity * tilt
    if (built.nodeMaterial) built.nodeMaterial.uniforms.uOpacity.value = clamp01((overall - 0.55) * 4) * opacity

    // ---- markers follow the palette so they swap colour with the theme
    if (built.nodeGeometry) {
      const attr = built.nodeGeometry.getAttribute('aColor') as THREE.BufferAttribute
      built.nodeSpots.forEach((s, i) => {
        const c = s.status === 'detected' ? palette.detected : s.status === 'uncertain' ? palette.uncertain : palette.missing
        attr.setXYZ(i, c.r, c.g, c.b)
      })
      attr.needsUpdate = true
    }

    // ---- gentle motion
    const g = group.current
    if (g && !world.reduced) {
      const k = 1 - Math.exp(-3 * dt)
      lean.current.x += (-world.pointer.y * 0.2 * follow * live - lean.current.x) * k
      lean.current.y += (world.pointer.x * 0.35 * follow * live - lean.current.y) * k
      g.rotation.set(rotation[0] * tilt + lean.current.x, rotation[1] * tilt + lean.current.y, rotation[2] * tilt)
      g.position.y = position[1] + Math.sin(t * 0.9 + phase) * 0.07 * float * live
    }

    // ---- the palm lines answer the pointer
    if (g && built.glints.length) {
      const active = !world.reduced && world.entered && !world.film.on && overall > 0.9 && state.camera.position.z > 3
      let hit = -1
      if (active) {
        g.updateWorldMatrix(true, false)
        if (pick.inside && pick.open && !pick.touch) hit = nearestLine(state.camera, pick.x, pick.y, 24)
        if (pick.tapNow && !pick.tapUsed) {
          const i = nearestLine(state.camera, pick.tapNow.x, pick.tapNow.y, 44)
          if (i >= 0) {
            look.tapIndex = i
            look.tapUntil = performance.now() + 2400
            pick.tapUsed = true
          }
        }
      }
      const tapped = performance.now() < look.tapUntil ? look.tapIndex : -1
      const shown = active ? (hit >= 0 ? hit : pick.touch ? tapped : -1) : -1
      if (shown >= 0) {
        const id = built.glints[shown].lineId
        setTip('hand', LINE_TIPS[id] ?? id)
        world.hit = `hand:${id}`
      } else {
        clearTip('hand')
        if (world.hit.startsWith('hand:')) world.hit = ''
      }
      const k = 1 - Math.exp(-10 * dt)
      built.glints.forEach((gl, i) => {
        look.lit[i] += ((i === shown ? 1 : 0) - look.lit[i]) * k
        gl.mesh.visible = look.lit[i] > 0.01
        gl.material.uniforms.uOpacity.value = 0.95 * look.lit[i] * opacity
      })
    }
  })

  return (
    <group ref={group} position={position} rotation={rotation} scale={scale}>
      <primitive object={built.root} />
    </group>
  )
}
