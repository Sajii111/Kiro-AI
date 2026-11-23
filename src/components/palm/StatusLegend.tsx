import type { ReactNode } from 'react'

// What the three line styles on the annotated hand mean. The same shapes are used on the hand itself,
// so the legend is a picture of the marks and not only a colour key.

function Glyph({ children }: { children: ReactNode }) {
  return (
    <svg width="34" height="14" viewBox="0 0 34 14" aria-hidden="true" className="mt-0.5 shrink-0">
      {children}
    </svg>
  )
}

export default function StatusLegend({ className = '' }: { className?: string }) {
  return (
    <ul className={`grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4 ${className}`} aria-label="What the marks mean">
      <li className="flex items-start gap-3">
        <Glyph>
          <path d="M3 7h28" stroke="var(--detected)" strokeWidth="3.4" strokeLinecap="round" />
        </Glyph>
        <span>
          <strong className="font-medium">Detected.</strong> <span className="text-muted">A clear line was found and drawn in.</span>
        </span>
      </li>
      <li className="flex items-start gap-3">
        <Glyph>
          <path d="M3 7h28" stroke="var(--uncertain)" strokeWidth="3.4" strokeLinecap="round" strokeDasharray="6 5" />
        </Glyph>
        <span>
          <strong className="font-medium">Uncertain.</strong> <span className="text-muted">Seen faintly, so nothing is said about its shape.</span>
        </span>
      </li>
      <li className="flex items-start gap-3">
        <Glyph>
          <rect x="3" y="2" width="28" height="10" rx="4" fill="none" stroke="var(--muted)" strokeWidth="2" strokeDasharray="0.1 5" strokeLinecap="round" />
        </Glyph>
        <span>
          <strong className="font-medium">Not visible.</strong> <span className="text-muted">Searched here, nothing clear enough to mark.</span>
        </span>
      </li>
      <li className="flex items-start gap-3">
        <Glyph>
          <path d="M3 7h28" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" strokeDasharray="1 5" />
        </Glyph>
        <span>
          <strong className="font-medium">Other crease.</strong> <span className="text-muted">Found, but it is none of the five lines, so it has no name.</span>
        </span>
      </li>
    </ul>
  )
}
