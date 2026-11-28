import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../../api'
import type { UnlockEvent } from '../../api/types'
import PalmPhotoInput from '../../components/palm/PalmPhotoInput'
import PalmResultCard from '../../components/palm/PalmResultCard'
import PalmSteps from '../../components/palm/PalmSteps'
import PlanetAvatar from '../../components/ui/PlanetAvatar'
import Icon from '../../components/ui/icons'
import Spinner from '../../components/ui/Spinner'
import { formatDate, plural } from '../../lib/format'
import { releasePhoto, type PreparedPhoto } from '../../lib/photo'
import { useData } from '../../state/data'
import { RemoveLockModal } from './LockModals'
import { usePalmAttempt } from './usePalmAttempt'
import { t } from '../../i18n'
import { tx } from '../../i18n/rich'

/** Only paths inside the app may be returned to after unlocking. */
function safeNext(next: string | null): string {
  return next && next.startsWith('/app') && !next.startsWith('//') ? next : '/app'
}

/**
 * Unlocking a profile with its palm: one photo, the five steps as they happen, then the outcome with its score, the
 * threshold and each method's score. A success opens the profile in this browser.
 */
export default function UnlockPage() {
  const { id = '' } = useParams()
  const [search] = useSearchParams()
  const next = safeNext(search.get('next'))
  const navigate = useNavigate()
  const { profiles, refresh } = useData()
  const profile = profiles?.find((p) => p.id === id) ?? null
  const [photo, setPhoto] = useState<PreparedPhoto | null>(null)
  const [removing, setRemoving] = useState(false)

  useEffect(() => () => releasePhoto(photo), [photo])

  const run = useCallback((onEvent: (e: UnlockEvent) => void, signal: AbortSignal) => api.unlockProfile(id, photo!.blob, onEvent, signal), [id, photo])
  const { state, start, reset } = usePalmAttempt(run)

  const go = async () => {
    const result = await start()
    if (result?.opened) refresh()
  }

  if (!profiles) {
    return (
      <p className="flex items-center gap-2 text-muted">
        <Spinner /> {t("Loading…")}
      </p>
    )
  }
  if (!profile) {
    return (
      <div className="card p-8">
        <h1 className="font-display text-3xl">{t("That profile could not be found")}</h1>
        <Link to="/app" className="btn btn-ghost mt-6">
          <Icon name="arrow-left" size={16} /> {t("Back to your profiles")}
        </Link>
      </div>
    )
  }
  if (!profile.lock) {
    return (
      <div className="card p-8">
        <h1 className="font-display text-3xl">{t('{name} has no palm lock', { name: profile.name })}</h1>
        <p className="mt-2 text-muted">{t("There is nothing to unlock. You can open it from your profiles, or set up a lock for it.")}</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link to="/app" className="btn btn-ghost">
            <Icon name="arrow-left" size={16} /> {t("Your profiles")}
          </Link>
          <Link to={`/app/lock/${profile.id}`} className="btn btn-primary">
            <Icon name="shield" size={16} /> {t("Set up a palm lock")}
          </Link>
        </div>
      </div>
    )
  }

  const running = state.phase === 'running'
  const side = profile.lock.side

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header className="flex flex-wrap items-center gap-5">
        <PlanetAvatar seed={profile.id} size={64} />
        <div className="min-w-0 flex-1">
          <p className="kicker">{t("Palm lock")}</p>
          <h1 className="mt-2 text-balance font-display text-4xl font-light tracking-tight md:text-5xl">{t('Unlock {name}', { name: profile.name })}</h1>
          <p className="mt-2 text-muted">
            {tx('Show the {palm} this profile was locked with (on {date}, from {count}).', {
              palm: <strong className="font-medium text-ink">{side === 'left' ? t('left palm') : t('right palm')}</strong>,
              date: formatDate(profile.lock.createdAt),
              count: plural(profile.lock.samples, 'photo'),
            })}
          </p>
        </div>
      </header>

      {state.phase === 'idle' && profile.open && (
        <p className="flex flex-wrap items-center gap-3 rounded-2xl bg-detected/10 p-4 text-sm">
          <Icon name="check" size={16} className="text-detected" /> {t('{name} is already unlocked in this browser.', { name: profile.name })}
          <button type="button" className="btn btn-ghost btn-sm ml-auto" onClick={() => navigate(next)}>
            {t('Go to {name}', { name: profile.name })} <Icon name="arrow-right" size={14} />
          </button>
        </p>
      )}

      {state.phase === 'done' ? (
        <>
          <PalmResultCard result={state.result}>
            {state.result.opened ? (
              <button type="button" className="btn btn-primary" onClick={() => navigate(next)}>
                {t('Go to {name}', { name: profile.name })} <Icon name="arrow-right" size={16} />
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setPhoto(null)
                  reset()
                }}
              >
                <Icon name="swap" size={16} /> {t("Try another photo")}
              </button>
            )}
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
            <PalmPhotoInput photo={photo} onPhoto={setPhoto} label={t("Photo of the {side} palm", { side: side })} side={side} disabled={running} />
            <ul className="space-y-1.5 text-sm text-muted">
              <li>• {side === 'left' ? t('The left palm, flat and open, fingers together, facing the camera') : t('The right palm, flat and open, fingers together, facing the camera')}</li>
              <li>• {t('Plain background, even light, the whole hand in the frame')}</li>
              <li>• {t('Use the normal camera, not selfie mode (it can mirror the hand)')}</li>
            </ul>
            {state.phase === 'error' && (
              <p role="alert" className="flex items-start gap-2 rounded-2xl bg-danger/10 p-4 text-sm text-danger">
                <Icon name="alert" size={16} className="mt-0.5 shrink-0" /> {state.message}
              </p>
            )}
            <div className="flex flex-wrap gap-3">
              <button type="button" className="btn btn-primary" disabled={!photo || running} onClick={go}>
                {running ? <Spinner /> : <Icon name="shield" size={16} />} {t("Unlock")}
              </button>
              <Link to="/app" className="btn btn-ghost">
                {t("Cancel")}
              </Link>
            </div>
          </div>
          <div>
            <PalmSteps steps={state.phase === 'idle' ? {} : state.steps} />
            <p className="mt-4 text-xs text-muted">{t("The photo is used for this attempt only and thrown away. The attempt itself (time, score, outcome) is written to the attempt log.")}</p>
          </div>
        </div>
      )}
      {!profile.open && (
        <p className="text-sm text-muted">
          {t("Cannot show the palm (the lock is from an older version of the palm lock, or the hand is hurt)?")}{' '}
          {tx('{button}, then set it up again.', {
            button: (
              <button type="button" className="underline hover:text-ink" disabled={running} onClick={() => setRemoving(true)}>
                {t('Take the lock off with your account password')}
              </button>
            ),
          })}
        </p>
      )}
      <RemoveLockModal profile={removing ? profile : null} onClose={() => setRemoving(false)} />
    </div>
  )
}
