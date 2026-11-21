import { useEffect, useMemo, useState } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { rng } from '../../lib/rand'
import { CONSTELLATIONS } from './constellations'
import { alongPath, filmPath, smooth } from './film'
import { PLANET } from './journey'
import { glowMaterial, ribbonMaterial, ribbonsGeometry, starsMaterial, sunMaterial } from './materials'
import { palette } from './palette'
import { planetMaterials } from './planetMaterials'
import { world } from './state'

// The props of the opening film: things that are only there while the camera flies in (see film.ts), and are gone before the
// landing page opens, so the hero looks exactly as it always did.
//  - a great zodiac wheel, centred on the hand and in front of it. Its twelve signs are drawn one after another around the hand
//    as it lights up, then the camera flies through the middle of the wheel and the signs sweep out past the edges of the screen
//  - a ringed planet far behind (the sun, in Golden Hour), rising in the upper left
//  - a tube of stars along the camera's path, so the flight has depth
//  - a soft glow behind the wheel and behind the planet
// None of it exists on a visit without a film (reduced motion, or already inside): FilmSet then renders nothing at all.

const TAU = Math.PI * 2
const SECTOR = TAU / 12

/** where the props sit and how big they are (the camera's path itself is in film.ts); times are film seconds */
const SET = {
  // `at`: how far along the camera's path the wheel stands (the camera flies through it). On a phone the camera hardly moves (the
  // hero hand is already close to the size of the loader's), so there the wheel simply stands `behind` the hand instead
  wheel: { at: 0.64, behind: 3.5, radius: 3.2, scale: 1.5, tilt: [0.22, -0.14] as const, spin: 0.2, first: 0.7, gap: 0.085, reveal: 0.75 },
  // up and to the left behind the hand; on a phone smaller and low on the left, where the screen is empty until the page opens
  planet: {
    offset: [-10, 4.2, -15] as const,
    scale: 1.8,
    narrow: { offset: [-3.8, -6.6, -15] as const, scale: 1.05 },
    tilt: [0.42, 0.3] as const,
    from: 1.5,
    over: 1.7,
  },
  stars: { count: 340, from: 0.9, over: 1.3 },
  glow: { from: 0.6, over: 1.4 },
}

type Disposable = { dispose(): void }

const planetWhite = new THREE.Color(1, 1, 1)

function buildWheel() {
  const root = new THREE.Group()
  const spinner = new THREE.Group()
  root.add(spinner)
  const disposables: Disposable[] = []

  const signs = CONSTELLATIONS.map((c, i) => {
    const group = new THREE.Group()
    // the first sign sits just right of the top, the rest follow clockwise; each one stands with its "up" pointing outwards
    const phi = Math.PI / 2 - (i + 0.5) * SECTOR
    group.rotation.z = phi - Math.PI / 2

    const chains = c.lines.map((chain) => chain.map((k) => new THREE.Vector3(c.stars[k][0], c.stars[k][1], 0)))
    const lineGeometry = ribbonsGeometry(chains)
    const lineMaterial = ribbonMaterial({
      width: 0.03,
      opacity: 0,
      colorA: palette.lineA,
      colorB: palette.lineB,
      glow: 0.6,
      core: 0.45,
      pulse: 1,
      pulseFreq: 1.2,
      pulseSpeed: 0.45,
      fogNear: 40,
      fogFar: 90,
      draw: 0,
    })
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
    const starMaterial = starsMaterial(20)
    starMaterial.uniforms.uOpacity.value = 0
    const points = new THREE.Points(starGeometry, starMaterial)
    points.frustumCulled = false

    group.add(lines, points)
    spinner.add(group)
    disposables.push(lineGeometry, lineMaterial, starGeometry, starMaterial)
    return { group, phi, lineMaterial, starMaterial }
  })
  return { root, spinner, signs, disposables }
}

