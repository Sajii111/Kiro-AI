// A stylised hand drawn entirely in code (no photos, no model files).
// Everything is stored as a few control points per stroke and smoothed with a Catmull-Rom spline.
// The same strokes feed: the SVG intro mark, the 3D ribbons on the landing page,
// the palm silhouette behind saved readings, and the demo feature paths in the mock API.
//
// Space: x to the right, y up, wrist crease near y = 0, palm about 1 unit wide.
// This is a RIGHT hand with the palm facing the viewer (thumb on the right). Use mirror() for a left hand.

export type P2 = [number, number]

export type Stroke = {
  id: string
  kind: 'outline' | 'line' | 'crease'
  pts: P2[]
}

// ---------------------------------------------------------------- spline sampling

function seg(p0: P2, p1: P2, p2: P2, p3: P2, t: number): P2 {
  // Centripetal Catmull-Rom (Barry-Goldman). Avoids loops and overshoot on uneven spacing.
  const d = (a: P2, b: P2) => Math.max(1e-6, Math.hypot(b[0] - a[0], b[1] - a[1]) ** 0.5)
  const t0 = 0
  const t1 = t0 + d(p0, p1)
  const t2 = t1 + d(p1, p2)
  const t3 = t2 + d(p2, p3)
  const x = t1 + (t2 - t1) * t
  const mix = (a: P2, b: P2, ta: number, tb: number): P2 => {
    const k = (x - ta) / (tb - ta)
    return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]
  }
  const a1 = mix(p0, p1, t0, t1)
  const a2 = mix(p1, p2, t1, t2)
  const a3 = mix(p2, p3, t2, t3)
  const b1 = mix(a1, a2, t0, t2)
  const b2 = mix(a2, a3, t1, t3)
  return mix(b1, b2, t1, t2)
}

/** Smooth polyline through the control points (open curve). */
export function sampleSpline(pts: P2[], perSegment = 10): P2[] {
  if (pts.length < 3) return pts.slice()
  const first = pts[0]
  const last = pts[pts.length - 1]
  const ext: P2[] = [
    [2 * first[0] - pts[1][0], 2 * first[1] - pts[1][1]],
    ...pts,
    [2 * last[0] - pts[pts.length - 2][0], 2 * last[1] - pts[pts.length - 2][1]],
  ]
  const out: P2[] = []
  for (let i = 0; i < pts.length - 1; i++) {
    for (let j = 0; j < perSegment; j++) {
      out.push(seg(ext[i], ext[i + 1], ext[i + 2], ext[i + 3], j / perSegment))
    }
  }
  out.push(last)
  return out
}

// ---------------------------------------------------------------- the hand
//
// The proportions follow a real adult hand, measured in palm widths: the palm is about 1.2 long, the middle finger
// about 0.95, the thumb reaches up to the level of the index knuckle, every finger narrows towards a rounded tip,
// and the thumb is broader than the fingers and springs out of a full thenar pad.

type Finger = {
  /** the two valley points where this finger leaves the palm (its left and right side, palm facing the viewer) */
  l: P2
  r: P2
  /** lean from straight up, in degrees (positive leans right) */
  angle: number
  /** from the middle of the base to the tip */
  length: number
  /** how wide the finger still is near the tip, compared with its base (1 = not narrower) */
  taper: number
  /** how round the tip is (1 = a half circle) */
  round: number
  /** how far the tip curves to the finger's right (negative: to its left), so the hand is relaxed rather than stiff */
  bend?: number
}

// the valleys between the fingers, left to right
const V0: P2 = [-0.3, 1.05]
const V1: P2 = [-0.045, 1.165]
const V2: P2 = [0.21, 1.15]

// pinky, ring, middle, index (left to right for a right palm)
const FINGERS: Finger[] = [
  { l: [-0.535, 0.985], r: V0, angle: -16, length: 0.72, taper: 0.76, round: 1.08, bend: 0.03 },
  { l: V0, r: V1, angle: -6, length: 0.95, taper: 0.74, round: 1.08, bend: 0.01 },
  { l: V1, r: V2, angle: 0.5, length: 1.03, taper: 0.74, round: 1.08 },
  { l: V2, r: [0.485, 1.08], angle: 7.5, length: 0.88, taper: 0.75, round: 1.08, bend: -0.03 },
]

/** the thumb is built the same way as a finger: wider, shorter and leaning far out */
const THUMB: Finger = { l: [0.53, 0.75], r: [0.655, 0.47], angle: 45, length: 0.65, taper: 0.74, round: 1.0, bend: -0.05 }

const bump = (s: number, at: number, size: number) => size * Math.exp(-(((s - at) / 0.075) ** 2))

