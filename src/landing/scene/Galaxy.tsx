import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { rng } from '../../lib/rand'
import { SAFE_GLSL, safeUniforms, shared } from './materials'
import { palette } from './palette'
import { pick } from './pick'
import { world } from './state'

// A spiral galaxy that hangs in the night sky behind the hero hand (Night Sky only: the Golden Hour dawn has none).
// It is thousands of tiny stars on three arms plus a few large, faint clouds for the glow between them.
//  - it turns slowly, and a little faster while the page is being scrolled
//  - it leans a touch towards the mouse, and the stars under the mouse wake up: they grow and brighten
//  - it fades out as the camera dives into the palm, so it never gets in the way of the flight past the two hands

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a))
  return t * t * (3 - 2 * t)
}

const GALAXY = {
  wide: { pos: [5.6, 2.45, -10] as const, radius: 6.6 },
  narrow: { pos: [1.8, 3.0, -10] as const, radius: 5 },
  /** how far the disc is tipped away from the viewer, and how far it is rolled in the screen plane */
  tilt: 1.02,
  roll: 0.44,
}

function galaxyGeometry(stars: number, clouds: number, R: number): THREE.BufferGeometry {
  const rand = rng(20261108)
  const gauss = () => Math.sqrt(-2 * Math.log(Math.max(1e-6, rand()))) * Math.cos(2 * Math.PI * rand())
  const n = stars + clouds
  const pos = new Float32Array(n * 3)
  const colour = new Float32Array(n * 3)
  const size = new Float32Array(n)
  const seed = new Float32Array(n)

  const ARMS = 3
  const TWIST = 4.4
  const core = new THREE.Color('#FFE7B4')
  const mid = new THREE.Color('#B8A5FF')
  const rim = new THREE.Color('#6E9CFF')
  const pink = new THREE.Color('#FF9CCB')
  const teal = new THREE.Color('#62D6C9')
  const c = new THREE.Color()

  // density falls off with distance from the heart (a gamma distribution in radius), kept inside the disc
  const radius = (scale: number) => {
    for (;;) {
      const r = -scale * (Math.log(Math.max(1e-6, rand())) + Math.log(Math.max(1e-6, rand())))
      if (r < 1) return r
    }
  }

  for (let i = 0; i < n; i++) {
    const cloud = i >= stars
    let u: number // 0 at the heart, 1 at the rim
    let theta: number
    let z: number
    const arm = Math.floor(rand() * ARMS)
    if (cloud) {
      u = 0.14 + 0.66 * rand()
      theta = (arm / ARMS) * Math.PI * 2 + u * TWIST + gauss() * 0.16
      z = gauss() * 0.01 * R
    } else if (rand() < 0.13) {
      // the round, bright heart
      u = Math.abs(gauss()) * 0.09
      theta = rand() * Math.PI * 2
      z = gauss() * 0.04 * R * (1 - Math.min(1, u * 5))
    } else if (rand() < 0.22) {
      // stars scattered through the disc between the arms
      u = radius(0.22)
      theta = rand() * Math.PI * 2
      z = gauss() * 0.02 * R
    } else {
      u = radius(0.2)
      theta = (arm / ARMS) * Math.PI * 2 + u * TWIST + gauss() * (0.1 + 0.3 * u)
      z = gauss() * 0.018 * R * (1.1 - u)
    }
    const r = u * R
    pos[i * 3] = Math.cos(theta) * r
    pos[i * 3 + 1] = Math.sin(theta) * r
    pos[i * 3 + 2] = z

    // gold at the heart, lavender through the middle, blue at the rim; a few pink star nurseries along the arms
    if (u < 0.3) c.copy(core).lerp(mid, smoothstep(0.04, 0.3, u))
    else c.copy(mid).lerp(rim, smoothstep(0.3, 0.95, u))
    if (!cloud && u > 0.25 && u < 0.85 && rand() < 0.07) c.copy(pink)
    else if (!cloud && u > 0.4 && rand() < 0.05) c.copy(teal)
    if (cloud) c.lerp(rand() < 0.5 ? pink : rim, 0.35)
    colour[i * 3] = c.r
    colour[i * 3 + 1] = c.g
    colour[i * 3 + 2] = c.b

    size[i] = cloud ? 22 + rand() * 20 : 0.5 + 2.6 * Math.pow(rand(), 5)
    seed[i] = rand()
  }

  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  g.setAttribute('aColor', new THREE.BufferAttribute(colour, 3))
  g.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
  g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1))
  return g
}

