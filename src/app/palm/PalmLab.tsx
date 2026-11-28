import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { PalmLockInfo, UnlockEvent } from '../../api/types'
import PalmPhotoInput from '../../components/palm/PalmPhotoInput'
import PalmResultCard from '../../components/palm/PalmResultCard'
import PalmSteps from '../../components/palm/PalmSteps'
import { fmtScore, STAGES } from '../../components/palm/palmCopy'
import Icon from '../../components/ui/icons'
import Spinner from '../../components/ui/Spinner'
import TextField from '../../components/ui/TextField'
import { releasePhoto, type PreparedPhoto } from '../../lib/photo'
import { useResource } from '../../lib/useResource'
import { useData } from '../../state/data'
import { usePalmAttempt } from './usePalmAttempt'
import { t, tServer } from '../../i18n'
import { tx } from '../../i18n/rich'

const MEASURE_LABEL: Record<string, string> = {
  people: t("People"),
  photos: t("Photos"),
  genuine_pairs: t("Same-person pairs"),
  impostor_pairs: t("Different-person pairs"),
  eer: t("Equal error rate"),
  far: t("FAR at the threshold"),
  frr: t("FRR at the threshold"),
  date: t("Measured on"),
}

function pct(v: string | number): string {
  return typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : v
}

function HowItDecides({ info }: { info: PalmLockInfo }) {
  return (
    <section aria-labelledby="lab-how" className="card space-y-6 p-6 md:p-8">
      <div>
        <h2 id="lab-how" className="font-display text-2xl font-normal">
          {t("How the palm lock decides")}
        </h2>
        <p className="mt-2 text-sm text-muted">
          {t('Everything runs on the server, on the photo of this one attempt, which is then thrown away. Engine {engine} (settings {settings}).', { engine: info.engineVersion, settings: info.configHash })}
        </p>
      </div>
      <ol className="grid gap-3 md:grid-cols-5">
        {STAGES.map((s, i) => (
          <li key={s.key} className="rounded-2xl bg-ink/5 p-4 text-sm">
            <span className="text-xs text-muted">{t("Step")}{' '}{i + 1}</span>
            <p className="mt-1 font-medium">{s.title}</p>
            <p className="mt-1 text-xs text-muted">{s.key === 'roi' ? t("{note}, {roiSize} × {roiSize2} pixels", { note: tServer(s.note), roiSize: info.roiSize, roiSize2: info.roiSize }) : tServer(s.note)}</p>
          </li>
        ))}
      </ol>
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="font-medium">{t("The threshold")}</h3>
          <p className="mt-2 font-display text-5xl font-light tabular-nums">{fmtScore(info.threshold)}</p>
          <p className="mt-2 text-sm text-muted">
            {tx('A fused score at or above it is {outcome}. It is set on validation photos, at the equal error rate, and it lives on the server: nobody can change it from here.', { outcome: <em>{t('Authentication Successful')}</em> })}
          </p>
          <p className={`mt-3 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs ${info.calibrated ? 'bg-detected/15' : 'bg-uncertain/15'}`}>
            <Icon name={info.calibrated ? 'check' : 'alert'} size={12} /> {info.calibrated ? t("Calibrated") : t("Not yet calibrated: a placeholder")}
          </p>
          <p className="mt-2 text-xs text-muted">{t("From:")}{' '}{info.calibrationSource}</p>
          {Object.keys(info.measured).length > 0 && (
            <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
              {Object.entries(info.measured)
                .filter(([k]) => k in MEASURE_LABEL)
                .map(([k, v]) => (
                  <div key={k} className="rounded-xl bg-ink/5 px-3 py-2">
                    <dt className="text-xs text-muted">{MEASURE_LABEL[k]}</dt>
                    <dd className="tabular-nums">{['eer', 'far', 'frr'].includes(k) ? pct(v) : String(v)}</dd>
                  </div>
                ))}
            </dl>
          )}
        </div>
        <div>
          <h3 className="font-medium">{t("The methods")}</h3>
          <ul className="mt-3 space-y-3">
            {info.methods.map((m) => (
              <li key={m.id} className="rounded-2xl border border-ink/10 p-4 text-sm">
                <p className="flex items-baseline justify-between gap-3 font-medium">
                  {m.name} <span className="text-xs font-normal text-muted">{m.weight > 0 ? t("counts {0}%", { "0": Math.round(m.weight * 100) }) : t("does not decide")}</span>
                </p>
                <p className="mt-1 text-xs text-muted">{m.description}</p>
              </li>
            ))}
          </ul>
          <h3 className="mt-6 font-medium">{t("The rules")}</h3>
          <ul className="mt-2 space-y-1.5 text-sm text-muted">
            <li>
              • {t('{failures} failed attempts within {window} minutes lock a profile out for {lockout} minutes. An Invalid Image does not count.', { failures: info.policy.failures, window: info.policy.windowMinutes, lockout: info.policy.lockoutMinutes })}
            </li>
            <li>• {t('An unlocked profile locks itself again after {minutes} minutes left alone, and when another profile is opened.', { minutes: info.policy.idleMinutes })}</li>
            <li>
              • {t('A lock is made from {min} to {max} photos of one palm, and every photo must match the others.', { min: info.policy.enrolMin, max: info.policy.enrolMax })}
            </li>
          </ul>
        </div>
      </div>
    </section>
  )
}

