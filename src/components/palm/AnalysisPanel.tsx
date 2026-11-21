import type { KeyboardEvent } from 'react'
import type { FeatureId, FeatureResult, HandAnalysis, NormPoint } from '../../api/types'
import { featureNumber } from '../../lib/features'
import { STATUS_LABEL } from '../../lib/status'
import { pointsToPath } from '../../lib/svgPath'
import PalmSilhouette from './PalmSilhouette'

// THE annotated analysis: the hand with each principal line drawn on it, in a style that says how sure we are.
//   detected     solid line, filled number badge
//   uncertain    dashed line, dashed-ring badge
//   not visible  no line at all: a dotted box marks the area that was searched, with a dotted-ring badge
//   other crease a thin dotted mark with no badge: something was found that is none of the five lines, and it has no name
// The status never rests on colour alone: line style and badge shape say it too.
//
// The picture underneath is either the person's own photo (only while it is still in this tab) or a schematic
// sketch of the hand redrawn from the saved outline.
//
// Two layers, and the order inside each never changes: first every line, then every numbered mark. Moving a
// shape in the DOM while the pointer is pressing on it can swallow the click, so the line that is pointed at is
// emphasised by weight and by fading the others, never by re-ordering. The marks sit above all the lines, so a
// mark can always be reached, even where lines cross.

type Props = {
  analysis: HandAnalysis
  /** The person's own photo, when it is still in this tab and the lines line up with it. */
  photoUrl?: string | null
  showLines?: boolean
  /** the line to emphasise (hovered, else selected) */
  active: FeatureId | null
  /** the line that is selected, for assistive technology */
  selected?: FeatureId | null
  onHover?: (id: FeatureId | null) => void
  onToggle?: (id: FeatureId) => void
  className?: string
}

const COLOR: Record<FeatureResult['status'], string> = {
  detected: 'var(--detected)',
  uncertain: 'var(--uncertain)',
  not_visible: 'var(--muted)',
}