function buildPlanet(s: number) {
  const m = planetMaterials()
  const disposables: Disposable[] = [m.body, m.ring, m.moon]
  const root = new THREE.Group()

  const glowMat = glowMaterial(0)
  glowMat.uniforms.uColorA = { value: palette.accent }
  glowMat.uniforms.uColorB = { value: palette.accent }
  const glowGeo = new THREE.PlaneGeometry(PLANET.radius * s * 7, PLANET.radius * s * 7)
  const glow = new THREE.Mesh(glowGeo, glowMat)
  glow.position.z = -PLANET.radius * s * 0.9
  glow.renderOrder = 0

  const tilt = new THREE.Group()
  tilt.rotation.set(SET.planet.tilt[0], 0, SET.planet.tilt[1])
  const bodyGeo = new THREE.SphereGeometry(PLANET.radius * s, 56, 36)
  const body = new THREE.Mesh(bodyGeo, m.body)
  body.renderOrder = 1
  const ringGeo = new THREE.RingGeometry(PLANET.ring[0] * s, PLANET.ring[1] * s, 128, 2)
  const ring = new THREE.Mesh(ringGeo, m.ring)
  ring.rotation.x = -Math.PI / 2
  ring.renderOrder = 3
  tilt.add(body, ring)
  root.add(glow, tilt)

  // the ring and the planet shade each other in world units, so the shader is told the sizes it really has
  m.u.uRing.value.set(PLANET.ring[0] * s, PLANET.ring[1] * s)
  m.u.uPlanetR.value = PLANET.radius * s

  // in Golden Hour there is a sun instead
  const sunMat = sunMaterial()
  const sunGeo = new THREE.PlaneGeometry(PLANET.radius * s * 4.2, PLANET.radius * s * 4.2)
  const sun = new THREE.Mesh(sunGeo, sunMat)
  root.add(sun)

  disposables.push(glowMat, glowGeo, bodyGeo, ringGeo, sunMat, sunGeo)
  return { root, tilt, body, glow, glowMat, sunMat, sun, m, dispose: () => disposables.forEach((d) => d.dispose()) }
}

function buildStars(count: number) {
  const rand = rng(20261110)
  const seeds = Array.from({ length: count }, () => ({ f: 0.08 + rand() * 0.87, r: 2.6 + 6.5 * Math.sqrt(rand()), th: rand() * TAU }))
  const pos = new Float32Array(count * 3)
  const size = new Float32Array(count)
  seeds.forEach((_s, i) => {
    size[i] = (rand() < 0.1 ? 1.5 : 0.5) + rand() * 0.7
  })
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  geometry.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
  const material = starsMaterial(15)
  material.uniforms.uOpacity.value = 0
  const points = new THREE.Points(geometry, material)
  points.frustumCulled = false
  return {
    points,
    geometry,
    material,
    seeds,
    dispose: () => {
      geometry.dispose()
      material.dispose()
    },
  }
}

function build() {
  const wheel = buildWheel()
  const planetScale = world.narrow ? SET.planet.narrow.scale : SET.planet.scale
  const planet = buildPlanet(planetScale)
  const stars = buildStars(world.narrow ? 200 : SET.stars.count)
  const wheelGlowMat = glowMaterial(0)
  wheelGlowMat.uniforms.uColorA = { value: palette.accent }
  wheelGlowMat.uniforms.uColorB = { value: palette.accent2 }
  const wheelGlowGeo = new THREE.PlaneGeometry(1, 1)
  const wheelGlow = new THREE.Mesh(wheelGlowGeo, wheelGlowMat)
  wheelGlow.renderOrder = 0

  const root = new THREE.Group()
  root.add(wheel.root, planet.root, stars.points, wheelGlow)
  return {
    root,
    wheel,
    planet,
    planetScale,
    stars,
    wheelGlow,
    wheelGlowMat,
    layoutKey: '',
    dispose: () => {
      wheel.disposables.forEach((d) => d.dispose())
      planet.dispose()
      stars.dispose()
      wheelGlowGeo.dispose()
      wheelGlowMat.dispose()
    },
  }
}

