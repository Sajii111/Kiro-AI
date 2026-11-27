import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../../api'
import { ApiError, errorMessage } from '../../api/errors'
import type { HandSide, PalmLockInfo } from '../../api/types'
import PalmPhotoInput from '../../components/palm/PalmPhotoInput'
import ChoiceCard from '../../components/ui/ChoiceCard'
import Icon from '../../components/ui/icons'
import PlanetAvatar from '../../components/ui/PlanetAvatar'
import Spinner from '../../components/ui/Spinner'
import { useToast } from '../../components/ui/Toast'
import { plural } from '../../lib/format'
import { releasePhoto, type PreparedPhoto } from '../../lib/photo'
import { useResource } from '../../lib/useResource'
import { useData } from '../../state/data'
import { useSession } from '../../state/session'

const MOST = 5

/**
 * Locking a profile with a palm (enrolment): which hand, consent, then three to five photos of that palm. The server checks
 * each photo, makes sure they all show the same palm, and keeps only an encrypted template made from them.
 */
export default function LockSetup() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const { session } = useSession()
  const { profiles, refresh } = useData()
  const profile = profiles?.find((p) => p.id === id) ?? null
  const info = useResource<PalmLockInfo>(() => api.palmLockInfo(), [])
  const need = info.data?.policy.enrolMin ?? 3

  const [side, setSide] = useState<HandSide>('right')
  const [consent, setConsent] = useState(false)
  const [photos, setPhotos] = useState<(PreparedPhoto | null)[]>(() => Array(MOST).fill(null))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [photoErrors, setPhotoErrors] = useState<Record<number, string>>({})
  // the photos chosen so far, for freeing their temporary addresses when the page closes
  const kept = useRef(photos)
  useEffect(() => {
    kept.current = photos
  }, [photos])
  useEffect(() => () => kept.current.forEach(releasePhoto), [])

  const chosen = photos.filter((p): p is PreparedPhoto => !!p)

  const setPhoto = (i: number, photo: PreparedPhoto | null) => {
    setPhotos((all) => {
      const next = [...all]
      releasePhoto(next[i])
      next[i] = photo
      return next
    })
    setPhotoErrors((e) => {
      const rest = { ...e }
      delete rest[i]
      return rest
    })
  }

  const submit = async () => {
    if (!profile) return
    setError(null)
    if (!consent) {
      setError(profile.owner === 'self' ? 'Please confirm that you agree to your palm being used as a lock.' : `Please confirm that ${profile.name} has agreed to their palm being used as a lock.`)
      return
    }
    if (chosen.length < need) {
      setError(`Add at least ${need} photos of the same palm.`)
      return
    }
    setBusy(true)
    setPhotoErrors({})
    // which slot each sent photo came from, so a problem points at the right picture
    const slots = photos.flatMap((p, i) => (p ? [i] : []))
    try {
      await api.lockProfile(profile.id, { side, consent, photos: chosen.map((p) => p.blob) })
      refresh()
      toast(`${profile.name} is now locked with the ${side} palm.`)
      navigate('/app')
    } catch (e) {
      setError(errorMessage(e))
      if (e instanceof ApiError && e.details.photos) {
        setPhotoErrors(Object.fromEntries(e.details.photos.map((p) => [slots[p.index] ?? p.index, p.message])))
      }
      setBusy(false)
    }
  }

  if (!profiles) {
    return (
      <p className="flex items-center gap-2 text-muted">
        <Spinner /> Loading…
      </p>
    )
  }
  if (!profile) {
    return (
      <div className="card p-8">
        <h1 className="font-display text-3xl">That profile could not be found</h1>
        <Link to="/app" className="btn btn-ghost mt-6">
          <Icon name="arrow-left" size={16} /> Back to your profiles
        </Link>
      </div>
    )
  }
  if (session?.kind !== 'user') {
    return (
      <div className="card p-8">
        <h1 className="font-display text-3xl">Palm locks are for accounts</h1>
        <p className="mt-2 max-w-xl text-muted">A guest session is temporary, and its lock would go with it. Create an account (your guest readings can come with you), then lock a profile.</p>
        <Link to="/signin" state={{ mode: 'signup', from: `/app/lock/${profile.id}` }} className="btn btn-primary mt-6">
          Create an account
        </Link>
      </div>
    )
  }
  if (profile.locked) {
    return (
      <div className="card p-8">
        <h1 className="font-display text-3xl">Unlock {profile.name} first</h1>
        <p className="mt-2 text-muted">A new lock replaces the old one, so the palm that locks it now must be shown first.</p>
        <Link to={`/app/unlock/${profile.id}?next=${encodeURIComponent(`/app/lock/${profile.id}`)}`} className="btn btn-primary mt-6">
          <Icon name="shield" size={16} /> Unlock {profile.name}
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <header className="flex flex-wrap items-center gap-5">
        <PlanetAvatar seed={profile.id} size={64} />
        <div className="min-w-0 flex-1">
          <p className="kicker">Palm lock</p>
          <h1 className="mt-2 text-balance font-display text-4xl font-light tracking-tight md:text-5xl">{profile.lock ? `Replace ${profile.name}’s lock` : `Lock ${profile.name} with a palm`}</h1>
          <p className="mt-2 max-w-2xl text-muted">
            Once locked, {profile.name}’s readings and chats open only after the palm is shown, in each browser, and lock again after {info.data?.policy.idleMinutes ?? 15} minutes left alone.
          </p>
        </div>
      </header>

      {info.data && !info.data.available && (
        <p role="alert" className="flex items-start gap-2 rounded-2xl bg-uncertain/15 p-4 text-sm">
          <Icon name="alert" size={16} className="mt-0.5 shrink-0" /> {info.data.note}
        </p>
      )}

      <section className="card space-y-6 p-6 md:p-8">
        <fieldset>
          <legend className="mb-2 font-medium">1. Which hand?</legend>
          <div className="grid max-w-md grid-cols-2 gap-3">
            {(['right', 'left'] as const).map((value) => (
              <ChoiceCard key={value} name="side" value={value} checked={side === value} onChange={() => setSide(value)} title={value === 'right' ? 'Right hand' : 'Left hand'} note={value === 'right' ? 'Recommended' : 'If the right hand is not possible'} />
            ))}
          </div>
        </fieldset>

        <div>
          <p className="mb-2 font-medium">
            2. {need} to {MOST} photos of the {side} palm
          </p>
          <p className="mb-4 text-sm text-muted">The same palm each time, flat and open, fingers together, plain background, even light. Move the hand away and back between photos, so they are not all the same.</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
            {photos.map((p, i) => (
              <PalmPhotoInput key={i} photo={p} onPhoto={(photo) => setPhoto(i, photo)} label={`Photo ${i + 1}${i < need ? '' : ' (optional)'}`} error={photoErrors[i]} side={side} compact disabled={busy} />
            ))}
          </div>
        </div>

        <label className="flex cursor-pointer items-start gap-3 rounded-2xl bg-accent2/20 p-4 text-sm">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--accent-ink)]" disabled={busy} />
          <span>
            <strong className="font-medium">{profile.owner === 'self' ? 'I agree' : `${profile.name} has agreed`}</strong> to {profile.owner === 'self' ? 'my' : 'their'} palm being used as a lock.
            <span className="mt-1 block text-xs text-muted">
              Only an encrypted template is kept: numbers made from the palm’s creases, which cannot be turned back into a photo. The photos are thrown away straight after. Taking the lock off deletes the template.
            </span>
          </span>
        </label>

        {error && (
          <p role="alert" className="flex items-start gap-2 text-sm text-danger">
            <Icon name="alert" className="mt-0.5 shrink-0" /> {error}
          </p>
        )}

        <div className="flex flex-wrap justify-end gap-3">
          <Link to="/app" className="btn btn-ghost">
            Cancel
          </Link>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={busy || chosen.length < need}>
            {busy ? <Spinner /> : <Icon name="shield" size={16} />} {busy ? 'Checking the photos…' : `Lock with ${plural(chosen.length || need, 'photo')}`}
          </button>
        </div>
      </section>
    </div>
  )
}
