import { useId, type ReactNode } from 'react'
import { pointsToPath } from '../../lib/svgPath'

type P = [number, number]

/**
 * The hand as a soft shape with a drawn edge. The wrist is left open and fades away, so the hand reads as continuing
 * into an arm instead of being cut off by a hard line. Anything passed as children (finger creases, say) sits between
 * the fill and the edge and fades with them.
 */
export default function PalmSilhouette({ pts, w, h, children }: { pts: P[]; w: number; h: number; children?: ReactNode }) {
  const id = useId()
  const ys = pts.map((p) => p[1])
  const bottom = Math.max(...ys)
  const top = Math.min(...ys)
  const fadeFrom = bottom - (bottom - top) * 0.12

  return (
    <g mask={`url(#${id}-m)`}>
      <defs>
        <linearGradient id={`${id}-g`} gradientUnits="userSpaceOnUse" x1="0" y1={fadeFrom} x2="0" y2={bottom}>
          <stop offset="0" stopColor="#fff" />
          <stop offset="1" stopColor="#000" />
        </linearGradient>
        <mask id={`${id}-m`} maskUnits="userSpaceOnUse" x="0" y="0" width={w} height={h}>
          <rect width={w} height={h} fill={`url(#${id}-g)`} />
        </mask>
      </defs>
      <path d={pointsToPath(pts, true)} style={{ fill: 'color-mix(in srgb, var(--accent) 24%, var(--surface))' }} />
      {children}
      <path
        d={pointsToPath(pts)}
        fill="none"
        stroke="var(--ink)"
        strokeOpacity="0.45"
        strokeWidth="1.8"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </g>
  )
}
