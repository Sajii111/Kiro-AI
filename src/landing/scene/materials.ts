import * as THREE from 'three'
import { palette } from './palette'
import { rng } from '../../lib/rand'

// All the shader code for the landing scene lives here.
//  - ribbons: flat strips that always face the camera, with a soft glow, draw-in and travelling pulses
//  - particles: soft round dots that rise and sway
//  - dots: individually coloured markers (the feature nodes)
//  - glow / sun: simple gradient discs

export const shared = {
  time: { value: 0 },
  pixelRatio: { value: 1 },
  /** drawing-buffer size in device pixels */
  res: { value: new THREE.Vector2(1, 1) },
  /** text-safe fade: (axis x, axis y, ramp start, ramp end) in 0..1 screen coordinates */
  safe: { value: new THREE.Vector4(1, 0, 0.1, 0.62) },
  /** how transparent lines become over the text side of the screen (1 = no change) */
  safeMin: { value: 0.3 },
  /** the cursor's "lamp": x, y and radius in drawing-buffer pixels (origin bottom left) and strength 0..1 */
  lamp: { value: new THREE.Vector4(0, 0, 1, 0) },
}

// Lines and dust get quieter over the side of the screen where the text sits (the left on desktop,
// the bottom on phones), so words stay easy to read while the scene stays rich where there is room.
export const SAFE_GLSL = /* glsl */ `
uniform vec2 uRes;
uniform vec4 uSafe;
uniform float uSafeMin;
float safeFade() {
  float t = dot(gl_FragCoord.xy / uRes, uSafe.xy);
  return mix(uSafeMin, 1.0, smoothstep(uSafe.z, uSafe.w, t));
}
`
export const safeUniforms = () => ({ uRes: shared.res, uSafe: shared.safe, uSafeMin: shared.safeMin })

// ------------------------------------------------------------------ ribbons