const VERT = /* glsl */ `
attribute float aSize;
attribute vec3 aColor;
attribute float aSeed;
uniform float uTime;
uniform float uPixelRatio;
uniform float uScale;
uniform float uAspect;
uniform vec3 uPtr;
varying vec3 vColor;
varying float vGlow;
varying float vTwinkle;
varying float vCloud;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vec4 clip = projectionMatrix * mv;
  gl_Position = clip;
  float cloud = step(8.0, aSize);
  // stars close to the pointer (in screen space) wake up
  vec2 d = (clip.xy / clip.w - uPtr.xy) * vec2(uAspect, 1.0);
  float near = uPtr.z * smoothstep(0.3, 0.0, length(d)) * (1.0 - cloud);
  vTwinkle = mix(0.68 + 0.32 * sin(uTime * (0.7 + aSeed * 2.6) + aSeed * 61.0), 1.0, cloud);
  vGlow = near;
  vCloud = cloud;
  vColor = aColor;
  float k = 10.0 / max(1.0, -mv.z);
  gl_PointSize = aSize * uScale * uPixelRatio * k * (1.0 + near * 0.9);
}
`

const FRAG = /* glsl */ `${SAFE_GLSL}
uniform float uOpacity;
varying vec3 vColor;
varying float vGlow;
varying float vTwinkle;
varying float vCloud;
void main() {
  float r = length(gl_PointCoord - 0.5) * 2.0;
  if (r > 1.0) discard;
  float core = 1.0 - smoothstep(0.0, 0.5, r);
  float halo = pow(1.0 - r, 2.4);
  float star = (core * 0.85 + halo * 0.5) * vTwinkle;
  float cloud = pow(1.0 - r, 2.0) * 0.07;
  float a = mix(star, cloud, vCloud);
  vec3 c = mix(vColor, vec3(1.0), (core * 0.45 + vGlow * 0.3) * (1.0 - vCloud));
  gl_FragColor = vec4(c, a * uOpacity * (1.0 + vGlow * 0.75) * safeFade());
}
`

function galaxyMaterial(scale: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      ...safeUniforms(),
      uTime: shared.time,
      uPixelRatio: shared.pixelRatio,
      uScale: { value: scale },
      uAspect: { value: 1.6 },
      uOpacity: { value: 0 },
      uPtr: { value: new THREE.Vector3(9, 9, 0) },
    },
  })
}

export default function Galaxy({ narrow }: { narrow: boolean }) {
  const camera = useThree((s) => s.camera)
  const spec = narrow ? GALAXY.narrow : GALAXY.wide
  const built = useMemo(
    () => ({
      geometry: galaxyGeometry(narrow ? 2600 : 6800, narrow ? 70 : 170, spec.radius),
      material: galaxyMaterial(narrow ? 4.2 : 5),
    }),
    [narrow, spec.radius],
  )
  useEffect(
    () => () => {
      built.geometry.dispose()
      built.material.dispose()
    },
    [built],
  )

  const outer = useRef<THREE.Group>(null)
  const roll = useRef<THREE.Group>(null)
  const tilt = useRef<THREE.Group>(null)
  const spin = useRef<THREE.Group>(null)
  const st = useMemo(() => ({ angle: 0.6, boost: 0, lastY: 0, ptr: 0, leanX: 0, leanY: 0 }), [])

  useFrame((state, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1)
    const u = built.material.uniforms
    // only in the Night Sky, and gone once the camera has dived into the palm; it comes up out of the dark during the opening film
    const fade = palette.dark * smoothstep(1.0, 4.5, camera.position.z) * world.film.sky
    u.uOpacity.value = 0.82 * fade
    if (outer.current) outer.current.visible = fade > 0.004
    if (fade <= 0.004) return

    if (!world.reduced) {
      // a slow turn that picks up while the page is scrolled
      const speed = Math.abs(world.scrollY - st.lastY) / Math.max(dt, 1e-3)
      st.lastY = world.scrollY
      st.boost += (Math.min(speed / 2400, 1) - st.boost) * (1 - Math.exp(-4 * dt))
      // (and it whirls while the camera races through the opening film)
      st.angle += dt * (0.028 + 0.2 * st.boost + 0.5 * world.film.speed)

      // lean towards the mouse
      const k = 1 - Math.exp(-2.2 * dt)
      st.leanX += (world.pointer.x * 0.1 - st.leanX) * k
      st.leanY += (world.pointer.y * 0.07 - st.leanY) * k

      // stars near the pointer light up
      const want = pick.inside && pick.open && !pick.touch ? 1 : 0
      st.ptr += (want - st.ptr) * (1 - Math.exp(-5 * dt))
      u.uPtr.value.set(pick.nx, pick.ny, st.ptr)
    }
    u.uAspect.value = state.size.width / Math.max(1, state.size.height)

    if (outer.current) outer.current.rotation.y = st.leanX
    if (roll.current) roll.current.rotation.z = GALAXY.roll
    if (tilt.current) tilt.current.rotation.x = -GALAXY.tilt + st.leanY
    if (spin.current) spin.current.rotation.z = st.angle
  })

  return (
    <group ref={outer} position={[spec.pos[0], spec.pos[1], spec.pos[2]]} visible={false}>
      <group ref={roll}>
        <group ref={tilt}>
          <group ref={spin}>
            <points geometry={built.geometry} material={built.material} frustumCulled={false} renderOrder={-5} />
          </group>
        </group>
      </group>
    </group>
  )
}