function FilmProps() {
  const gl = useThree((s) => s.gl)
  const scene = useThree((s) => s.scene)
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const built = useMemo(() => build(), [])
  useEffect(
    () => () => {
      built.dispose()
      world.film.mask.length = 0
    },
    [built],
  )
  // compile the props' shaders now, behind the loader, so nothing stalls the film the first time one of them comes into view
  useEffect(() => {
    gl.compile(scene, camera)
  }, [gl, scene, camera, built])

  const tmp = useMemo(() => ({ v: new THREE.Vector3(), c: new THREE.Vector3(), r: new THREE.Vector3() }), [])

  useFrame((state) => {
    const film = world.film
    const clock = film.clock
    const props = film.props
    const { wheel, planet, stars } = built

    // ---- where everything sits (again whenever the window or the hand's size changes)
    const key = `${state.size.width}|${state.size.height}|${camera.fov}|${world.narrow}|${film.handPx}`
    if (key !== built.layoutKey) {
      built.layoutKey = key
      const path = filmPath(state.size.height, camera.fov, world.narrow, film.handPx)
      const [h0x, h0y] = path.h0
      const z = world.narrow ? path.h0[2] - SET.wheel.behind : path.p0[2] + (path.rest[2] - path.p0[2]) * SET.wheel.at
      // the wheel is as big as fits the screen as seen from the start (a phone is narrow)
      const dist = path.p0[2] - z
      const halfH = dist * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
      const aspect = state.size.width / Math.max(1, state.size.height)
      const R = Math.min(SET.wheel.radius, 0.74 * halfH, 0.78 * halfH * aspect)
      wheel.root.position.set(h0x, h0y, z)
      wheel.root.rotation.set(SET.wheel.tilt[0], SET.wheel.tilt[1], 0)
      wheel.signs.forEach((s) => {
        s.group.position.set(Math.cos(s.phi) * R, Math.sin(s.phi) * R, 0)
        s.group.scale.setScalar((R / SET.wheel.radius) * SET.wheel.scale)
      })
      built.wheelGlow.position.set(h0x, h0y, z - 1.5)
      built.wheelGlow.scale.setScalar(R * 5.2)
      const at = world.narrow ? SET.planet.narrow.offset : SET.planet.offset
      planet.root.position.set(h0x + at[0], h0y + at[1], at[2])
      const attr = stars.geometry.getAttribute('position') as THREE.BufferAttribute
      stars.seeds.forEach((s, i) => {
        const c = alongPath(path, s.f)
        attr.setXYZ(i, c[0] + Math.cos(s.th) * s.r, c[1] + Math.sin(s.th) * s.r, c[2])
      })
      attr.needsUpdate = true
    }

    // ---- the zodiac wheel: its signs are drawn in turn around the hand, the wheel turns, and each sign dims as the camera passes close
    wheel.spinner.rotation.z = -clock * SET.wheel.spin
    wheel.root.updateWorldMatrix(true, true)
    wheel.signs.forEach((s, i) => {
      const a = smooth((clock - (SET.wheel.first + SET.wheel.gap * i)) / SET.wheel.reveal)
      s.group.getWorldPosition(tmp.v)
      const near = smooth((tmp.v.distanceTo(camera.position) - 2) / 4.5)
      const vis = a * near * props
      const lu = s.lineMaterial.uniforms
      lu.uDraw.value = a
      lu.uOpacity.value = 0.9 * vis
      const su = s.starMaterial.uniforms
      su.uOpacity.value = vis
      su.uDark.value = palette.dark
    })
    wheel.root.visible = props > 0.002 && clock > SET.wheel.first - 0.05

    // ---- the glow behind the wheel (it thins out as the camera comes up to it: flying through it must not haze the whole screen)
    const glow = smooth((clock - SET.glow.from) / SET.glow.over) * props * smooth((camera.position.distanceTo(built.wheelGlow.position) - 3) / 7)
    built.wheelGlowMat.uniforms.uOpacity.value = 0.2 * glow
    built.wheelGlow.visible = glow > 0.003

    // ---- the planet (Night Sky) or the sun (Golden Hour), far behind and to the upper left
    const rise = smooth((clock - SET.planet.from) / SET.planet.over) * props
    const dark = palette.dark
    const vis = rise * dark
    planet.root.visible = rise > 0.003
    planet.body.visible = vis > 0.003
    planet.tilt.visible = vis > 0.003
    planet.glowMat.uniforms.uOpacity.value = 0.34 * vis
    planet.glow.visible = vis > 0.003
    planet.sun.visible = rise * (1 - dark) > 0.003
    planet.sunMat.uniforms.uDark.value = dark
    planet.sunMat.uniforms.uOpacity.value = rise * (1 - dark) * 0.9
    if (vis > 0.003) {
      planet.body.rotation.y = 0.8 + state.clock.elapsedTime * 0.07
      planet.tilt.updateWorldMatrix(true, false)
      const { u, colours } = planet.m
      u.uCenter.value.setFromMatrixPosition(planet.tilt.matrixWorld)
      u.uRingN.value.set(0, 1, 0).transformDirection(planet.tilt.matrixWorld)
      u.uOpacity.value = vis
      colours.uColA.value.copy(palette.accent).multiplyScalar(0.42)
      colours.uColB.value.copy(palette.accent).lerp(planetWhite, 0.5)
      colours.uColC.value.copy(palette.accent2).multiplyScalar(0.95)
      colours.uInner.value.copy(palette.accent).lerp(planetWhite, 0.62)
      colours.uOuter.value.copy(palette.accent2).lerp(planetWhite, 0.3)
      u.uAtmo.value.copy(palette.accent).lerp(planetWhite, 0.25)

      // where it is on the screen: the streaks of the flight pass behind it (see state.ts)
      const mk = film.mask
      mk.length = 0
      const w = state.size.width
      const h = state.size.height
      tmp.c.setFromMatrixPosition(planet.tilt.matrixWorld)
      tmp.r
        .setFromMatrixColumn(camera.matrixWorld, 0)
        .multiplyScalar(PLANET.radius * built.planetScale)
        .add(tmp.c)
      tmp.c.project(camera)
      tmp.r.project(camera)
      mk.push(vis, (tmp.c.x * 0.5 + 0.5) * w, (-tmp.c.y * 0.5 + 0.5) * h, Math.hypot((tmp.r.x - tmp.c.x) * 0.5 * w, (tmp.r.y - tmp.c.y) * 0.5 * h) + 2)
      const ringOuter = PLANET.ring[1] * built.planetScale
      for (let k = 0; k < 40; k++) {
        const a = (k / 40) * TAU
        tmp.v.set(Math.cos(a) * ringOuter, 0, Math.sin(a) * ringOuter).applyMatrix4(planet.tilt.matrixWorld).project(camera)
        mk.push((tmp.v.x * 0.5 + 0.5) * w, (-tmp.v.y * 0.5 + 0.5) * h)
      }
    } else {
      film.mask.length = 0
    }

    // ---- the stars along the way
    const starsOn = smooth((clock - SET.stars.from) / SET.stars.over) * props
    stars.material.uniforms.uOpacity.value = 0.85 * starsOn
    stars.material.uniforms.uDark.value = palette.dark
    stars.points.visible = starsOn > 0.003
  })

  return <primitive object={built.root} />
}

/** The film's props: mounted only while there is a film, and dropped (and freed) the moment it is over. */
export default function FilmSet() {
  const [alive, setAlive] = useState(() => world.film.on)
  useFrame(() => {
    if (alive && !world.film.on) setAlive(false)
  })
  return alive ? <FilmProps /> : null
}