/** Several separate strips merged into one geometry (one draw call), each built like ribbonGeometry. */
export function ribbonsGeometry(lines: THREE.Vector3[][], closed = false): THREE.BufferGeometry {
  const strips = lines.filter((l) => l.length >= 2)
  const total = strips.reduce((a, l) => a + l.length, 0)
  const pos = new Float32Array(total * 6)
  const tan = new Float32Array(total * 6)
  const side = new Float32Array(total * 2)
  const along = new Float32Array(total * 2)
  const index = new Uint32Array(strips.reduce((a, l) => a + (l.length - 1) * 6, 0))
  const t = new THREE.Vector3()
  let base = 0 // first vertex of the current strip
  let at = 0 // write position in the index array
  for (const points of strips) {
    const n = points.length
    const lens: number[] = Array.from({ length: n }, () => 0)
    for (let i = 1; i < n; i++) lens[i] = lens[i - 1] + points[i].distanceTo(points[i - 1])
    const length = lens[n - 1] || 1
    for (let i = 0; i < n; i++) {
      const prev = points[closed ? (i - 1 + n) % n : Math.max(0, i - 1)]
      const next = points[closed ? (i + 1) % n : Math.min(n - 1, i + 1)]
      t.subVectors(next, prev).normalize()
      const p = points[i]
      for (let s = 0; s < 2; s++) {
        const k = base + i * 2 + s
        pos[k * 3] = p.x
        pos[k * 3 + 1] = p.y
        pos[k * 3 + 2] = p.z
        tan[k * 3] = t.x
        tan[k * 3 + 1] = t.y
        tan[k * 3 + 2] = t.z
        side[k] = s === 0 ? -1 : 1
        along[k] = lens[i] / length
      }
    }
    for (let i = 0; i < n - 1; i++) {
      const a = base + i * 2
      index.set([a, a + 1, a + 2, a + 1, a + 3, a + 2], at)
      at += 6
    }
    base += n * 2
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  g.setAttribute('aTangent', new THREE.BufferAttribute(tan, 3))
  g.setAttribute('aSide', new THREE.BufferAttribute(side, 1))
  g.setAttribute('aAlong', new THREE.BufferAttribute(along, 1))
  g.setIndex(new THREE.BufferAttribute(index, 1))
  g.computeBoundingSphere()
  return g
}

/** A strip of two vertices per point; the shader pushes them apart sideways to make a line. */
export function ribbonGeometry(points: THREE.Vector3[], closed = false): THREE.BufferGeometry {
  return ribbonsGeometry([points], closed)
}

const RIBBON_VERT = /* glsl */ `
attribute vec3 aTangent;
attribute float aSide;
attribute float aAlong;
uniform float uWidth;
uniform float uBoost;
uniform float uClosed;
varying float vAlong;
varying float vSide;
varying float vDist;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vec3 tn = normalize(mat3(modelMatrix) * aTangent);
  vec3 toCam = cameraPosition - wp.xyz;
  vec3 cr = cross(tn, toCam);
  vec3 sideDir = length(cr) > 1e-5 ? normalize(cr) : vec3(1.0, 0.0, 0.0);
  float edge = uClosed > 0.5 ? 1.0 : smoothstep(0.0, 0.05, aAlong) * smoothstep(1.0, 0.95, aAlong);
  float w = uWidth * uBoost * mix(0.2, 1.0, edge);
  wp.xyz += sideDir * aSide * w * 0.5;
  vAlong = aAlong;
  vSide = aSide;
  vDist = length(toCam);
  gl_Position = projectionMatrix * viewMatrix * wp;
}
`

const RIBBON_FRAG = /* glsl */ `${SAFE_GLSL}
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform vec3 uHot;
uniform float uTime;
uniform float uOpacity;
uniform float uDraw;
uniform float uGlow;
uniform float uCore;
uniform float uPulse;
uniform float uPulseFreq;
uniform float uPulseSpeed;
uniform float uDash;
uniform float uDuty;
uniform float uFogNear;
uniform float uFogFar;
uniform vec4 uLamp;
varying float vAlong;
varying float vSide;
varying float vDist;
void main() {
  if (vAlong > uDraw) discard;
  float d = abs(vSide);
  float core = 1.0 - smoothstep(uCore * 0.55, uCore, d);
  float halo = pow(max(0.0, 1.0 - d), 2.2) * uGlow;
  float a = max(core, halo);
  if (uDash > 0.0) {
    float dd = fract(vAlong * uDash - uTime * 0.04);
    a *= smoothstep(0.0, 0.06, dd) * smoothstep(uDuty + 0.06, uDuty, dd);
  }
  float head = uDraw < 0.999 ? smoothstep(0.07, 0.0, uDraw - vAlong) : 0.0;
  float ph = fract(vAlong * uPulseFreq - uTime * uPulseSpeed);
  float pulse = smoothstep(0.0, 0.1, ph) * smoothstep(0.34, 0.1, ph) * uPulse;
  // the cursor acts like a small lamp: any line close to it brightens and warms
  float lamp = uLamp.w * smoothstep(uLamp.z, 0.0, distance(gl_FragCoord.xy, uLamp.xy));
  vec3 col = mix(uColorA, uColorB, vAlong);
  col = mix(col, uHot, clamp(pulse + head + lamp * 0.55, 0.0, 1.0));
  float fog = 1.0 - smoothstep(uFogNear, uFogFar, vDist);
  float alpha = a * uOpacity * fog * safeFade() * (1.0 + pulse * 0.5 + head * 0.8 + lamp * 1.3);
  gl_FragColor = vec4(col, clamp(alpha, 0.0, 1.0));
}
`

export type RibbonStyle = {
  /** width in world units */
  width: number
  opacity?: number
  colorA?: THREE.Color
  colorB?: THREE.Color
  hot?: THREE.Color
  /** halo strength 0..1 */
  glow?: number
  /** how much of the width is the crisp centre, 0..1 */
  core?: number
  pulse?: number
  pulseFreq?: number
  pulseSpeed?: number
  /** dashes along the stroke, 0 = solid */
  dash?: number
  duty?: number
  closed?: boolean
  fogNear?: number
  fogFar?: number
  draw?: number
  /** a uniform shared with other things that multiplies the width (the opening film widens the hero hand's lines with it) */
  boost?: { value: number }
}

export function ribbonMaterial(s: RibbonStyle): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: RIBBON_VERT,
    fragmentShader: RIBBON_FRAG,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: {
      ...safeUniforms(),
      uTime: shared.time,
      uWidth: { value: s.width },
      uBoost: s.boost ?? { value: 1 },
      uClosed: { value: s.closed ? 1 : 0 },
      uOpacity: { value: s.opacity ?? 1 },
      uDraw: { value: s.draw ?? 1 },
      uColorA: { value: s.colorA ?? palette.ink },
      uColorB: { value: s.colorB ?? s.colorA ?? palette.ink },
      uHot: { value: s.hot ?? palette.hot },
      uGlow: { value: s.glow ?? 0.5 },
      uCore: { value: s.core ?? 0.42 },
      uPulse: { value: s.pulse ?? 0 },
      uPulseFreq: { value: s.pulseFreq ?? 2 },
      uPulseSpeed: { value: s.pulseSpeed ?? 0.18 },
      uDash: { value: s.dash ?? 0 },
      uDuty: { value: s.duty ?? 0.5 },
      uFogNear: { value: s.fogNear ?? 28 },
      uFogFar: { value: s.fogFar ?? 62 },
      uLamp: shared.lamp,
    },
  })
}

