import { getStroke, toSvgPath } from '../lib/handGeometry'

// A small open palm with its heart, head and life lines: the mark used where an icon would be too thin to show a hand.
const PATHS = {
  outline: toSvgPath(getStroke('outline'), { size: 100, perSegment: 4 }),
  lines: ['heart', 'head', 'life'].map((id) => toSvgPath(getStroke(id), { size: 100, perSegment: 4 })),
}

export default function HandMark({ size = 40, className = '' }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} fill="none" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
      <path d={PATHS.outline} stroke="currentColor" strokeWidth="3" />
      {PATHS.lines.map((d, i) => (
        <path key={i} d={d} stroke="currentColor" strokeWidth="2.6" strokeOpacity="0.75" />
      ))}
    </svg>
  )
}
