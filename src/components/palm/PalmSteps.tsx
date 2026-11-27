import Icon from '../ui/icons'
import Spinner from '../ui/Spinner'
import { STAGES, type StepState } from './palmCopy'

/** The five steps of a palm attempt, live: what each did, the picture it made, and how long it took. */
export default function PalmSteps({ steps }: { steps: StepState }) {
  return (
    <ol className="space-y-3" aria-live="polite">
      {STAGES.map((s, i) => {
        const e = steps[s.key]
        const state = e?.state
        return (
          <li key={s.key} className={`flex gap-4 rounded-2xl border p-4 transition-colors ${state === 'failed' ? 'border-danger/50 bg-danger/5' : state === 'done' ? 'border-ink/15' : state === 'running' ? 'border-accent' : 'border-ink/10 opacity-60'}`}>
            <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border border-ink/20 text-xs">
              {state === 'running' ? <Spinner size={14} /> : state === 'done' ? <Icon name="check" size={14} className="text-detected" /> : state === 'failed' ? <Icon name="x" size={14} className="text-danger" /> : i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-baseline gap-x-2 font-medium">
                {s.title}
                {e?.ms !== undefined && state !== 'running' && <span className="text-xs font-normal text-muted">{Math.round(e.ms)} ms</span>}
              </p>
              <p className="mt-0.5 text-sm text-muted">{e?.detail ?? s.note}</p>
            </div>
            {e?.preview && <img src={e.preview} alt={`${s.title}: what this step made`} className="h-20 shrink-0 rounded-lg border border-ink/10 object-contain" />}
          </li>
        )
      })}
    </ol>
  )
}