// ------------------------------------------------------------------ particles

const PARTICLE_VERT = /* glsl */ `
attribute vec3 aSeed;
attribute float aSize;
uniform float uTime;
uniform float uPixelRatio;
uniform float uSize;
uniform float uRise;
uniform float uSway;
uniform float uSpeed;
varying float vAlpha;
varying float vMix;
varying float vDist;
void main() {
  float life = fract(aSeed.x + uTime * uSpeed * (0.35 + aSeed.y * 0.65));
  vec3 p = position;
  p.y += life * uRise;
  p.x += sin(uTime * 0.5 + aSeed.z * 6.2831) * uSway * (0.3 + aSeed.y);
  p.z += cos(uTime * 0.4 + aSeed.x * 6.2831) * uSway;
  vAlpha = smoothstep(0.0, 0.12, life) * smoothstep(1.0, 0.55, life);
  vMix = aSeed.z;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vDist = -mv.z;
  gl_Position = projectionMatrix * mv;
  gl_PointSize = min(aSize * uSize * uPixelRatio * (8.0 / max(0.6, -mv.z)), 40.0 * uPixelRatio);
}
`

const PARTICLE_FRAG = /* glsl */ `${SAFE_GLSL}
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform float uOpacity;
uniform float uFogNear;
uniform float uFogFar;
varying float vAlpha;
varying float vMix;
varying float vDist;
void main() {
  float r = length(gl_PointCoord - 0.5);
  float soft = smoothstep(0.5, 0.04, r);
  float a = soft * soft * vAlpha * uOpacity * (1.0 - smoothstep(uFogNear, uFogFar, vDist)) * safeFade();
  if (a < 0.01) discard;
  gl_FragColor = vec4(mix(uColorA, uColorB, vMix), a);
}
`

export type ParticleStyle = {
  size?: number
  opacity?: number
  rise?: number
  sway?: number
  speed?: number
  colorA?: THREE.Color
  colorB?: THREE.Color
  fogNear?: number
  fogFar?: number
}

export function particleMaterial(s: ParticleStyle = {}): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: PARTICLE_VERT,
    fragmentShader: PARTICLE_FRAG,
    transparent: true,
    depthWrite: false,
    uniforms: {
      ...safeUniforms(),
      uTime: shared.time,
      uPixelRatio: shared.pixelRatio,
      uSize: { value: s.size ?? 3 },
      uOpacity: { value: s.opacity ?? 0.9 },
      uRise: { value: s.rise ?? 0.8 },
      uSway: { value: s.sway ?? 0.05 },
      uSpeed: { value: s.speed ?? 0.12 },
      uColorA: { value: s.colorA ?? palette.accent },
      uColorB: { value: s.colorB ?? palette.accent2 },
      uFogNear: { value: s.fogNear ?? 26 },
      uFogFar: { value: s.fogFar ?? 58 },
    },
  })
}

