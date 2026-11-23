import { useEffect, useRef, useState } from 'react'
import { isMock } from '../../api'
import type { HandSide, Reading, StageKey } from '../../api/types'
import CompareSlider from '../../components/CompareSlider'
import AnalysisPanel from '../../components/palm/AnalysisPanel'
import StatusDot from '../../components/StatusDot'
import Icon from '../../components/ui/icons'
import Spinner from '../../components/ui/Spinner'
import type { PreparedPhoto } from '../../lib/photo'
import { STATUS_LABEL } from '../../lib/status'
import { FEATURE_ORDER, featureNumber } from '../../lib/features'
import { STAGE_BY_KEY, STAGE_META, type PreviewMap, type StageMap, type StageStatus } from './stages'

type Props = {
  phase: 'processing' | 'done' | 'failed'
  stages: StageMap
  previews: PreviewMap
  photos: Record<HandSide, PreparedPhoto>
  reading: Reading | null
  /** true when the lines can be drawn on the person's own photos */
  aligned: boolean
  error: string | null
  onCancel: () => void
  onRetry: () => void
  onReplace: () => void
  onOpen: () => void
  onAnother: () => void
}

function StageIcon({ state }: { state: StageStatus['state'] }) {
  if (state === 'running') {
    return (
      <span className="grid h-6 w-6 place-items-center rounded-full bg-accent/30 text-accent-ink">
        <Spinner size={13} />
      </span>
    )
  }
  if (state === 'done') {
    return (
      <span className="grid h-6 w-6 place-items-center rounded-full bg-detected text-paper">
        <Icon name="check" size={13} />
      </span>
    )
  }
  if (state === 'failed') {
    return (
      <span className="grid h-6 w-6 place-items-center rounded-full bg-danger text-paper">
        <Icon name="x" size={13} />
      </span>
    )
  }
  return <span className="block h-6 w-6 rounded-full border-2 border-ink/20" />
}

