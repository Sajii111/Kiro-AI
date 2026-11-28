import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api'
import type { Attempt, HandProfile } from '../../api/types'
import { fmtScore, KIND_LABEL, METHOD_NAME, OUTCOME_SHORT, OUTCOME_TONE } from '../../components/palm/palmCopy'
import PlanetAvatar from '../../components/ui/PlanetAvatar'
import Icon from '../../components/ui/icons'
import Spinner from '../../components/ui/Spinner'
import { formatDate, formatDateTime, plural } from '../../lib/format'
import { useResource } from '../../lib/useResource'
import { useData } from '../../state/data'
import { useSession } from '../../state/session'
import { RemoveLockModal } from './LockModals'
import { t, tServer } from '../../i18n'

function OutcomeBadge({ attempt }: { attempt: Attempt }) {
  if (!attempt.outcome) {
    return <span className="inline-flex items-center gap-1.5 rounded-full border border-ink/20 px-2.5 py-1 text-xs">{KIND_LABEL[attempt.kind]}</span>
  }
  const tone = OUTCOME_TONE[attempt.outcome]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${tone.border} ${tone.bg}`}>
      <Icon name={tone.icon} size={12} className={tone.text} /> {OUTCOME_SHORT[attempt.outcome]}
    </span>
  )
}

function LockCard({ profile, guest, onRemove }: { profile: HandProfile; guest: boolean; onRemove: () => void }) {
  return (
    <section aria-labelledby="sec-lock" className="card flex flex-col gap-4 p-6 md:p-8">
      <div className="flex items-center gap-4">
        <PlanetAvatar seed={profile.id} size={52} />
        <div className="min-w-0 flex-1">
          <h2 id="sec-lock" className="truncate font-display text-2xl font-normal">
            {profile.name}
          </h2>
          <p className="text-sm text-muted">
            {profile.lock ? t("Locked with the {side} palm · since {1} · {2}", { side: profile.lock.side, "1": formatDate(profile.lock.createdAt), "2": plural(profile.lock.samples, 'photo') }) : t("No palm lock")}
          </p>
        </div>
        {profile.lock && <span className="rounded-full bg-detected/15 px-2.5 py-1 text-xs">{t("Open now")}</span>}
      </div>
      <p className="break-all font-mono text-xs text-muted" title={t("The user ID of this profile: the Palm lab's test asks for it")}>
        {t("User ID:")}{' '}{profile.id}
      </p>
      {guest ? (
        <p className="text-sm text-muted">{t("Palm locks are for accounts. Create an account to lock a profile.")}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {profile.lock ? (
            <>
              <Link to={`/app/lock/${profile.id}`} className="btn btn-ghost btn-sm">
                <Icon name="swap" size={14} /> {t("Replace lock")}
              </Link>
              <button type="button" onClick={onRemove} className="btn btn-ghost btn-sm">
                <Icon name="x" size={14} /> {t("Take lock off")}
              </button>
            </>
          ) : (
            <Link to={`/app/lock/${profile.id}`} className="btn btn-primary btn-sm">
              <Icon name="shield" size={14} /> {t("Set up a lock")}
            </Link>
          )}
        </div>
      )}
    </section>
  )
}

/**
 * The security page of the open profile: its palm lock and the attempts made on it. Other profiles have their own page, reached
 * by opening them. It holds times, outcomes, scores and thresholds, never a photo.
 */
export default function SecurityPage() {
  const { session } = useSession()
  const { activeProfile } = useData()
  const [removing, setRemoving] = useState<HandProfile | null>(null)
  const profileId = activeProfile?.id
  const signature = `${profileId ?? ''}:${activeProfile?.lock?.createdAt ?? ''}:${activeProfile?.locked ?? ''}`
  const log = useResource(() => (profileId ? api.listActivity(profileId) : Promise.resolve([] as Attempt[])), [profileId, signature])
  const guest = session?.kind === 'guest'

  if (!activeProfile) return null

  return (
    <div className="space-y-8">
      <header>
        <p className="kicker">{t("Security ·")}{' '}{activeProfile.name}</p>
        <h1 className="mt-3 text-balance font-display text-4xl font-light tracking-tight md:text-6xl">{t("Palm lock and attempts")}</h1>
        <p className="mt-3 max-w-2xl text-pretty text-muted">
          {t("This profile’s lock, and every attempt to open it. Other profiles have their own page: open one to see it. No photo is ever kept: only the time, the outcome and the numbers.")}
        </p>
      </header>

      <LockCard profile={activeProfile} guest={guest} onRemove={() => setRemoving(activeProfile)} />

      <section aria-labelledby="sec-log" className="space-y-4">
        <h2 id="sec-log" className="font-display text-2xl font-normal">
          {t("Attempt log")}
        </h2>
        {log.error && <p className="text-danger">{log.error}</p>}
        {log.loading && !log.data ? (
          <Spinner />
        ) : log.data && log.data.length === 0 ? (
          <p className="card p-6 text-muted">{t("Nothing yet. Every unlock, every Palm lab test and every change to this profile’s lock will be listed here.")}</p>
        ) : (
          <div className="card overflow-x-auto">
            <table className="w-full min-w-[46rem] text-left text-sm">
              <thead className="border-b border-ink/10 text-xs uppercase tracking-wider text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">{t("When")}</th>
                  <th className="px-4 py-3 font-medium">{t("User ID")}</th>
                  <th className="px-4 py-3 font-medium">{t("What")}</th>
                  <th className="px-4 py-3 font-medium">{t("Outcome")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("Score / threshold")}</th>
                  <th className="px-4 py-3 text-right font-medium">{t("Time")}</th>
                  <th className="px-4 py-3 font-medium">{t("Attempt ID")}</th>
                </tr>
              </thead>
              <tbody>
                {log.data?.map((a) => (
                  <tr key={a.id} className="border-b border-ink/5 align-top last:border-0">
                    <td className="whitespace-nowrap px-4 py-3">{formatDateTime(a.at)}</td>
                    <td className="break-all px-4 py-3 font-mono text-[11px] text-muted">{a.profileId}</td>
                    <td className="px-4 py-3">
                      {KIND_LABEL[a.kind]}
                      {a.hand && <span className="block text-xs text-muted">{a.hand === 'left' ? t('Left hand') : t('Right hand')}</span>}
                      {a.via && <span className="block text-xs text-muted">{a.via === 'password' ? t('with the password') : t('with the palm')}</span>}
                    </td>
                    <td className="px-4 py-3">
                      <OutcomeBadge attempt={a} />
                      <span className="mt-1 block max-w-[16rem] text-xs text-muted">{tServer(a.reason)}</span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">
                      {a.score !== undefined ? (
                        <>
                          {fmtScore(a.score)} / {fmtScore(a.threshold)}
                          {a.methods && (
                            <span className="block text-[11px] text-muted">
                              {Object.entries(a.methods)
                                .map(([m, v]) => `${METHOD_NAME[m] ?? m} ${fmtScore(v)}`)
                                .join(' · ')}
                            </span>
                          )}
                        </>
                      ) : (
                        '–'
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{a.durationMs !== undefined ? `${a.durationMs} ms` : '–'}</td>
                    <td className="px-4 py-3 font-mono text-[11px] text-muted">{a.id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <RemoveLockModal profile={removing} onClose={() => setRemoving(null)} />
    </div>
  )
}
