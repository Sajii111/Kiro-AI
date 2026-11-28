import type { PalmResult } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import Icon from '../ui/icons'
import { fmtScore, METHOD_NAME, OUTCOME_TONE } from './palmCopy'
import { t, tServer } from '../../i18n'

/** A bar from 0 to 1 with the threshold marked on it. */
function ScoreBar({ value, threshold, label }: { value: number; threshold?: number; label: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span>{label}</span>
        <span className="font-display text-lg tabular-nums">{fmtScore(value)}</span>
      </div>
      <div className="relative mt-1.5 h-2.5 rounded-full bg-ink/10" role="img" aria-label={`${label}: ${fmtScore(value)} out of 1${threshold !== undefined ? t(", threshold {0}", { "0": fmtScore(threshold) }) : ''}`}>
        <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }} />
        {threshold !== undefined && <div className="absolute -top-1 h-4.5 w-0.5 rounded bg-ink" style={{ left: `calc(${threshold * 100}% - 1px)` }} title={t("Threshold {0}", { "0": fmtScore(threshold) })} />}
      </div>
    </div>
  )
}

/**
 * The answer to a palm attempt: the outcome in the brief's words, the score against the threshold, each method's score, the
 * time it took and the attempt ID (the same ID as in the attempt log).
 */
export default function PalmResultCard({ result, children }: { result: PalmResult; children?: React.ReactNode }) {
  const tone = OUTCOME_TONE[result.outcome]
  return (
    <section aria-live="assertive" className={`card overflow-hidden border-2 ${tone.border}`}>
      <div className={`flex items-center gap-4 p-6 ${tone.bg}`}>
        <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-full border-2 ${tone.border} ${tone.text}`}>
          <Icon name={tone.icon} size={24} />
        </span>
        <div className="min-w-0">
          <h2 className="font-display text-2xl font-normal md:text-3xl">{result.title}</h2>
          <p className="mt-1 text-sm text-muted">{tServer(result.reason)}</p>
        </div>
      </div>

      <div className="grid gap-6 p-6 md:grid-cols-2">
        <div className="space-y-4">
          {result.score !== undefined ? (
            <>
              <ScoreBar value={result.score} threshold={result.threshold} label={t("Match score")} />
              <p className="text-xs text-muted">
                {t('The line on the bar is the threshold, {threshold}: a score at or above it opens the lock.', { threshold: fmtScore(result.threshold) })}
                {!result.calibrated && t(" The threshold is still a placeholder until it is measured on real validation photos.")}
              </p>
              <div className="space-y-3 border-t border-ink/10 pt-4">
                {Object.entries(result.methods).map(([m, v]) => (
                  <ScoreBar key={m} value={v} label={METHOD_NAME[m] ?? m} />
                ))}
              </div>
            </>
          ) : (
            <p className="rounded-2xl bg-ink/5 p-4 text-sm">{t("No score: the photo could not be judged, so nothing was compared. This does not count as a failed attempt.")}</p>
          )}
        </div>
        <dl className="grid grid-cols-2 content-start gap-3 text-sm">
          <div className="rounded-2xl bg-ink/5 p-3">
            <dt className="text-xs uppercase tracking-wider text-muted">{t("Threshold")}</dt>
            <dd className="mt-0.5 font-display text-xl tabular-nums">{fmtScore(result.threshold)}</dd>
          </div>
          <div className="rounded-2xl bg-ink/5 p-3">
            <dt className="text-xs uppercase tracking-wider text-muted">{t("Time")}</dt>
            <dd className="mt-0.5 font-display text-xl tabular-nums">{result.durationMs} {t("ms")}</dd>
          </div>
          <div className="rounded-2xl bg-ink/5 p-3">
            <dt className="text-xs uppercase tracking-wider text-muted">{t("Hand")}</dt>
            <dd className="mt-0.5 capitalize">{t(result.hand)}</dd>
          </div>
          <div className="rounded-2xl bg-ink/5 p-3">
            <dt className="text-xs uppercase tracking-wider text-muted">{t("When")}</dt>
            <dd className="mt-0.5">{formatDateTime(result.at)}</dd>
          </div>
          <div className="col-span-2 rounded-2xl bg-ink/5 p-3">
            <dt className="text-xs uppercase tracking-wider text-muted">{t("Attempt ID")}</dt>
            <dd className="mt-0.5 break-all font-mono text-xs">{result.attemptId}</dd>
          </div>
          {Object.keys(result.raw).length > 0 && (
            <div className="col-span-2 rounded-2xl bg-ink/5 p-3">
              <dt className="text-xs uppercase tracking-wider text-muted">{t("Raw similarities")}</dt>
              <dd className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                {Object.entries(result.raw).map(([m, v]) => (
                  <span key={m}>
                    {METHOD_NAME[m] ?? m} <span className="tabular-nums">{v.toFixed(3)}</span>
                  </span>
                ))}
              </dd>
            </div>
          )}
        </dl>
      </div>
      {result.lockedUntil && (
        <p className="mx-6 mb-6 flex items-start gap-2 rounded-2xl bg-danger/10 p-4 text-sm text-danger">
          <Icon name="alert" size={16} className="mt-0.5 shrink-0" /> {t('Too many failed attempts: this profile is locked out until {when}.', { when: formatDateTime(new Date(result.lockedUntil).toISOString()) })}
        </p>
      )}
      {children && <div className="flex flex-wrap gap-3 border-t border-ink/10 p-6">{children}</div>}
    </section>
  )
}
