import { useEffect, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { PLANET } from './journey'
import { glowMaterial, ribbonGeometry, ribbonMaterial } from './materials'
import { palette } from './palette'
import { clearTip, pick, rayAt, setTip } from './pick'
import { planetMaterials } from './planetMaterials'
import { world } from './state'

// The ringed planet that rises over the horizon at the end of the journey (Night Sky only: Golden Hour has the sun).
// It is a gas giant with a ring system, a small moon on a faint orbit, and a soft glow behind it.
//  - hover it: it brightens and spins a little faster, and a label says "Drag to spin"
//  - drag it: it follows the mouse (sideways spins it, up and down tips it) and keeps turning when let go
//  - click or tap it: it gets a flick
// On a touch screen a tap is the interaction (a drag would scroll the page). With reduced motion it is a still picture.

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const clamp01 = (v: number) => clamp(v, 0, 1)
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a))
  return t * t * (3 - 2 * t)
}

/** How the ring plane leans: towards the viewer (so the top face shows) and rolled a little in the screen plane. */
const BASE_TILT = { x: 0.3, z: -0.2 }
/** radians per second the planet turns when left alone */
const IDLE = 0.07

function build() {
  const m = planetMaterials()
  const disposables: { dispose(): void }[] = []

  const root = new THREE.Group()
  root.position.set(PLANET.pos[0], PLANET.pos[1], PLANET.pos[2])

  // a soft glow behind the planet
  const glowMat = glowMaterial(0)
  // violet all through, so the haze belongs to the sky around it
  glowMat.uniforms.uColorA = { value: palette.accent }
  glowMat.uniforms.uColorB = { value: palette.accent }
  const glowGeo = new THREE.PlaneGeometry(15, 15)
  const glow = new THREE.Mesh(glowGeo, glowMat)
  glow.position.z = -1.4
  glow.renderOrder = 0

  // everything that shares the ring plane's lean
  const tilt = new THREE.Group()
  tilt.rotation.set(BASE_TILT.x, 0, BASE_TILT.z)

  const bodyGeo = new THREE.SphereGeometry(PLANET.radius, 72, 48)
  const body = new THREE.Mesh(bodyGeo, m.body)
  body.renderOrder = 1

  const ringGeo = new THREE.RingGeometry(PLANET.ring[0], PLANET.ring[1], 160, 2)
  const ring = new THREE.Mesh(ringGeo, m.ring)
  ring.rotation.x = -Math.PI / 2
  ring.renderOrder = 3

  // the moon rides a faint orbit, tilted a little against the rings
  const orbitTilt = new THREE.Group()
  orbitTilt.rotation.set(0.12, 0, 0.05)
  const pivot = new THREE.Group()
  const moonGeo = new THREE.SphereGeometry(PLANET.moonRadius, 32, 24)
  const moon = new THREE.Mesh(moonGeo, m.moon)
  moon.position.x = PLANET.moonOrbit
  moon.renderOrder = 2
  pivot.add(moon)
  const orbitPts: THREE.Vector3[] = []
  for (let i = 0; i <= 160; i++) {
    const a = (i / 160) * Math.PI * 2
    orbitPts.push(new THREE.Vector3(Math.cos(a) * PLANET.moonOrbit, 0, Math.sin(a) * PLANET.moonOrbit))
  }
  const orbitGeo = ribbonGeometry(orbitPts, true)
  const orbitMat = ribbonMaterial({
    closed: true,
    width: 0.022,
    opacity: 0.3,
    colorA: palette.lineB,
    colorB: palette.lineB,
    glow: 0.25,
    dash: 150,
    duty: 0.3,
    fogNear: 30,
    fogFar: 80,
  })
  const orbit = new THREE.Mesh(orbitGeo, orbitMat)
  orbit.frustumCulled = false
  orbit.renderOrder = 4
  orbitTilt.add(orbit, pivot)

  // invisible stand-ins for the pointer to hit: the globe (a little generous) and the ring plane
  const proxyMat = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide })
  const proxyGlobeGeo = new THREE.SphereGeometry(PLANET.radius * 1.1, 20, 14)
  const proxyGlobe = new THREE.Mesh(proxyGlobeGeo, proxyMat)
  const proxyRingGeo = new THREE.RingGeometry(PLANET.ring[0] * 0.97, PLANET.ring[1] * 1.03, 48, 1)
  const proxyRing = new THREE.Mesh(proxyRingGeo, proxyMat)
  proxyRing.rotation.x = -Math.PI / 2
  proxyGlobe.visible = false
  proxyRing.visible = false

  tilt.add(body, ring, orbitTilt, proxyGlobe, proxyRing)
  root.add(glow, tilt)
  disposables.push(m.body, m.ring, m.moon, glowMat, glowGeo, bodyGeo, ringGeo, moonGeo, orbitGeo, orbitMat, proxyMat, proxyGlobeGeo, proxyRingGeo)

  return { root, tilt, body, pivot, orbitMat, glowMat, proxies: [proxyGlobe, proxyRing], m, dispose: () => disposables.forEach((d) => d.dispose()) }
}

