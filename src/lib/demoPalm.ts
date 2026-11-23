import { HAND_STROKES, getStroke, handFrame, sampleSpline } from './handGeometry'

/**
 * Paints a convincing "photo" of a palm using nothing but the hand geometry:
 * skin tones, soft shading, creases, uneven lighting and sensor noise.
 * No real person's hand is involved; it only demonstrates the processing steps.
 */
export function drawDemoPalm(w = 520, h = 660, table: readonly [string, string] = ['#6a564c', '#2d2522']): HTMLCanvasElement {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const ctx = c.getContext('2d', { willReadFrequently: true })!

  // the same placement the sample analysis uses, so overlay lines land exactly on the creases
  const P = handFrame(w, h).toPx

  // a dim tabletop (warm brown unless another pair of colours is asked for)
  const bg = ctx.createLinearGradient(0, 0, w, h)
  bg.addColorStop(0, table[0])
  bg.addColorStop(1, table[1])
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, w, h)

  // hand silhouette. The forearm runs off the bottom of the picture, as it does in a real photo of a palm
  const outline = sampleSpline(getStroke('outline').pts, 10).map(P)
  const first = outline[0]
  const last = outline[outline.length - 1]
  const silhouette = new Path2D()
  silhouette.moveTo(first[0], first[1])
  for (const [x, y] of outline) silhouette.lineTo(x, y)
  silhouette.lineTo(last[0] + 8, h + 60)
  silhouette.lineTo(first[0] - 8, h + 60)
  silhouette.closePath()

  // soft shadow under the hand
  ctx.save()
  ctx.filter = 'blur(18px)'
  ctx.translate(10, 14)
  ctx.fillStyle = 'rgba(0,0,0,0.35)'
  ctx.fill(silhouette)
  ctx.restore()

  const skin = ctx.createLinearGradient(0, 0, w, h)
  skin.addColorStop(0, '#ecbc98')
  skin.addColorStop(0.55, '#d9a37f')
  skin.addColorStop(1, '#bf8561')
  ctx.fillStyle = skin
  ctx.fill(silhouette)

  // darker rim inside the edge for roundness
  ctx.save()
  ctx.clip(silhouette)
  ctx.filter = 'blur(12px)'
  ctx.lineWidth = 34
  ctx.strokeStyle = 'rgba(120,68,44,0.38)'
  ctx.stroke(silhouette)
  ctx.restore()

  // creases
  ctx.save()
  ctx.clip(silhouette)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const id of ['heart', 'head', 'life', 'fate', 'sun']) {
    const pts = sampleSpline(getStroke(id).pts, 10).map(P)
    ctx.beginPath()
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
    ctx.filter = 'blur(2.2px)'
    ctx.lineWidth = id === 'fate' || id === 'sun' ? 3.4 : 5
    ctx.strokeStyle = id === 'sun' ? 'rgba(126,72,50,0.28)' : 'rgba(118,66,44,0.62)'
    ctx.stroke()
  }
  // the joint creases of the fingers and thumb, and the crease across the wrist
  ctx.filter = 'blur(1px)'
  ctx.lineWidth = 2.2
  ctx.strokeStyle = 'rgba(126,72,50,0.42)'
  for (const s of HAND_STROKES) {
    if (s.kind !== 'crease') continue
    const pts = sampleSpline(s.pts, 8).map(P)
    ctx.beginPath()
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
    ctx.stroke()
  }
  ctx.restore()

  // uneven lighting: bright upper left, dim lower right
  const light = ctx.createRadialGradient(w * 0.3, h * 0.25, 10, w * 0.5, h * 0.5, Math.max(w, h) * 0.85)
  light.addColorStop(0, 'rgba(255,240,220,0.28)')
  light.addColorStop(0.55, 'rgba(0,0,0,0)')
  light.addColorStop(1, 'rgba(0,0,0,0.38)')
  ctx.fillStyle = light
  ctx.fillRect(0, 0, w, h)

  // sensor noise
  const img = ctx.getImageData(0, 0, w, h)
  for (let i = 0; i < img.data.length; i += 4) {
    const n = (Math.random() - 0.5) * 26
    img.data[i] += n
    img.data[i + 1] += n
    img.data[i + 2] += n
  }
  ctx.putImageData(img, 0, 0)
  return c
}
