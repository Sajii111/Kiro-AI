import type { P2 } from './handGeometry'

/** SVG path data through a list of points (in picture units). */
export function pointsToPath(points: P2[], close = false): string {
  if (points.length === 0) return ''
  return `M${points.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join('L')}${close ? 'Z' : ''}`
}
