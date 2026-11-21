import type { FeatureId, HandSide, Reading, ReportSection as Section, ShapeSection, SideObservation, ThemeSection, ThemeSource } from '../../api/types'
import StatusDot from '../../components/StatusDot'
import Icon from '../../components/ui/icons'
import { formatDateTime } from '../../lib/format'
import { featureNumber } from '../../lib/features'
import { STATUS_LABEL } from '../../lib/status'
import { DISCLAIMER_LONG } from '../copy'

// The written report. Two kinds of sentence are kept visibly apart on purpose:
//   what was SEEN in the photo (plain, factual), and what the TRADITION says about it (tinted, labelled).
// A line that was not seen carries no traditional reading at all.
//
// The same findings can be read two ways, and the person chooses:
//   By theme  personality, career, money, relationships, future outlook: each one says which lines it rests on
//   By line   one card per principal line, both hands side by side

export type ReportView = 'theme' | 'line'

const SIDES: HandSide[] = ['left', 'right']

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
const scrollToId = (id: string) =>
  requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' }))

/** What was seen, then what the tradition says, for each hand. Shared by the line cards and the hand shape card. */
function SidePair({ observed, traditional, notSeen }: { observed: Record<HandSide, SideObservation>; traditional: Record<HandSide, string | null>; notSeen: string }) {
  return (
    <div className="mt-5 grid gap-6 md:grid-cols-2">
      {SIDES.map((side) => {
        const seen = observed[side]
        const tradition = traditional[side]
        return (
          <div key={side}>
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted">
              {side === 'left' ? 'Left hand' : 'Right hand'}
              <span className="flex items-center gap-1.5 font-medium normal-case tracking-normal text-ink">
                <StatusDot status={seen.status} /> {STATUS_LABEL[seen.status]}
              </span>
            </p>
            <p className="mt-2 text-sm leading-relaxed">
              <span className="sr-only">What was seen: </span>
              {seen.text}
            </p>
            <div className="mt-3 rounded-2xl border border-accent2/50 bg-accent2/15 p-4">
              <p className="kicker !text-[0.68rem]">Traditional reading</p>
              {tradition ? <p className="mt-1.5 text-sm leading-relaxed">{tradition}</p> : <p className="mt-1.5 text-sm italic text-muted">{notSeen}</p>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function LineCard({ section, selected, onShow }: { section: Section; selected: boolean; onShow: (id: FeatureId) => void }) {
  const id = section.featureId
  return (
    <article id={`report-${id}`} className={`card scroll-mt-28 p-5 transition-colors md:p-7 ${selected ? 'border-accent shadow-[0_0_0_1px_var(--accent)]' : ''}`}>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-3 font-display text-2xl font-normal">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-ink text-sm font-semibold text-paper">{featureNumber(id)}</span>
          {section.title}
        </h3>
        <button type="button" onClick={() => onShow(id)} className="btn btn-ghost btn-sm">
          Show on the hands
        </button>
      </header>

      <SidePair observed={section.observed} traditional={section.traditional} notSeen="Not described. This line was not seen clearly enough, so nothing is claimed about it." />

      {section.comparison && (
        <div className="mt-5 rounded-2xl bg-ink/5 p-4">
          <p className="kicker !text-[0.68rem]">Comparing the hands</p>
          <p className="mt-1.5 text-sm leading-relaxed">{section.comparison}</p>
        </div>
      )}
    </article>
  )
}

const sourceLabel = (src: ThemeSource, names: Record<FeatureId, string>) => (src === 'shape' ? 'Hand shape' : names[src])

function ThemeCard({ theme, names, onShowLine }: { theme: ThemeSection; names: Record<FeatureId, string>; onShowLine: (id: FeatureId) => void }) {
  const open = (src: ThemeSource) => (src === 'shape' ? scrollToId('report-shape') : onShowLine(src))
  return (
    <article id={`report-theme-${theme.themeId}`} className="card scroll-mt-28 p-5 md:p-7">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-display text-2xl font-normal">{theme.title}</h3>
        <span className="rounded-full border border-accent2/50 bg-accent2/15 px-3 py-1 text-xs font-medium">Traditional reading</span>
      </header>

      <div className="mt-4 rounded-2xl border border-accent2/50 bg-accent2/15 p-4 md:p-5">
        {theme.traditional ? (
          <p className="whitespace-pre-line text-sm leading-relaxed md:text-base">{theme.traditional}</p>
        ) : (
          <p className="text-sm italic text-muted">Not described. What this theme rests on was not seen clearly enough, so nothing is claimed about it.</p>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted">Based on</span>
        {theme.basedOn.length > 0 ? (
          theme.basedOn.map((src) => (
            <button
              key={src}
              type="button"
              onClick={() => open(src)}
              className="inline-flex items-center gap-1.5 rounded-full border border-ink/15 py-0.5 pl-0.5 pr-2.5 text-xs transition-colors hover:border-accent"
            >
              {src === 'shape' ? (
                <span className="grid h-5 w-5 place-items-center rounded-full bg-ink text-paper">
                  <Icon name="hand" size={11} />
                </span>
              ) : (
                <span className="grid h-5 w-5 place-items-center rounded-full bg-ink text-[0.65rem] font-semibold text-paper">{featureNumber(src)}</span>
              )}
              {sourceLabel(src, names)}
            </button>
          ))
        ) : (
          <span className="text-xs text-muted">nothing that was clearly seen</span>
        )}
      </div>
      {theme.leftOut.length > 0 && !theme.traditional && (
        <p className="mt-2 text-xs text-muted">Left out, because it was not clearly seen on either hand: {theme.leftOut.map((src) => sourceLabel(src, names).toLowerCase()).join(', ')}.</p>
      )}
    </article>
  )
}

function ShapeCard({ shape }: { shape: ShapeSection }) {
  return (
    <article id="report-shape" className="card scroll-mt-28 p-5 md:p-7">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-3 font-display text-2xl font-normal">
          <span className="grid h-7 w-7 place-items-center rounded-full bg-ink text-paper">
            <Icon name="hand" size={15} />
          </span>
          Hand shape
        </h3>
      </header>
      <SidePair observed={shape.observed} traditional={shape.traditional} notSeen="Not described. The shape of the hand could not be judged, so nothing is claimed about it." />
      {shape.comparison && (
        <div className="mt-5 rounded-2xl bg-ink/5 p-4">
          <p className="kicker !text-[0.68rem]">Comparing the hands</p>
          <p className="mt-1.5 text-sm leading-relaxed">{shape.comparison}</p>
        </div>
      )}
    </article>
  )
}

type Props = {
  reading: Reading
  selected: FeatureId | null
  onShowLine: (id: FeatureId) => void
  view: ReportView
  onViewChange: (view: ReportView) => void
}

/** The summary is up to two parts: what the app measured (first line), then Gemini's overview when it wrote one (the rest). */
function splitSummary(summary: string) {
  const [lead = '', ...more] = summary.split('\n')
  return { lead, overview: more.join('\n').trim() }
}

/** The report writer as a person would say it. */
function writerName(meta: Reading['meta']) {
  if (meta.provider === 'gemini') return `Gemini · ${meta.model}`
  if (meta.provider === 'knowledge-base') return 'Knowledge base · fixed wording'
  if (meta.mock) return 'Sample stand-in'
  return `${meta.provider} · ${meta.model}`
}

export default function ReportSection({ reading, selected, onShowLine, view, onViewChange }: Props) {
  const { report, meta } = reading
  const names = Object.fromEntries(report.sections.map((s) => [s.featureId, s.title])) as Record<FeatureId, string>
  const { lead, overview } = splitSummary(report.summary)
  return (
    <div>
      <p className="kicker">The reading</p>
      <h2 className="mt-2 font-display text-2xl font-light tracking-tight sm:text-3xl md:text-4xl">What it says, and what it is based on</h2>
      <p className="mt-3 max-w-2xl text-sm text-muted sm:text-base">
        Written {formatDateTime(report.generatedAt)}, only from the findings above. What was seen and what the tradition says are kept apart.
      </p>

      <div className="card mt-6 p-6 md:p-8">
        <p className="kicker">In short</p>
        <p className="mt-3 font-display text-xl font-light leading-snug md:text-2xl">{lead}</p>
        {overview && <p className="mt-4 whitespace-pre-line text-sm leading-relaxed sm:text-base">{overview}</p>}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3">
        <div role="group" aria-label="How to read the report" className="inline-flex rounded-full border border-ink/15 bg-surface/70 p-1 text-sm">
          {(['theme', 'line'] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => onViewChange(v)}
              className={`rounded-full px-5 py-2 transition-colors ${view === v ? 'bg-ink text-paper' : 'text-ink/75 hover:text-ink'}`}
            >
              {v === 'theme' ? 'By theme' : 'By line'}
            </button>
          ))}
        </div>
        <p className="max-w-xl text-xs text-muted sm:text-sm">
          {view === 'theme'
            ? 'Each theme is what the tradition says, built only from the lines that were clearly seen. It is for reflection, not advice or a forecast.'
            : 'One card for each line, with both hands side by side.'}
        </p>
      </div>

      {view === 'theme' ? (
        <div id="report-themes" className="mt-5 scroll-mt-28 space-y-5">
          {report.themes.map((t) => (
            <ThemeCard key={t.themeId} theme={t} names={names} onShowLine={onShowLine} />
          ))}
        </div>
      ) : (
        <div id="report-lines" className="mt-5 scroll-mt-28 space-y-5">
          {report.sections.map((s) => (
            <LineCard key={s.featureId} section={s} selected={selected === s.featureId} onShow={onShowLine} />
          ))}
        </div>
      )}

      <div className="mt-5">
        <ShapeCard shape={report.shape} />
      </div>

      <section id="report-uncertainty" aria-labelledby="unclear-h" className="card mt-5 scroll-mt-28 p-6 md:p-7">
        <h3 id="unclear-h" className="font-display text-2xl font-normal">
          What was unclear or missing
        </h3>
        {report.uncertainty.length > 0 ? (
          <ul className="mt-4 space-y-3 text-sm">
            {report.uncertainty.map((item) => (
              <li key={item} className="flex items-start gap-3">
                <Icon name="info" size={16} className="mt-0.5 shrink-0 text-accent-ink" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-muted">Every line and the hand shape were seen clearly on both hands, so there is nothing to flag.</p>
        )}
      </section>

      <details className="card group mt-5 p-6 md:p-7">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-display text-2xl font-normal">
          How this reading was made
          <Icon name="chevron-down" className="transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-4 space-y-4 text-sm">
          {meta.mock && (
            <p className="rounded-2xl bg-uncertain/15 p-4">
              <strong className="font-medium">Sample reading.</strong> The lines, the hand shape and the report were made by a stand-in, not by measuring a palm in a photo, so treat them as an illustration of the screens, not as a result for this hand. Nothing from a sample reading is ever sent to Gemini.
            </p>
          )}
          {meta.note && (
            <p className="flex items-start gap-3 rounded-2xl bg-ink/5 p-4">
              <Icon name="info" size={16} className="mt-0.5 shrink-0" />
              <span>{meta.note}</span>
            </p>
          )}
          <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-muted">Image pipeline</dt>
              <dd className="mt-1">{meta.pipeline}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-muted">Report writer</dt>
              <dd className="mt-1">{writerName(meta)}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-muted">Knowledge base</dt>
              <dd className="mt-1">{meta.knowledgeBase}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wider text-muted">Instructions</dt>
              <dd className="mt-1">{meta.prompt}</dd>
            </div>
          </dl>
          <ul className="space-y-2 text-muted">
            <li className="flex items-start gap-3">
              <Icon name="check" size={16} className="mt-0.5 shrink-0 text-accent-ink" />
              The photos were processed in memory and discarded. Only the findings, this report and your chats are kept.
            </li>
            <li className="flex items-start gap-3">
              <Icon name="check" size={16} className="mt-0.5 shrink-0 text-accent-ink" />
              {meta.provider === 'gemini'
                ? 'Gemini wrote part of this report. It was sent only the findings, as words: never the photos, your name or your contact details. The sentences about what was seen are written by the app, not by Gemini, and every passage Gemini wrote was checked against the findings and the knowledge base before it was used.'
                : 'The report writer only ever sees the findings, never the photos, and must stay within them.'}
            </li>
            {meta.provider === 'gemini' && (
              <li className="flex items-start gap-3">
                <Icon name="info" size={16} className="mt-0.5 shrink-0 text-accent-ink" />
                Gemini is run by Google. On Google’s free tier, Google may use what it receives to improve its products, and people may read it, so keep private details out of the chat.
              </li>
            )}
            <li className="flex items-start gap-3">
              <Icon name="check" size={16} className="mt-0.5 shrink-0 text-accent-ink" />
              The detection score on a line shows how strongly the detector matched it. It is not the chance that a reading is right.
            </li>
          </ul>
        </div>
      </details>

      <p className="mt-5 flex items-start gap-3 rounded-2xl border border-ink/10 bg-ink/5 p-5 text-sm">
        <Icon name="info" size={18} className="mt-0.5 shrink-0" />
        <span>{report.disclaimer || DISCLAIMER_LONG}</span>
      </p>
    </div>
  )
}