export default function Processing({ phase, stages, previews, photos, reading, aligned, error, onCancel, onRetry, onReplace, onOpen, onAnother }: Props) {
  const [side, setSide] = useState<HandSide>('left')
  // a step the person chose to look at; it only holds for the phase it was chosen in, so finishing reveals the lines
  const [picked, setPicked] = useState<{ key: StageKey; phase: Props['phase'] } | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  // the page just changed under the person: put the screen-reader cursor on the new heading
  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [])

  // follow the latest finished picture until the person picks a step themselves
  const latestImage = [...STAGE_META].reverse().find((s) => s.image && previews[s.key]?.[side])?.key ?? null
  const linesReady = !!reading
  const shown: StageKey | null = (picked && picked.phase === phase ? picked.key : null) ?? (linesReady ? 'lines' : latestImage)
  const meta = shown ? STAGE_BY_KEY[shown] : null

  const running = STAGE_META.find((s) => stages[s.key].state === 'running')
  const photo = photos[side]
  const aspect = `${photo.width} / ${photo.height}`

  const canView = (key: StageKey) => (STAGE_BY_KEY[key].image && !!previews[key]?.[side]) || (key === 'lines' && linesReady)

  const title =
    phase === 'processing'
      ? 'Reading your palms…'
      : phase === 'done'
        ? reading?.name
          ? `“${reading.name}” is ready.`
          : 'Your reading is ready.'
        : 'That did not work.'
  const lead =
    phase === 'processing'
      ? (running?.doing ?? 'Getting started…')
      : phase === 'done'
        ? 'Look through each step, or open the reading.'
        : 'Nothing was saved, and your photos have been discarded.'

  return (
    <div>
      <p className="kicker">{phase === 'failed' ? 'Something went wrong' : 'Analysing'}</p>
      <h1 ref={heading} tabIndex={-1} className="mt-3 text-balance font-display text-4xl font-light tracking-tight outline-none md:text-5xl">
        {title}
      </h1>
      <p className="mt-3 max-w-2xl text-muted" aria-live="polite">
        {lead}
      </p>

      {phase === 'failed' && (
        <div role="alert" className="mt-8 flex flex-wrap items-start gap-4 rounded-3xl border border-danger/40 bg-danger/10 p-6">
          <Icon name="alert" size={22} className="mt-0.5 text-danger" />
          <div className="min-w-0 flex-1 basis-64">
            <p className="font-medium">{error ?? 'We could not finish the reading.'}</p>
            <p className="mt-1 text-sm text-muted">Your photos are still only in this tab, so you can try again without choosing them again.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={onRetry} className="btn btn-primary">
              Try again
            </button>
            <button type="button" onClick={onReplace} className="btn btn-ghost">
              Replace photos
            </button>
          </div>
        </div>
      )}

      <div className="mt-10 grid gap-8 lg:grid-cols-[19rem_minmax(0,1fr)] lg:gap-12">
        {/* ---------------------------------------------------------- the steps */}
        <ol aria-label="Steps" className="order-2 lg:order-1">
          {STAGE_META.map((s, i) => {
            const st = stages[s.key]
            const viewable = canView(s.key)
            const isShown = shown === s.key
            const last = i === STAGE_META.length - 1
            const inner = (
              <>
                <span className="relative z-10 mt-0.5 shrink-0">
                  <StageIcon state={st.state} />
                </span>
                <span className="min-w-0 flex-1 text-left">
                  <span className={`block font-medium ${st.state === 'waiting' ? 'text-muted' : ''}`}>{s.label}</span>
                  <span className="mt-0.5 block text-sm text-muted">
                    {st.state === 'running' ? 'Working on it…' : st.state === 'waiting' ? '' : (st.detail ?? '')}
                  </span>
                  {viewable && !isShown && <span className="mt-1 block text-xs font-medium text-accent-ink">View this step</span>}
                </span>
              </>
            )
            return (
              <li key={s.key} className="relative">
                {!last && (
                  <span
                    aria-hidden="true"
                    className={`absolute bottom-0 left-3 top-7 w-px ${st.state === 'done' ? 'bg-detected/60' : 'bg-ink/15'}`}
                  />
                )}
                {viewable ? (
                  <button
                    type="button"
                    onClick={() => setPicked({ key: s.key, phase })}
                    aria-current={isShown ? 'step' : undefined}
                    className={`-mx-3 flex w-[calc(100%+1.5rem)] gap-4 rounded-2xl px-3 py-3 transition-colors ${isShown ? 'bg-accent/15' : 'hover:bg-ink/5'}`}
                  >
                    {inner}
                  </button>
                ) : (
                  <div className="-mx-3 flex gap-4 px-3 py-3">{inner}</div>
                )}
              </li>
            )
          })}
        </ol>

        {/* ---------------------------------------------------------- the picture */}
        <div className="order-1 min-w-0 lg:order-2">
          <div role="tablist" aria-label="Which hand to look at" className="mb-4 inline-flex rounded-full border border-ink/15 bg-surface/70 p-1 text-sm">
            {(['left', 'right'] as const).map((h) => (
              <button
                key={h}
                type="button"
                role="tab"
                aria-selected={side === h}
                onClick={() => setSide(h)}
                className={`rounded-full px-5 py-2 transition-colors ${side === h ? 'bg-ink text-paper' : 'text-ink/75 hover:text-ink'}`}
              >
                {h === 'left' ? 'Left palm' : 'Right palm'}
              </button>
            ))}
          </div>

          <div className="mx-auto w-full" style={{ maxWidth: `min(100%, calc(64vh * ${photo.width / photo.height}))` }}>
            {shown === 'lines' && reading ? (
              <AnalysisPanel analysis={reading.hands[side]} photoUrl={aligned ? photo.url : null} active={null} />
            ) : shown && STAGE_BY_KEY[shown].image && previews[shown]?.[side] ? (
              <CompareSlider
                aspect={aspect}
                beforeLabel="Your photo"
                afterLabel={STAGE_BY_KEY[shown].label}
                before={<img src={photo.url} alt={`Your ${side} palm, original`} draggable={false} className="h-full w-full object-cover" />}
                after={<img src={previews[shown]![side]} alt={`Your ${side} palm after ${STAGE_BY_KEY[shown].label}`} draggable={false} className="h-full w-full object-cover" />}
              />
            ) : (
              <div className={`relative overflow-hidden rounded-2xl border border-ink/10 bg-ink/5 ${phase === 'processing' ? 'scan' : ''}`} style={{ aspectRatio: aspect }}>
                <img src={photo.url} alt={`Your ${side} palm`} draggable={false} className="h-full w-full object-cover" />
              </div>
            )}
          </div>

          <div className="mt-5 rounded-2xl bg-ink/5 p-5">
            {meta ? (
              <>
                <p className="kicker">{meta.label}</p>
                <p className="mt-2">{meta.why}</p>
                {shown === 'lines' && reading ? (
                  <LinesLegend reading={reading} side={side} aligned={aligned} />
                ) : (
                  meta.image && (
                    <p className="mt-3 text-xs text-muted">
                      {isMock
                        ? 'Demo mode: this picture is drawn in your browser from your photo to illustrate the step. The real app does this step on the server.'
                        : 'Processed on the server and shown here only. It is not stored.'}
                    </p>
                  )
                )}
              </>
            ) : (
              <p className="text-muted">The steps appear here as they finish. Drag the handle on a picture to compare it with your photo.</p>
            )}
          </div>
        </div>
      </div>

      {/* ---------------------------------------------------------- actions */}
      <div className="mt-10 flex flex-wrap items-center gap-4 border-t border-ink/10 pt-6">
        {phase === 'processing' && (
          <>
            <button type="button" onClick={onCancel} className="btn btn-ghost">
              Cancel
            </button>
            <p className="text-sm text-muted">Photos are processed in memory and never saved.</p>
          </>
        )}
        {phase === 'done' && (
          <>
            <button type="button" onClick={onOpen} className="btn btn-primary !px-8 !py-4">
              Open your reading <Icon name="arrow-right" size={17} />
            </button>
            <button type="button" onClick={onAnother} className="btn btn-ghost">
              Start another
            </button>
            <p className="text-sm text-muted">Your photos stay in this tab only until you leave or reload. Only the results are kept.</p>
          </>
        )}
      </div>
    </div>
  )
}

function LinesLegend({ reading, side, aligned }: { reading: Reading; side: HandSide; aligned: boolean }) {
  const hand = reading.hands[side]
  return (
    <div className="mt-4">
      <ul className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        {FEATURE_ORDER.map((id) => {
          const f = hand.features.find((x) => x.id === id)!
          return (
            <li key={id} className="flex items-center gap-2">
              <span aria-hidden="true" className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-ink/10 text-xs font-medium">
                {featureNumber(id)}
              </span>
              <span className="font-medium">{f.name}</span>
              <StatusDot status={f.status} />
              <span className="text-muted">{STATUS_LABEL[f.status]}</span>
            </li>
          )
        })}
      </ul>
      {!aligned && (
        <p className="mt-3 text-xs text-muted">
          Sample reading: a stand-in placed these lines (they come from the built-in sample photos, or the server has no hand model), so they are drawn on a sketch of the hand instead of the photo.
        </p>
      )}
    </div>
  )
}
