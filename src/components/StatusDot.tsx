// How sure we are about a palm feature. Never colour alone: each status also has its own shape,
// so it reads clearly for colour-blind visitors and in grayscale screenshots.
//   detected     solid dot
//   uncertain    dashed ring
//   not_visible  dotted ring

import type { FeatureStatus } from '../lib/status'

export default function StatusDot({ status, className = '' }: { status: FeatureStatus; className?: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" className={`shrink-0 ${className}`}>
      {status === 'detected' && <circle cx="7" cy="7" r="5" className="fill-detected" />}
      {status === 'uncertain' && (
        <circle cx="7" cy="7" r="5" fill="none" strokeWidth="2" strokeDasharray="3.2 2.2" className="stroke-uncertain" />
      )}
      {status === 'not_visible' && (
        <circle cx="7" cy="7" r="5" fill="none" strokeWidth="2" strokeDasharray="0.1 3.5" strokeLinecap="round" className="stroke-muted" />
      )}
    </svg>
  )
}
