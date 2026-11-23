import * as THREE from 'three'
import { PLANET } from './journey'
import { shared } from './materials'

// The shaders for the ringed planet and its moon. There are no textures: the bands, storm and craters are made
// from noise in the shader, the light comes from one direction, and the rings and the planet shade each other.

const NOISE = /* glsl */ `
float h31(vec3 p) {
  p = fract(p * 0.1031);
  p += dot(p, p.zyx + 31.32);
  return fract((p.x + p.y) * p.z);
}
float vnoise(vec3 x) {
  vec3 i = floor(x);
  vec3 f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(mix(h31(i), h31(i + vec3(1.0, 0.0, 0.0)), f.x), mix(h31(i + vec3(0.0, 1.0, 0.0)), h31(i + vec3(1.0, 1.0, 0.0)), f.x), f.y),
    mix(mix(h31(i + vec3(0.0, 0.0, 1.0)), h31(i + vec3(1.0, 0.0, 1.0)), f.x), mix(h31(i + vec3(0.0, 1.0, 1.0)), h31(i + vec3(1.0, 1.0, 1.0)), f.x), f.y),
    f.z
  );
}
float fbm(vec3 p) {
  float a = 0.5;
  float s = 0.0;
  for (int i = 0; i < 4; i++) {
    s += a * vnoise(p);
    p = p * 2.03 + 11.7;
    a *= 0.5;
  }
  return s;
}
// how solid the rings are across their width (0 = inner edge, 1 = outer edge): a faint inner ring, a dense one, a gap, an outer ring
float ringDensity(float u) {
  if (u <= 0.0 || u >= 1.0) return 0.0;
  float c = 0.3 * smoothstep(0.0, 0.1, u) * (1.0 - smoothstep(0.16, 0.2, u));
  float b = 0.95 * smoothstep(0.17, 0.23, u) * (1.0 - smoothstep(0.52, 0.58, u));
  float a = 0.72 * smoothstep(0.64, 0.68, u) * (1.0 - smoothstep(0.94, 0.995, u));
  float grooves = 0.74 + 0.26 * vnoise(vec3(u * 70.0, 0.5, 1.7)) + 0.1 * sin(u * 190.0);
  return clamp((c + b + a) * grooves, 0.0, 1.0);
}
`

const BODY_VERT = /* glsl */ `
varying vec3 vObj;
varying vec3 vNormalW;
varying vec3 vPosW;
void main() {
  vObj = position;
  vNormalW = normalize(mat3(modelMatrix) * normal);
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vPosW = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}
`

const PLANET_FRAG = /* glsl */ `${NOISE}
uniform vec3 uLight;
uniform vec3 uCenter;
uniform vec3 uRingN;
uniform vec2 uRing;
uniform vec3 uColA;
uniform vec3 uColB;
uniform vec3 uColC;
uniform vec3 uAtmo;
uniform float uTime;
uniform float uHover;
uniform float uPulse;
uniform float uOpacity;
varying vec3 vObj;
varying vec3 vNormalW;
varying vec3 vPosW;
void main() {
  vec3 q = normalize(vObj);
  float lat = q.y;
  float turb = fbm(q * vec3(2.4, 4.2, 2.4) + vec3(0.0, 3.0, uTime * 0.012));
  float b1 = 0.5 + 0.5 * sin(lat * 12.0 + turb * 3.6 + 0.4);
  float b2 = 0.5 + 0.5 * sin(lat * 31.0 + turb * 6.5);
  vec3 col = mix(uColA, uColB, smoothstep(0.2, 0.8, b1));
  col = mix(col, uColC, smoothstep(0.6, 0.95, b2) * 0.45);
  col *= 0.8 + 0.4 * fbm(q * vec3(5.0, 34.0, 5.0));
  // one large storm that rides around with the planet
  float storm = smoothstep(0.2, 0.02, distance(q, normalize(vec3(0.66, -0.3, 0.69))));
  col = mix(col, mix(uColC, uColB, 0.4) * 1.1, storm * 0.75);
  col = mix(col, uColA * 0.72, smoothstep(0.8, 1.0, abs(lat)) * 0.65);

  vec3 n = normalize(vNormalW);
  vec3 V = normalize(cameraPosition - vPosW);
  float ndl = dot(n, uLight);
  float day = smoothstep(-0.1, 0.6, ndl);
  float fres = pow(1.0 - clamp(dot(n, V), 0.0, 1.0), 3.0);

  // the rings throw a shadow across the planet
  float shadow = 0.0;
  float denom = dot(uLight, uRingN);
  if (abs(denom) > 0.02) {
    float t = dot(uCenter - vPosW, uRingN) / denom;
    if (t > 0.0) {
      float u = (length(vPosW + uLight * t - uCenter) - uRing.x) / (uRing.y - uRing.x);
      shadow = ringDensity(u);
    }
  }
  vec3 lit = col * (0.04 + 0.96 * day) * (1.0 - 0.72 * shadow);
  lit += uAtmo * fres * (0.2 + 0.85 * day) * (1.0 + uHover * 0.9);
  lit *= 1.0 + uHover * 0.1 + uPulse * 0.18;
  gl_FragColor = vec4(lit, uOpacity);
}
`