/** The Palm lab's test: type a user ID (a profile's ID), add one photo, and see exactly what the lock would decide. */
function TestVerification() {
  const { profiles } = useData()
  const locked = profiles?.filter((p) => p.lock) ?? []
  const [userId, setUserId] = useState('')
  const [photo, setPhoto] = useState<PreparedPhoto | null>(null)
  useEffect(() => () => releasePhoto(photo), [photo])
  const run = useCallback((onEvent: (e: UnlockEvent) => void, signal: AbortSignal) => api.testVerification(userId.trim(), photo!.blob, onEvent, signal), [userId, photo])
  const { state, start, reset } = usePalmAttempt(run)
  const running = state.phase === 'running'

  return (
    <section aria-labelledby="lab-test" className="card space-y-6 p-6 md:p-8">
      <div>
        <h2 id="lab-test" className="font-display text-2xl font-normal">
          {t("Test a verification")}
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-muted">
          {t("One photo against the lock of a user ID, as a lock would judge it. It opens nothing, but it is written to the attempt log and counts toward the lockout like any attempt. An ID that is not a profile of this account is refused, and nothing is compared.")}
        </p>
      </div>
      {state.phase === 'done' ? (
        <>
          <PalmResultCard result={state.result}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setPhoto(null)
                reset()
              }}
            >
              <Icon name="swap" size={16} /> {t("Test another")}
            </button>
          </PalmResultCard>
          <details className="card p-6">
            <summary className="cursor-pointer font-medium">{t("The steps of this attempt")}</summary>
            <div className="mt-4">
              <PalmSteps steps={state.steps} />
            </div>
          </details>
        </>
      ) : (
        <div className="grid gap-6 md:grid-cols-[1fr_1.2fr]">
          <div className="space-y-4">
            <TextField label={t("User ID")} value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="prf_…" autoComplete="off" spellCheck={false} hint={t("The ID shown on a profile's Security page (open the profile first).")} disabled={running} />
            {locked.length > 0 && (
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="text-muted">{t("Locked profiles:")}</span>
                {locked.map((p) => (
                  <button key={p.id} type="button" className="rounded-full border border-ink/20 px-2.5 py-1 hover:border-accent" onClick={() => setUserId(p.id)} disabled={running}>
                    {p.name}
                  </button>
                ))}
              </div>
            )}
            <PalmPhotoInput photo={photo} onPhoto={setPhoto} label={t("Palm photo to test")} disabled={running} />
            {state.phase === 'error' && (
              <p role="alert" className="flex items-start gap-2 rounded-2xl bg-danger/10 p-4 text-sm text-danger">
                <Icon name="alert" size={16} className="mt-0.5 shrink-0" /> {state.message}
              </p>
            )}
            <button type="button" className="btn btn-primary" disabled={!photo || !userId.trim() || running} onClick={() => void start()}>
              {running ? <Spinner /> : <Icon name="spark" size={16} />} {t("Run the test")}
            </button>
          </div>
          <PalmSteps steps={state.phase === 'idle' ? {} : state.steps} />
        </div>
      )}
    </section>
  )
}

/** Palm lab: how the palm lock works and decides (read-only), and a tool to test a verification by user ID. */
export default function PalmLab() {
  const info = useResource(() => api.palmLockInfo(), [])
  return (
    <div className="space-y-8">
      <header>
        <p className="kicker">{t("Palm lab")}</p>
        <h1 className="mt-3 text-balance font-display text-4xl font-light tracking-tight md:text-6xl">{t("Inside the palm lock")}</h1>
        <p className="mt-3 max-w-2xl text-pretty text-muted">{t("The palm lock recognises a palm by its creases. Here is how it decides, and a place to test it.")}</p>
      </header>
      {info.error && <p className="text-danger">{info.error}</p>}
      {info.data && !info.data.available && info.data.note && (
        <p role="alert" className="flex items-start gap-2 rounded-2xl bg-uncertain/15 p-4 text-sm">
          <Icon name="alert" size={16} className="mt-0.5 shrink-0" /> {tServer(info.data.note)}
        </p>
      )}
      {info.data?.available && info.data.note && <p className="rounded-2xl bg-ink/5 p-4 text-sm text-muted">{tServer(info.data.note)}</p>}
      {info.data ? <HowItDecides info={info.data} /> : !info.error && <Spinner />}
      <TestVerification />
    </div>
  )
}
