import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { CONSTELLATIONS } from './constellations'
import { ribbonMaterial, ribbonsGeometry, shared, starsMaterial } from './materials'
import { palette } from './palette'
import { clearTip, pick, rayAt, setTip } from './pick'
import { world } from './state'

// A zodiac wheel that turns slowly around the hand while it is being scanned: twelve small constellations,
// each a few stars joined by straight lines. There is no ring or tick drawn between them: the signs float on their own,
// so the hand is not boxed in by curves.
//  - hover a constellation: it lights up, light runs along its lines, the wheel pauses and a label names the sign
//  - click or tap one: its stars flare
//  - scrolling through "how it works" also turns the wheel
// With reduced motion it is a still picture and nothing reacts.

const TAU = Math.PI * 2
const SECTOR = TAU / 12
/** radius of the ring the constellations sit on, and the band where the pointer counts as "on" a sign */
const RC = 3.4
const BAND: [number, number] = [2.75, 4.05]

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a))
  return t * t * (3 - 2 * t)
}

type Disposable = { dispose(): void }

function build() {
  const root = new THREE.Group()
  const disposables: Disposable[] = []

  // The signs sit between the text and the hand, so they fade out over the text side of the screen sooner and
  // harder than the rest of the scene does (the shared text-safe ramp is gentler, because it is made for thin lines).
  const safe = { value: new THREE.Vector4(1, 0, 0.3, 0.58) }
  const safeMin = { value: 0.1 }
  const textSafe = (m: THREE.ShaderMaterial) => {
    m.uniforms.uSafe = safe
    m.uniforms.uSafeMin = safeMin
    return m
  }

  const items = CONSTELLATIONS.map((c, i) => {
    const group = new THREE.Group()
    // the first sign sits just right of the top, the rest follow clockwise; each one stands with its "up" pointing outwards
    const phi = Math.PI / 2 - (i + 0.5) * SECTOR
    group.position.set(Math.cos(phi) * RC, Math.sin(phi) * RC, 0)
    group.rotation.z = phi - Math.PI / 2

    const chains = c.lines.map((chain) => chain.map((k) => new THREE.Vector3(c.stars[k][0], c.stars[k][1], 0)))
    const lineGeometry = ribbonsGeometry(chains)
    const lineMaterial = textSafe(
      ribbonMaterial({
        width: 0.036,
        opacity: 0.6,
        colorA: palette.lineA,
        colorB: palette.lineA,
        glow: 0.55,
        core: 0.42,
        pulseFreq: 1.4,
        pulseSpeed: 0.4,
        fogNear: 12,
        fogFar: 30,
      }),
    )
    const lines = new THREE.Mesh(lineGeometry, lineMaterial)
    lines.frustumCulled = false

    const pos = new Float32Array(c.stars.length * 3)
    const size = new Float32Array(c.stars.length)
    c.stars.forEach(([x, y], k) => {
      pos[k * 3] = x
      pos[k * 3 + 1] = y
      size[k] = c.big?.includes(k) ? 1.75 : 1
    })
    const starGeometry = new THREE.BufferGeometry()
    starGeometry.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    starGeometry.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
    const starMaterial = textSafe(starsMaterial(17))
    const points = new THREE.Points(starGeometry, starMaterial)
    points.frustumCulled = false

    group.add(lines, points)
    root.add(group)
    disposables.push(lineGeometry, lineMaterial, starGeometry, starMaterial)
    return { lineMaterial, starMaterial, lit: 0, flare: 0 }
  })

  return { root, items, safe, safeMin, dispose: () => disposables.forEach((d) => d.dispose()) }
}