export default function AnalysisPanel({ analysis, photoUrl = null, showLines = true, active, selected = null, onHover, onToggle, className = '' }: Props) {
  const { width: W, height: H } = analysis.photo
  const R = W * 0.036
  const px = ([x, y]: NormPoint): [number, number] => [x * W, y * H]
  const sideName = analysis.side === 'left' ? 'Left' : 'Right'
  const interactive = !!onToggle

  // where each line is, and where its numbered mark sits: at the far end of the line, or on the top edge of the searched area
  const base = analysis.features.map((f) => {
    const hasPath = f.status !== 'not_visible' && f.path.length > 1
    const points = f.path.map(px)
    const box = f.searchArea
    const end = hasPath ? points[points.length - 1] : ([(box.x + box.w / 2) * W, box.y * H] as [number, number])
    return { f, hasPath, points, box, x: end[0], y: end[1] }
  })

  // marks that would land on top of each other are nudged apart, so every one stays easy to see and to press
  const gap = R * 2 + 6
  const clampX = (v: number) => Math.min(W - R - 4, Math.max(R + 4, v))
  const clampY = (v: number) => Math.min(H - R - 4, Math.max(R + 4, v))
  const marks = base.map((b) => ({ x: clampX(b.x), y: clampY(b.y) }))
  for (let pass = 0; pass < 16; pass++) {
    let moved = false
    for (let i = 0; i < marks.length; i++) {
      for (let j = i + 1; j < marks.length; j++) {
        let dx = marks[j].x - marks[i].x
        let dy = marks[j].y - marks[i].y
        let d = Math.hypot(dx, dy)
        if (d >= gap) continue
        if (d < 0.01) {
          dx = 1
          dy = 0
          d = 1
        }
        const push = (gap - d) / 2
        marks[i].x -= (dx / d) * push
        marks[i].y -= (dy / d) * push
        marks[j].x += (dx / d) * push
        marks[j].y += (dy / d) * push
        moved = true
      }
    }
    for (const m of marks) {
      m.x = clampX(m.x)
      m.y = clampY(m.y)
    }
    if (!moved) break
  }

  const shapes = base.map((b, i) => ({
    ...b,
    bx: marks[i].x,
    by: marks[i].y,
    isActive: active === b.f.id,
    dim: active !== null && active !== b.f.id,
  }))

  return (
    <div
      className={`relative overflow-hidden rounded-3xl border border-ink/10 bg-surface ${className}`}
      style={{ aspectRatio: `${W} / ${H}` }}
    >
      {photoUrl && <img src={photoUrl} alt="" draggable={false} className="absolute inset-0 h-full w-full select-none object-fill" />}

      <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 h-full w-full" role="group" aria-label={`${sideName} palm with its main lines marked`}>
        {!photoUrl && analysis.outline && <PalmSilhouette pts={analysis.outline.map(px)} w={W} h={H} />}

        {showLines && (
          <>
            {/* other creases: thin dotted marks, never named, behind everything else */}
            {analysis.otherCreases.map((c) => (
              <path
                key={c.id}
                d={pointsToPath(c.path.map(px))}
                fill="none"
                stroke="var(--muted)"
                strokeWidth="2"
                strokeDasharray="1 5"
                strokeLinecap="round"
                opacity="0.9"
                vectorEffect="non-scaling-stroke"
                aria-hidden="true"
                pointerEvents="none"
              />
            ))}

            {/* layer one: the lines. Pointing at one lights it up, pressing it selects it (the marks do the same for keyboards). */}
            {shapes.map(({ f, hasPath, points, box, isActive, dim }) => (
              <g
                key={f.id}
                aria-hidden="true"
                opacity={dim ? 0.38 : 1}
                style={{ transition: 'opacity 0.25s' }}
                onPointerEnter={() => onHover?.(f.id)}
                onPointerLeave={() => onHover?.(null)}
                onClick={() => onToggle?.(f.id)}
              >
                {hasPath ? (
                  <g fill="none" strokeLinecap="round" strokeLinejoin="round">
                    <path d={pointsToPath(points)} stroke="var(--surface)" strokeOpacity="0.8" strokeWidth={isActive ? 10 : 8} vectorEffect="non-scaling-stroke" />
                    <path
                      d={pointsToPath(points)}
                      stroke={COLOR[f.status]}
                      strokeWidth={isActive ? 5 : 3.4}
                      strokeDasharray={f.status === 'uncertain' ? '8 7' : undefined}
                      vectorEffect="non-scaling-stroke"
                    />
                    {/* a wide invisible stroke makes thin lines easy to point at */}
                    <path d={pointsToPath(points)} stroke="transparent" strokeWidth="24" style={{ cursor: interactive ? 'pointer' : undefined }} pointerEvents={interactive ? 'stroke' : 'none'} vectorEffect="non-scaling-stroke" />
                  </g>
                ) : (
                  <rect
                    x={box.x * W}
                    y={box.y * H}
                    width={box.w * W}
                    height={box.h * H}
                    rx={R * 1.4}
                    fill="transparent"
                    stroke={COLOR.not_visible}
                    strokeWidth={isActive ? 3 : 2}
                    strokeDasharray="0.1 6"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                    // the searched box is only a drawing: its mark is the thing to point at, so the box never blocks the lines beneath it
                    pointerEvents="none"
                  />
                )}
              </g>
            ))}

            {/* layer two: the numbered marks, always above every line */}
            {shapes.map(({ f, bx, by, isActive, dim }) => {
              const label = `${f.name}, ${STATUS_LABEL[f.status].toLowerCase()}${f.confidence !== null ? `, detection score ${Math.round(f.confidence * 100)} percent` : ''}`
              const toggle = () => onToggle?.(f.id)
              const onKey = (e: KeyboardEvent) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  toggle()
                }
              }
              return (
                <g
                  key={f.id}
                  role={interactive ? 'button' : 'img'}
                  tabIndex={interactive ? 0 : undefined}
                  aria-label={label}
                  aria-pressed={interactive ? selected === f.id : undefined}
                  opacity={dim ? 0.38 : 1}
                  onPointerEnter={() => onHover?.(f.id)}
                  onPointerLeave={() => onHover?.(null)}
                  onClick={toggle}
                  onKeyDown={interactive ? onKey : undefined}
                  onFocus={interactive ? () => onHover?.(f.id) : undefined}
                  onBlur={interactive ? () => onHover?.(null) : undefined}
                  className="focus-own [&:focus-visible>circle:first-of-type]:stroke-focus"
                  style={{ cursor: interactive ? 'pointer' : undefined, transition: 'opacity 0.25s' }}
                  transform={`translate(${bx} ${by}) scale(${isActive ? 1.18 : 1})`}
                >
                  <title>{label}</title>
                  {/* a generous invisible target for a finger, and the ring that shows keyboard focus */}
                  <circle r={R + 10} fill="transparent" stroke="transparent" strokeWidth="3" />
                  <circle r={R + 3} fill="var(--surface)" />
                  {f.status === 'detected' && <circle r={R} fill="var(--detected)" />}
                  {f.status === 'uncertain' && <circle r={R - 1} fill="var(--surface)" stroke="var(--uncertain)" strokeWidth="2.6" strokeDasharray="5.5 4" />}
                  {f.status === 'not_visible' && <circle r={R - 1} fill="var(--surface)" stroke="var(--muted)" strokeWidth="2.6" strokeDasharray="0.1 5.2" strokeLinecap="round" />}
                  <text
                    textAnchor="middle"
                    dominantBaseline="central"
                    fontSize={R * 1.12}
                    fontWeight="600"
                    fill={f.status === 'detected' ? 'var(--paper)' : 'var(--ink)'}
                    style={{ fontFamily: 'var(--font-body)', pointerEvents: 'none' }}
                  >
                    {featureNumber(f.id)}
                  </text>
                </g>
              )
            })}
          </>
        )}
      </svg>
    </div>
  )
}
