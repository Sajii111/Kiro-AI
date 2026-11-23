import type { FeatureId, FeatureResult, HandAnalysis } from '../../api/types'
import { FEATURE_ORDER, featureNumber } from '../../lib/features'
import { STATUS_LABEL } from '../../lib/status'
import StatusDot from '../StatusDot'

type Hands = { left: HandAnalysis; right: HandAnalysis }

const find = (a: HandAnalysis, id: FeatureId) => a.features.find((f) => f.id === id)!

function Cell({ f }: { f: FeatureResult }) {
  return (
    <span className="flex items-center gap-1.5 text-sm">
      <StatusDot status={f.status} />
      <span className={f.status === 'not_visible' ? 'text-muted' : ''}>{STATUS_LABEL[f.status]}</span>
      {f.confidence !== null && (
        <span className="hidden text-xs text-muted sm:inline" title="How clearly this line showed up in the photo">
          <span className="sr-only">score </span>
          {Math.round(f.confidence * 100)}%
        </span>
      )}
    </span>
  )
}

/** Every line, both hands, at a glance. Rows are buttons: pointing at one lights up that line on both palms. */
export function FeatureTable({
  hands,
  active,
  selected,
  onHover,
  onToggle,
}: {
  hands: Hands
  active: FeatureId | null
  selected: FeatureId | null
  onHover: (id: FeatureId | null) => void
  onToggle: (id: FeatureId) => void
}) {
  return (
    <div className="card overflow-hidden">
      <div className="grid grid-cols-[minmax(0,1.15fr)_1fr_1fr] gap-3 border-b border-ink/10 px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-muted">
        <span>Line</span>
        <span>Left hand</span>
        <span>Right hand</span>
      </div>
      <ul>
        {FEATURE_ORDER.map((id) => {
          const l = find(hands.left, id)
          const r = find(hands.right, id)
          const isSelected = selected === id
          return (
            <li key={id} className="border-b border-ink/10 last:border-b-0">
              <button
                type="button"
                aria-pressed={isSelected}
                onClick={() => onToggle(id)}
                onPointerEnter={() => onHover(id)}
                onPointerLeave={() => onHover(null)}
                onFocus={() => onHover(id)}
                onBlur={() => onHover(null)}
                className={`grid w-full grid-cols-[minmax(0,1.15fr)_1fr_1fr] items-center gap-3 px-4 py-3 text-left transition-colors ${
                  isSelected ? 'bg-accent/15' : active === id ? 'bg-ink/5' : 'hover:bg-ink/5'
                }`}
              >
                <span className="flex items-center gap-2.5">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-ink text-xs font-semibold text-paper">{featureNumber(id)}</span>
                  <span className="truncate font-medium">{l.name}</span>
                </span>
                <Cell f={l} />
                <Cell f={r} />
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Side({ title, f }: { title: string; f: FeatureResult }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</p>
      <p className="mt-2 flex items-center gap-2 font-medium">
        <StatusDot status={f.status} /> {STATUS_LABEL[f.status]}
      </p>
      {f.confidence !== null && (
        <div className="mt-2 flex items-center gap-3 text-xs text-muted">
          <span
            className="h-1.5 w-24 overflow-hidden rounded-full bg-ink/10"
            role="img"
            aria-label={`score ${Math.round(f.confidence * 100)} percent`}
          >
            <span className="block h-full rounded-full bg-ink/60" style={{ width: `${Math.round(f.confidence * 100)}%` }} />
          </span>
          Score {Math.round(f.confidence * 100)}%
        </div>
      )}
      <p className="mt-3 text-sm leading-relaxed">{f.observation}</p>
    </div>
  )
}

/** What was seen for one line, on each hand. Only what is visible in the photo: no meaning attached here. */
export function FeatureDetail({ hands, id }: { hands: Hands; id: FeatureId | null }) {
  if (!id) {
    return (
      <div className="card flex min-h-[15rem] items-center justify-center p-5 text-center text-sm text-muted" aria-live="polite">
        Select a line, on a hand or in the table, to see what was seen there.
      </div>
    )
  }
  const l = find(hands.left, id)
  const r = find(hands.right, id)
  return (
    <div className="card min-h-[15rem] p-5 md:p-6" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="flex items-center gap-2.5 font-display text-xl font-normal">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-ink text-xs font-semibold text-paper">{featureNumber(id)}</span>
          {l.name}
        </h3>
        <p className="text-xs text-muted">What was seen. Visual only, with no meaning attached.</p>
      </div>
      <div className="mt-4 grid gap-6 sm:grid-cols-2">
        <Side title="Left hand" f={l} />
        <Side title="Right hand" f={r} />
      </div>
      <p className="mt-4 text-xs text-muted">
        Detected with {l.method}
        {l.method !== r.method ? ` and ${r.method}` : ''}. The score shows how clearly the line showed up in the photo. It is not the chance that a reading is right.
      </p>
    </div>
  )
}
