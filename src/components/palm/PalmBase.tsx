import { HAND_STROKES, getStroke, handFrame, sampleSpline } from '../../lib/handGeometry'
import { pointsToPath } from '../../lib/svgPath'
import PalmSilhouette from './PalmSilhouette'
import { t } from '../../i18n'

/**
 * The schematic palm: a soft silhouette, its outline and the finger-joint creases, drawn in a picture of w x h units.
 * It is what a saved reading shows under the findings, because the photo itself is never kept. A left hand is the right one mirrored.
 */
export default function PalmBase({ w, h, flip = false }: { w: number; h: number; flip?: boolean }) {
  const { toPx } = handFrame(w, h)
  const outline = sampleSpline(getStroke('outline').pts, 8).map(toPx)
  const creases = HAND_STROKES.filter((s) => s.kind === 'crease')

  return (
    <g transform={flip ? `translate(${w} 0) scale(-1 1)` : undefined}>
      <PalmSilhouette pts={outline} w={w} h={h}>
        <g fill="none" stroke="var(--ink)" strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.2" strokeWidth="1.6">
          {creases.map((s) => (
            <path key={s.id} d={pointsToPath(sampleSpline(s.pts, 6).map(toPx))} vectorEffect="non-scaling-stroke" />
          ))}
        </g>
      </PalmSilhouette>
    </g>
  )
}

const LINES = [
  { id: 'heart', status: 'detected' },
  { id: 'head', status: 'detected' },
  { id: 'life', status: 'detected' },
  { id: 'fate', status: 'uncertain' },
] as const

/** A decorative palm showing the three kinds of result: solid (detected), dashed (uncertain), dotted (not visible). */
export function PalmArt({ className = '' }: { className?: string }) {
  const W = 520
  const H = 660
  const { toPx } = handFrame(W, H)
  const sun = getStroke('sun').pts.map(toPx)
  const xs = sun.map((p) => p[0])
  const ys = sun.map((p) => p[1])
  const box = { x: Math.min(...xs) - 26, y: Math.min(...ys) - 26, w: Math.max(...xs) - Math.min(...xs) + 52, h: Math.max(...ys) - Math.min(...ys) + 52 }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("A drawing of a palm with its main lines marked as detected, uncertain and not visible")} className={className}>
      <PalmBase w={W} h={H} />
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        {LINES.map(({ id, status }) => {
          const d = pointsToPath(sampleSpline(getStroke(id).pts, 8).map(toPx))
          return (
            <g key={id}>
              <path d={d} stroke="var(--surface)" strokeOpacity="0.8" strokeWidth="9" vectorEffect="non-scaling-stroke" />
              <path
                d={d}
                stroke={status === 'detected' ? 'var(--detected)' : 'var(--uncertain)'}
                strokeWidth="3.4"
                strokeDasharray={status === 'uncertain' ? '8 7' : undefined}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          )
        })}
        <rect x={box.x} y={box.y} width={box.w} height={box.h} rx="22" stroke="var(--muted)" strokeWidth="2" strokeDasharray="0.1 6" vectorEffect="non-scaling-stroke" />
      </g>
    </svg>
  )
}