/** n particles scattered by `place`, each with a random seed and size. */
export function particleGeometry(n: number, place: (i: number, out: THREE.Vector3) => void): THREE.BufferGeometry {
  const pos = new Float32Array(n * 3)
  const seed = new Float32Array(n * 3)
  const size = new Float32Array(n)
  const v = new THREE.Vector3()
  const rand = rng(n * 31 + 7)
  for (let i = 0; i < n; i++) {
    place(i, v)
    pos[i * 3] = v.x
    pos[i * 3 + 1] = v.y
    pos[i * 3 + 2] = v.z
    seed[i * 3] = rand()
    seed[i * 3 + 1] = rand()
    seed[i * 3 + 2] = rand()
    size[i] = 0.55 + rand() * 1.1
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 3))
  g.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
  return g
}

// ------------------------------------------------------------------ feature nodes

const DOT_VERT = /* glsl */ `
attribute vec3 aColor;
attribute float aSize;
attribute float aPulse;
uniform float uTime;
uniform float uPixelRatio;
uniform float uScale;
varying vec3 vColor;
varying float vRing;
void main() {
  vColor = aColor;
  vRing = aPulse < -0.5 ? 1.0 : 0.0;
  float beat = aPulse > 0.5 ? 1.0 + 0.35 * sin(uTime * 3.2 + position.x * 5.0) : 1.0;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * beat * uScale * uPixelRatio * (8.0 / max(0.6, -mv.z));
}
`

const DOT_FRAG = /* glsl */ `${SAFE_GLSL}
uniform float uOpacity;
varying vec3 vColor;
varying float vRing;
void main() {
  float r = length(gl_PointCoord - 0.5) * 2.0;
  float disc = 1.0 - smoothstep(0.55, 0.7, r);
  float ring = smoothstep(0.5, 0.62, r) * (1.0 - smoothstep(0.78, 0.9, r));
  float glow = pow(max(0.0, 1.0 - r), 2.0) * 0.45;
  float a = vRing > 0.5 ? ring : disc;
  a = max(a, glow);
  if (a < 0.01) discard;
  gl_FragColor = vec4(vColor, a * uOpacity * safeFade());
}
`

export function dotsMaterial(scale = 14, opacity = 1): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: DOT_VERT,
    fragmentShader: DOT_FRAG,
    transparent: true,
    depthWrite: false,
    uniforms: {
      ...safeUniforms(),
      uTime: shared.time,
      uPixelRatio: shared.pixelRatio,
      uScale: { value: scale },
      uOpacity: { value: opacity },
    },
  })
}

// ------------------------------------------------------------------ stars (the zodiac wheel)

const STAR_VERT = /* glsl */ `
attribute float aSize;
uniform float uTime;
uniform float uPixelRatio;
uniform float uScale;
varying float vTwinkle;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  vTwinkle = 0.78 + 0.22 * sin(uTime * 1.7 + position.x * 9.0 + position.y * 7.0);
  gl_PointSize = aSize * uScale * uPixelRatio * (8.0 / max(0.6, -mv.z));
}
`

const STAR_FRAG = /* glsl */ `${SAFE_GLSL}
uniform vec3 uColor;
uniform float uOpacity;
uniform float uLit;
uniform float uDark;
varying float vTwinkle;
void main() {
  vec2 q = gl_PointCoord - 0.5;
  float r = length(q) * 2.0;
  float core = 1.0 - smoothstep(0.16, 0.3, r);
  float halo = pow(max(0.0, 1.0 - r), 2.4) * (0.5 + uLit * 0.6);
  vec2 a2 = abs(q) * 2.0;
  float spike = (1.0 - smoothstep(0.0, 0.16, min(a2.x, a2.y))) * (1.0 - r) * (0.35 + uLit * 0.8);
  float a = max(max(core, halo), spike) * vTwinkle;
  if (a < 0.01) discard;
  // on the night sky a star's heart is white; on the cream dawn sky it stays amber so it can still be seen
  gl_FragColor = vec4(mix(uColor, vec3(1.0), core * 0.7 * uDark), a * uOpacity * safeFade());
}
`