function fingerEdges(f: Finger) {
  const a = (f.angle * Math.PI) / 180
  const dir: P2 = [Math.sin(a), Math.cos(a)]
  const perp: P2 = [Math.cos(a), -Math.sin(a)] // towards the finger's right-hand side
  const mid: P2 = [(f.l[0] + f.r[0]) / 2, (f.l[1] + f.r[1]) / 2]
  // the width across the finger (not along the slanted line between the valleys)
  const w0 = Math.abs((f.r[0] - f.l[0]) * perp[0] + (f.r[1] - f.l[1]) * perp[1])
  const bend = f.bend ?? 0
  const centre = (s: number): P2 => [
    mid[0] + dir[0] * s * f.length + perp[0] * bend * s * s,
    mid[1] + dir[1] * s * f.length + perp[1] * bend * s * s,
  ]
  // half the width at a point along the finger: narrows towards the tip, with a slight swell at each knuckle
  const half = (s: number) => (w0 / 2) * (1 - (1 - f.taper) * (0.55 * s + 0.45 * s * s) + bump(s, 0.33, 0.05) + bump(s, 0.66, 0.04))
  // the natural corner of the base is not exactly at a valley point, so the difference is carried up the finger and fades out
  const corner = (side: -1 | 1): P2 => [mid[0] + perp[0] * (w0 / 2) * side, mid[1] + perp[1] * (w0 / 2) * side]
  const edge = (s: number, side: -1 | 1): P2 => {
    const c = centre(s)
    const h = half(s)
    const base = side < 0 ? f.l : f.r
    const n = corner(side)
    const k = (1 - s) ** 3
    return [c[0] + perp[0] * h * side + (base[0] - n[0]) * k, c[1] + perp[1] * h * side + (base[1] - n[1]) * k]
  }

  // where the rounded tip begins
  let sc = 0.9
  for (let i = 0; i < 3; i++) sc = 1 - (f.round * half(sc)) / f.length
  const hc = half(sc)
  const capLen = f.round * hc
  const along = [0, 0.15, 0.3, 0.45, 0.6, 0.75].filter((s) => s < sc - 0.07)
  const up = [...along, sc]
  const cap: P2[] = [150, 120, 90, 60, 30].map((deg) => {
    const p = (deg * Math.PI) / 180
    const c = centre(sc)
    return [c[0] + dir[0] * capLen * Math.sin(p) + perp[0] * hc * Math.cos(p), c[1] + dir[1] * capLen * Math.sin(p) + perp[1] * hc * Math.cos(p)]
  })

  return {
    left: up.map((s) => edge(s, -1)),
    cap,
    right: up.map((s) => edge(s, 1)).reverse(),
    /** a point s of the way up the finger, `across` of the way from the middle to a side (-1 left .. 1 right) */
    at: (s: number, across: number): P2 => {
      const c = centre(s)
      const h = half(s)
      return [c[0] + perp[0] * h * across, c[1] + perp[1] * h * across]
    },
  }
}

function buildOutline(): P2[] {
  // up the little-finger side of the palm
  const pts: P2[] = [
    [-0.335, -0.22],
    [-0.345, -0.08],
    [-0.38, 0.1],
    [-0.43, 0.32],
    [-0.475, 0.55],
    [-0.5, 0.78],
    [-0.516, 0.88],
  ]
  // the four fingers, with a rounded valley between each pair
  FINGERS.forEach((f, i) => {
    const e = fingerEdges(f)
    pts.push(...(i === 0 ? e.left : e.left.slice(1)), ...e.cap, ...(i < FINGERS.length - 1 ? e.right.slice(0, -1) : e.right))
    if (i < FINGERS.length - 1) {
      const v = f.r
      pts.push([v[0] - 0.007, v[1] + 0.004], [v[0], v[1] - 0.017], [v[0] + 0.007, v[1] + 0.004])
    }
  })
  // down the edge of the palm to the web, then out along the thumb and down the thenar pad to the wrist
  pts.push([0.49, 0.98], [0.494, 0.88], [0.508, 0.8])
  const t = fingerEdges(THUMB)
  pts.push(...t.left, ...t.cap, ...t.right)
  pts.push([0.615, 0.37], [0.57, 0.26], [0.495, 0.1], [0.415, -0.05], [0.345, -0.22])
  return pts
}

const OUTLINE = buildOutline()

const LINES: Stroke[] = [
  {
    id: 'heart',
    kind: 'line',
    pts: [[-0.5, 0.82], [-0.4, 0.9], [-0.22, 0.95], [0.0, 0.96], [0.17, 0.99], [0.29, 1.04]],
  },
  {
    id: 'head',
    kind: 'line',
    pts: [[0.46, 0.8], [0.32, 0.74], [0.14, 0.69], [-0.06, 0.64], [-0.24, 0.6], [-0.4, 0.55]],
  },
  {
    id: 'life',
    kind: 'line',
    pts: [[0.44, 0.82], [0.36, 0.7], [0.27, 0.56], [0.21, 0.4], [0.18, 0.24], [0.2, 0.07], [0.27, -0.07]],
  },
  {
    id: 'fate',
    kind: 'line',
    pts: [[0.0, -0.06], [-0.01, 0.14], [0.0, 0.36], [0.03, 0.58], [0.06, 0.76], [0.08, 0.9]],
  },
  {
    id: 'sun',
    kind: 'line',
    pts: [[-0.1, 0.46], [-0.13, 0.6], [-0.16, 0.74], [-0.18, 0.88]],
  },
]