export default function ZodiacWheel() {
  const camera = useThree((s) => s.camera)
  const built = useMemo(() => build(), [])
  useEffect(() => () => built.dispose(), [built])

  const holder = useRef<THREE.Group>(null)
  const st = useMemo(() => ({ angle: 0.3, speed: 1, tapIndex: -1, tapUntil: 0 }), [])
  const scratch = useMemo(
    () => ({
      inverse: new THREE.Matrix4(),
      ray: new THREE.Ray(),
      point: new THREE.Vector3(),
      centre: new THREE.Vector3(),
      plane: new THREE.Plane(new THREE.Vector3(0, 0, 1), 0),
    }),
    [],
  )

  /** Which sign (0..11) is at this screen position? -1 if the position is not on the wheel's band. */
  const signAt = (x: number, y: number): number => {
    const spin = built.root
    spin.updateWorldMatrix(true, false)
    scratch.inverse.copy(spin.matrixWorld).invert()
    scratch.ray.copy(rayAt(camera, x, y).ray).applyMatrix4(scratch.inverse)
    const p = scratch.ray.intersectPlane(scratch.plane, scratch.point)
    if (!p) return -1
    const r = Math.hypot(p.x, p.y)
    if (r < BAND[0] || r > BAND[1]) return -1
    const d = (((Math.PI / 2 - Math.atan2(p.y, p.x)) % TAU) + TAU) % TAU
    return Math.floor(d / SECTOR)
  }

  useFrame((_, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1)
    const g = holder.current
    if (!g) return
    const now = performance.now()

    // present only when the camera is near the scanner
    g.getWorldPosition(scratch.centre)
    const fade = 1 - smoothstep(9, 18, camera.position.distanceTo(scratch.centre))
    g.visible = fade > 0.003
    if (!g.visible) {
      clearTip('zodiac')
      if (world.hit.startsWith('zodiac:')) world.hit = ''
      return
    }

    const live = fade > 0.3 && !world.reduced && world.entered
    let hit = -1
    if (live && pick.inside && pick.open && !pick.touch) hit = signAt(pick.x, pick.y)
    if (live && pick.tapNow) {
      const i = signAt(pick.tapNow.x, pick.tapNow.y)
      if (i >= 0) {
        built.items[i].flare = 1
        st.tapIndex = i
        st.tapUntil = now + 2400
        pick.tapUsed = true
      }
    }
    const tapped = now < st.tapUntil ? st.tapIndex : -1
    const shown = hit >= 0 ? hit : pick.touch ? tapped : -1

    if (shown >= 0) {
      const c = CONSTELLATIONS[shown]
      setTip('zodiac', `${c.name} · ${c.dates}`)
      world.hit = `zodiac:${c.name.toLowerCase()}`
    } else {
      clearTip('zodiac')
      if (world.hit.startsWith('zodiac:')) world.hit = ''
    }

    // on a phone the text sits at the bottom, so the ordinary text-safe ramp is used there
    if (world.narrow) {
      built.safe.value.copy(shared.safe.value)
      built.safeMin.value = shared.safeMin.value
    } else {
      built.safe.value.set(1, 0, 0.3, 0.58)
      built.safeMin.value = 1 - 0.9 * world.safe
    }

    // the wheel turns clockwise, pauses while a sign is being looked at, and follows the scroll through "how it works"
    if (!world.reduced) {
      st.speed += ((shown >= 0 ? 0 : 1) - st.speed) * (1 - Math.exp(-3 * dt))
      st.angle -= dt * 0.032 * st.speed
    }
    built.root.rotation.z = st.angle - world.howProgress * 1.1

    const k = 1 - Math.exp(-9 * dt)
    built.items.forEach((it, i) => {
      it.lit += ((i === shown ? 1 : 0) - it.lit) * k
      it.flare = Math.max(0, it.flare - dt * 1.3)
      const L = Math.min(1, it.lit + it.flare * 0.8)
      const lu = it.lineMaterial.uniforms
      lu.uOpacity.value = (0.62 + 0.38 * L) * fade
      lu.uPulse.value = L
      lu.uGlow.value = 0.45 + 0.5 * L
      const su = it.starMaterial.uniforms
      su.uOpacity.value = (0.95 + 0.05 * L) * fade
      su.uLit.value = L
      su.uDark.value = palette.dark
    })
  })

  return (
    // a little right of the hand and behind it, so the signs sit in the open space between the text and the hand
    <group ref={holder} position={[0.95, 0, -0.5]} rotation={[0.1, -0.06, 0]}>
      <primitive object={built.root} />
    </group>
  )
}