export function starsMaterial(scale = 12): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: STAR_VERT,
    fragmentShader: STAR_FRAG,
    transparent: true,
    depthWrite: false,
    uniforms: {
      ...safeUniforms(),
      uTime: shared.time,
      uPixelRatio: shared.pixelRatio,
      uScale: { value: scale },
      uColor: { value: palette.lineB },
      uOpacity: { value: 0.9 },
      uLit: { value: 0 },
      uDark: { value: 1 },
    },
  })
}

// ------------------------------------------------------------------ glow + sun

const QUAD_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

const GLOW_FRAG = /* glsl */ `
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform float uOpacity;
varying vec2 vUv;
void main() {
  float r = length(vUv - 0.5) * 2.0;
  float g = pow(max(0.0, 1.0 - r), 2.2);
  vec3 col = mix(uColorB, uColorA, smoothstep(0.0, 0.85, r));
  gl_FragColor = vec4(col, g * uOpacity);
}
`

export function glowMaterial(opacity = 0.5): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: QUAD_VERT,
    fragmentShader: GLOW_FRAG,
    transparent: true,
    depthWrite: false,
    uniforms: {
      uColorA: { value: palette.accent },
      uColorB: { value: palette.accent2 },
      uOpacity: { value: opacity },
    },
  })
}

const SUN_FRAG = /* glsl */ `
uniform vec3 uTop;
uniform vec3 uBottom;
uniform vec3 uHalo;
uniform float uDark;
uniform float uOpacity;
varying vec2 vUv;
void main() {
  vec2 p = (vUv - 0.5) * 2.0;
  float r = length(p);
  float disc = 1.0 - smoothstep(0.30, 0.315, r);
  float corona = pow(max(0.0, 1.0 - r), 2.4) * 0.6;
  vec3 col = mix(uBottom, uTop, smoothstep(-0.3, 0.3, p.y));
  float bands = 1.0;
  if (p.y < 0.0) {
    float k = fract(p.y * 20.0);
    float cut = 0.18 + (-p.y) * 1.5;
    bands = mix(1.0, step(cut, k), (1.0 - uDark) * smoothstep(0.0, -0.12, p.y));
  }
  float a = disc * bands + corona * (1.0 - disc);
  vec3 outc = mix(uHalo, col, disc);
  gl_FragColor = vec4(outc, a * uOpacity);
}
`

export function sunMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: QUAD_VERT,
    fragmentShader: SUN_FRAG,
    transparent: true,
    depthWrite: false,
    uniforms: {
      uTop: { value: palette.accent2 },
      uBottom: { value: palette.accent },
      uHalo: { value: palette.accent },
      uDark: { value: 0 },
      uOpacity: { value: 1 },
    },
  })
}

// ------------------------------------------------------------------ radar sweep

const SWEEP_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uOpacity;
uniform float uTheta;
varying vec2 vUv;
void main() {
  vec2 p = vUv - 0.5;
  float u = atan(p.y, p.x) / uTheta;
  float k = clamp(u, 0.0, 1.0);
  float r = length(p) * 2.0;
  // brightest just behind the leading edge, which fades out softly instead of ending in a hard line
  float a = pow(k, 2.2) * smoothstep(1.0, 0.8, k) * (1.0 - smoothstep(0.7, 1.0, r)) * smoothstep(0.05, 0.3, r);
  gl_FragColor = vec4(uColor, a * uOpacity);
}
`

/** A wedge (use with a CircleGeometry whose thetaLength equals `theta`) that is brightest at its leading edge. */
export function sweepMaterial(theta: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: QUAD_VERT,
    fragmentShader: SWEEP_FRAG,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: {
      uColor: { value: palette.accent },
      uOpacity: { value: 0.4 },
      uTheta: { value: theta },
    },
  })
}