export default function Planet() {
  const camera = useThree((s) => s.camera)
  const built = useMemo(() => build(), [])
  useEffect(() => () => built.dispose(), [built])

  const st = useMemo(() => ({ angle: 0.8, omega: IDLE, hover: 0, tilt: 0, pulse: 0, moon: 0.9, wasGrabbed: false }), [])
  // development only: lets test scripts watch the planet's spin (window.__planet)
  useEffect(() => {
    if (import.meta.env.DEV) Object.assign(window, { __planet: st })
  }, [st])
  const tints = useMemo(() => ({ white: new THREE.Color(1, 1, 1) }), [])

  const hitTest = (x: number, y: number) => {
    built.tilt.updateWorldMatrix(true, true)
    return rayAt(camera, x, y).intersectObjects(built.proxies, false).length > 0
  }

  useFrame((_, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1)
    const z = camera.position.z
    // appears as the journey leaves the chat bubbles behind and reaches the horizon, and only in the Night Sky
    const reveal = smoothstep(-33, -43, z)
    const vis = palette.dark * reveal
    built.root.visible = vis > 0.004
    if (!built.root.visible) {
      clearTip('planet')
      if (world.hit === 'planet') world.hit = ''
      return
    }
    // it rises a little as the camera arrives
    built.root.position.y = PLANET.pos[1] - 1.3 * (1 - smoothstep(-36, -46, z))

    // --- pointer
    const live = vis > 0.85 && !world.reduced && world.entered
    const grabbed = pick.dragging === 'planet'
    const hit = live && !grabbed && pick.inside && pick.open && !pick.touch && !pick.dragging && hitTest(pick.x, pick.y)
    if (hit || grabbed) pick.wantGrab = 'planet'
    if (hit) {
      setTip('planet', 'Drag to spin')
      world.hit = 'planet'
    } else {
      clearTip('planet')
      if (grabbed) world.hit = 'planet'
      else if (world.hit === 'planet') world.hit = ''
    }
    if (live && pick.tapNow && hitTest(pick.tapNow.x, pick.tapNow.y)) {
      st.omega = clamp(st.omega + 3.4, -10, 10)
      st.pulse = 1
      pick.tapUsed = true
    }

    // --- motion
    st.hover += ((hit || grabbed ? 1 : 0) - st.hover) * (1 - Math.exp(-7 * dt))
    // the frame in which the button is let go still counts the last bit of movement, so a flick is not lost on a slow frame
    const dragging = grabbed || st.wasGrabbed
    st.wasGrabbed = grabbed
    if (dragging) {
      const turned = pick.fdx * 0.0095
      st.angle += turned
      // the speed of the hand over the real time that passed (not the clamped step), so slow frames do not exaggerate it
      st.omega += (turned / Math.min(Math.max(dtRaw, 1e-3), 0.5) - st.omega) * (1 - Math.exp(-16 * dt))
      st.omega = clamp(st.omega, -10, 10)
      st.tilt = clamp(st.tilt - pick.fdy * 0.0028, -0.45, 0.45)
    } else if (!world.reduced) {
      const idle = IDLE * (1 + st.hover * 1.4)
      st.omega = clamp(st.omega + (idle - st.omega) * (1 - Math.exp(-0.8 * dt)), -10, 10)
      st.angle += st.omega * dt
      st.tilt += (0 - st.tilt) * (1 - Math.exp(-1.6 * dt))
    }
    if (!world.reduced) st.moon += dt * (0.14 + 0.1 * st.hover + Math.abs(st.omega) * 0.04)
    st.pulse = Math.max(0, st.pulse - dt * 1.1)
    built.body.rotation.y = st.angle
    built.tilt.rotation.x = BASE_TILT.x + st.tilt
    built.pivot.rotation.y = st.moon

    // --- light and colour (drawn from the theme, so the planet matches the page)
    built.tilt.updateWorldMatrix(true, false)
    const { u, colours } = built.m
    u.uCenter.value.setFromMatrixPosition(built.tilt.matrixWorld)
    u.uRingN.value.set(0, 1, 0).transformDirection(built.tilt.matrixWorld)
    u.uHover.value = st.hover
    u.uPulse.value = st.pulse
    u.uOpacity.value = vis
    colours.uColA.value.copy(palette.accent).multiplyScalar(0.42)
    colours.uColB.value.copy(palette.accent).lerp(tints.white, 0.5)
    colours.uColC.value.copy(palette.accent2).multiplyScalar(0.95)
    colours.uInner.value.copy(palette.accent).lerp(tints.white, 0.62)
    colours.uOuter.value.copy(palette.accent2).lerp(tints.white, 0.3)
    u.uAtmo.value.copy(palette.accent).lerp(tints.white, 0.25)
    built.glowMat.uniforms.uOpacity.value = (0.34 + 0.22 * st.hover) * vis
    built.orbitMat.uniforms.uOpacity.value = 0.3 * vis * (1 + st.hover * 0.8)
  })

  return <primitive object={built.root} />
}