/** Short joint creases across each finger, the thumb and the wrist: little marks that make the outline read as a hand. */
function buildCreases(): Stroke[] {
  const out: Stroke[] = []
  FINGERS.forEach((f, i) => {
    const e = fingerEdges(f)
    ;[0.36, 0.64].forEach((along, j) => {
      const l = e.at(along, -0.6)
      const m = e.at(along - 0.014, 0)
      const r = e.at(along, 0.6)
      out.push({ id: `crease-${i}-${j}`, kind: 'crease', pts: [l, m, r] })
    })
  })
  const t = fingerEdges(THUMB)
  ;[
    ['crease-thumb', 0.6],
    ['crease-thumb-b', 0.26],
  ].forEach(([id, along]) => {
    const l = t.at(along as number, -0.62)
    const m = t.at((along as number) - 0.02, 0)
    const r = t.at(along as number, 0.62)
    out.push({ id: id as string, kind: 'crease', pts: [l, m, r] })
  })
  out.push({ id: 'crease-wrist', kind: 'crease', pts: [[-0.31, -0.03], [-0.12, -0.075], [0.12, -0.08], [0.33, -0.04]] })
  return out
}

export const HAND_STROKES: Stroke[] = [
  { id: 'outline', kind: 'outline', pts: OUTLINE },
  ...LINES,
  ...buildCreases(),
]

/** Names used across the app for the five principal lines. */
export const LINE_IDS = ['heart', 'head', 'life', 'fate', 'sun'] as const
export type LineId = (typeof LINE_IDS)[number]

/** The box around the hand (from the outline itself, with a little air), so a change to the drawing never leaves it off-centre. */
function boundsOf(pts: P2[], pad: number) {
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  return { minX: Math.min(...xs) - pad, maxX: Math.max(...xs) + pad, minY: Math.min(...ys) - pad, maxY: Math.max(...ys) + pad }
}

export const HAND_BOUNDS = boundsOf(sampleSpline(OUTLINE, 6), 0.04)

/** The point of the hand the 3D version turns around (hand space). The drawn hand is centred on the middle of HAND_BOUNDS instead. */
export const HAND_CENTRE = { x: 0.2, y: 0.98 }

export function mirror(strokes: Stroke[]): Stroke[] {
  return strokes.map((s) => ({ ...s, pts: s.pts.map(([x, y]) => [-x, y] as P2) }))
}

export function getStroke(id: string): Stroke {
  const s = HAND_STROKES.find((x) => x.id === id)
  if (!s) throw new Error(`Unknown hand stroke: ${id}`)
  return s
}

/**
 * Where the hand sits inside a picture of w x h pixels. The sample photo, the schematic palm and the
 * mock feature paths all use this one placement, so they line up exactly.
 */
export function handFrame(w: number, h: number, fill = 0.9) {
  const b = HAND_BOUNDS
  const s = Math.min(w / (b.maxX - b.minX), h / (b.maxY - b.minY)) * fill
  const ox = (w - (b.maxX - b.minX) * s) / 2 - b.minX * s
  const oy = (h - (b.maxY - b.minY) * s) / 2 + b.maxY * s
  return {
    scale: s,
    /** hand space to pixels */
    toPx: ([x, y]: P2): P2 => [ox + x * s, oy - y * s],
  }
}

/** Depth for the 3D version: palm slightly cupped, fingertips curling a touch towards the viewer. */
export function handDepth(x: number, y: number): number {
  const palm = 0.1 * Math.max(0, 1 - (x * x) / 0.5)
  const curl = 0.32 * Math.pow(Math.max(0, y - 1.2), 1.5)
  const thumb = 0.12 * Math.max(0, x - 0.45)
  return palm + curl + thumb
}

// ---------------------------------------------------------------- SVG helpers

/** SVG path data for a stroke inside a viewBox of `size` x `size` (hand centred, y flipped). */
export function toSvgPath(
  s: Stroke,
  opts: { size?: number; flip?: boolean; perSegment?: number } = {},
): string {
  const size = opts.size ?? 200
  const per = opts.perSegment ?? 8
  const b = HAND_BOUNDS
  const w = b.maxX - b.minX
  const h = b.maxY - b.minY
  const k = (size * 0.9) / Math.max(w, h)
  const ox = (size - w * k) / 2
  const oy = (size - h * k) / 2
  const pts = sampleSpline(s.pts, per)
  return pts
    .map(([x, y], i) => {
      const xx = ox + ((opts.flip ? -x : x) - (opts.flip ? -b.maxX : b.minX)) * k
      const yy = oy + (b.maxY - y) * k
      return `${i === 0 ? 'M' : 'L'}${xx.toFixed(1)} ${yy.toFixed(1)}`
    })
    .join(' ')
}