const RING_VERT = /* glsl */ `
varying vec2 vLocal;
varying vec3 vPosW;
void main() {
  vLocal = position.xy;
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vPosW = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}
`

const RING_FRAG = /* glsl */ `${NOISE}
uniform vec3 uLight;
uniform vec3 uCenter;
uniform vec3 uRingN;
uniform vec2 uRing;
uniform float uPlanetR;
uniform vec3 uInner;
uniform vec3 uOuter;
uniform float uHover;
uniform float uPulse;
uniform float uOpacity;
varying vec2 vLocal;
varying vec3 vPosW;
void main() {
  float u = (length(vLocal) - uRing.x) / (uRing.y - uRing.x);
  float d = ringDensity(u);
  if (d < 0.01) discard;
  vec3 V = normalize(cameraPosition - vPosW);
  // the face of the ring the light falls on is bright; the other face is dim and more see-through
  float lit = (dot(V, uRingN) * dot(uLight, uRingN)) > 0.0 ? 1.0 : 0.0;
  // the planet's shadow on the ring
  vec3 oc = vPosW - uCenter;
  float b = dot(oc, uLight);
  float away = sqrt(max(0.0, dot(oc, oc) - b * b));
  float shadow = b < 0.0 ? smoothstep(uPlanetR, uPlanetR * 0.92, away) : 0.0;
  vec3 col = mix(uInner, uOuter, smoothstep(0.0, 1.0, u));
  col *= 0.9 + 0.2 * vnoise(vec3(u * 40.0, 3.1, 0.0));
  float bright = mix(0.32, 1.0, lit) * (1.0 - 0.88 * shadow);
  float alpha = d * mix(0.5, 0.92, lit) * (1.0 - 0.7 * shadow);
  col *= bright * (1.0 + uHover * 0.18 + uPulse * 0.3);
  gl_FragColor = vec4(col, alpha * uOpacity);
}
`

const MOON_FRAG = /* glsl */ `${NOISE}
uniform vec3 uLight;
uniform vec3 uColA;
uniform vec3 uColB;
uniform vec3 uAtmo;
uniform float uOpacity;
varying vec3 vObj;
varying vec3 vNormalW;
varying vec3 vPosW;
void main() {
  vec3 q = normalize(vObj);
  vec3 col = mix(uColA, uColB, fbm(q * 6.0));
  col *= 0.76 + 0.5 * smoothstep(0.35, 0.7, fbm(q * 14.0 + 3.0));
  vec3 n = normalize(vNormalW);
  float day = smoothstep(-0.08, 0.5, dot(n, uLight));
  float fres = pow(1.0 - clamp(dot(n, normalize(cameraPosition - vPosW)), 0.0, 1.0), 3.0);
  vec3 lit = col * (0.05 + 0.95 * day) + uAtmo * fres * 0.25 * day;
  gl_FragColor = vec4(lit, uOpacity);
}
`

/** One set of uniforms shared by the planet, its rings and its moon, so a single update re-lights all three. */
export function planetMaterials() {
  const u = {
    uLight: { value: new THREE.Vector3(-0.62, 0.52, 0.58).normalize() },
    uCenter: { value: new THREE.Vector3() },
    uRingN: { value: new THREE.Vector3(0, 1, 0) },
    uRing: { value: new THREE.Vector2(PLANET.ring[0], PLANET.ring[1]) },
    uPlanetR: { value: PLANET.radius },
    uHover: { value: 0 },
    uPulse: { value: 0 },
    uOpacity: { value: 0 },
    uTime: shared.time,
    uAtmo: { value: new THREE.Color() },
  }
  const colours = {
    uColA: { value: new THREE.Color() },
    uColB: { value: new THREE.Color() },
    uColC: { value: new THREE.Color() },
    uInner: { value: new THREE.Color() },
    uOuter: { value: new THREE.Color() },
    uMoonA: { value: new THREE.Color('#6d6a86') },
    uMoonB: { value: new THREE.Color('#d9d4ec') },
  }
  const body = new THREE.ShaderMaterial({
    vertexShader: BODY_VERT,
    fragmentShader: PLANET_FRAG,
    transparent: true,
    uniforms: { ...u, uColA: colours.uColA, uColB: colours.uColB, uColC: colours.uColC },
  })
  const ring = new THREE.ShaderMaterial({
    vertexShader: RING_VERT,
    fragmentShader: RING_FRAG,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: { ...u, uInner: colours.uInner, uOuter: colours.uOuter },
  })
  const moon = new THREE.ShaderMaterial({
    vertexShader: BODY_VERT,
    fragmentShader: MOON_FRAG,
    transparent: true,
    uniforms: { ...u, uColA: colours.uMoonA, uColB: colours.uMoonB },
  })
  return { u, colours, body, ring, moon }
}
