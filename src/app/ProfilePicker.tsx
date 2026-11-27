import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { HandProfile } from '../api/types'
import PlanetAvatar from '../components/ui/PlanetAvatar'
import Icon from '../components/ui/icons'
import Spinner from '../components/ui/Spinner'
import { greeting, plural, relativeDay } from '../lib/format'
import { useData } from '../state/data'
import { useSession } from '../state/session'
import { CreateProfileModal, DeleteProfileModal, RenameProfileModal } from './ProfileModals'

/** Set once a profile was entered in this tab, so a person who comes back to choose is not sent straight in again. */
const CHOSE_KEY = 'kiro-chose-profile'

function chose(): boolean {
  try {
    return sessionStorage.getItem(CHOSE_KEY) === '1'
  } catch {
    return false
  }
}

function markChosen() {
  try {
    sessionStorage.setItem(CHOSE_KEY, '1')
  } catch {
    /* private browsing */
  }
}

function ProfileTile({ profile, canLock, opening, onEnter, onRename, onDelete }: { profile: HandProfile; canLock: boolean; opening: boolean; onEnter: () => void; onRename: () => void; onDelete: () => void }) {
  const locked = profile.locked
  return (
    <li className="card group relative flex flex-col p-6 transition-[border-color,box-shadow] hover:border-accent">
      {/* the whole tile goes into the profile (a stretched button); the small actions sit above it */}
      <button type="button" onClick={onEnter} className="flex flex-col items-center gap-4 text-center after:absolute after:inset-0 after:rounded-[inherit] after:content-['']" aria-label={locked ? `Unlock ${profile.name} with the palm` : `Open ${profile.name}`} data-cursor>
        <span className="relative">
          <PlanetAvatar seed={profile.id} size={96} />
          {profile.lock && (
            <span className={`absolute -bottom-1 -right-1 grid h-8 w-8 place-items-center rounded-full border-2 border-surface ${locked ? 'bg-ink text-paper' : 'bg-detected text-paper'}`} title={locked ? 'Locked with a palm' : 'Palm lock on, unlocked here'}>
              <Icon name="shield" size={15} />
            </span>
          )}
        </span>
        <span>
          <span className="block font-display text-2xl">{profile.name}</span>
          <span className="block text-sm text-muted">{profile.owner === 'self' ? 'My hands' : 'Shared with permission'}</span>
        </span>
        <span className="text-sm text-muted">
          {locked
            ? `Locked with the ${profile.lock?.side} palm`
            : profile.readingCount === 0
              ? 'No readings yet'
              : `${plural(profile.readingCount, 'reading')} · latest ${profile.lastReadingAt ? relativeDay(profile.lastReadingAt) : ''}`}
        </span>
        <span className={`btn btn-sm ${locked ? 'btn-primary' : 'btn-ghost'}`}>
          {opening ? <Spinner /> : <Icon name={locked ? 'shield' : 'arrow-right'} size={15} />} {locked ? 'Unlock with palm' : 'Open'}
        </span>
      </button>
      <span className="relative z-10 mt-4 flex justify-center gap-1 border-t border-ink/10 pt-3">
        {canLock && !locked && (
          <Link to={`/app/lock/${profile.id}`} aria-label={profile.lock ? `Replace the palm lock of ${profile.name}` : `Lock ${profile.name} with a palm`} title={profile.lock ? 'Replace the palm lock' : 'Lock with a palm'} className="grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-ink/5 hover:text-ink">
            <Icon name="shield" size={16} />
          </Link>
        )}
        {!locked && (
          <button type="button" onClick={onRename} aria-label={`Rename ${profile.name}`} title="Rename" className="grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-ink/5 hover:text-ink">
            <Icon name="pencil" size={16} />
          </button>
        )}
        <button type="button" onClick={onDelete} aria-label={`Delete ${profile.name}`} title="Delete" className="grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-danger/10 hover:text-danger">
          <Icon name="trash" size={16} />
        </button>
      </span>
    </li>
  )
}

/**
 * The first screen of the app: whose palms? Each hand profile is a tile. Choosing one goes inside it (after the palm, when
 * it is locked), and everything from then on (home, new reading, chat, history) is that profile's. With a single profile
 * that has no lock, the app goes straight in.
 */
export default function ProfilePicker() {
  const { session } = useSession()
  const { profiles, profilesError, openingId, setActiveProfileId, refresh } = useData()
  const [creating, setCreating] = useState(false)
  const [renaming, setRenaming] = useState<HandProfile | null>(null)
  const [deleting, setDeleting] = useState<HandProfile | null>(null)
  const [loadingSamples, setLoadingSamples] = useState(false)
  const name = session?.kind === 'user' ? session.user.displayName : null
  const demo = api.demo

  const enter = (p: HandProfile) => {
    markChosen()
    setActiveProfileId(p.id)
  }

  // one profile, no lock, first time in this tab: there is nothing to choose, so go straight in
  useEffect(() => {
    if (profiles && profiles.length === 1 && !profiles[0].locked && !chose()) {
      markChosen()
      setActiveProfileId(profiles[0].id)
    }
  }, [profiles, setActiveProfileId])

  const loadSamples = async () => {
    if (!demo) return
    setLoadingSamples(true)
    await demo.loadSamples()
    refresh()
    setLoadingSamples(false)
  }

  return (
    <div className="space-y-10">
      <header className="text-center">
        <p className="kicker justify-center">{session?.kind === 'guest' ? 'Guest session' : name ? `${greeting()}, ${name}` : greeting()}</p>
        <h1 className="mt-3 text-balance font-display text-4xl font-light tracking-tight md:text-6xl">Whose palms today?</h1>
        <p className="mx-auto mt-3 max-w-xl text-muted">Choose a hand profile to go inside it. A locked profile opens with its palm.</p>
      </header>

      {profilesError && (
        <p role="alert" className="flex items-center justify-center gap-2 text-sm text-danger">
          <Icon name="alert" /> {profilesError}
        </p>
      )}

      {profiles === null ? (
        <div className="mx-auto grid max-w-5xl gap-5 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card h-72 animate-pulse bg-ink/5" />
          ))}
        </div>
      ) : profiles.length === 0 ? (
        <div className="card mx-auto flex max-w-2xl flex-col items-center gap-5 p-10 text-center">
          <h2 className="font-display text-2xl font-normal">Start with a hand profile</h2>
          <p className="text-muted">A profile is one person&apos;s pair of hands: yours, or someone who has said yes. Each has its own readings and chats, so nothing gets mixed up.</p>
          <div className="flex flex-wrap justify-center gap-3">
            <button type="button" onClick={() => setCreating(true)} className="btn btn-primary">
              <Icon name="plus" size={16} /> Create a profile
            </button>
            {demo && (
              <button type="button" onClick={loadSamples} disabled={loadingSamples} className="btn btn-ghost">
                {loadingSamples && <Spinner />} Load sample profiles
              </button>
            )}
          </div>
        </div>
      ) : (
        <ul className="mx-auto grid max-w-5xl gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {profiles.map((p) => (
            <ProfileTile key={p.id} profile={p} canLock={session?.kind === 'user'} opening={openingId === p.id} onEnter={() => enter(p)} onRename={() => setRenaming(p)} onDelete={() => setDeleting(p)} />
          ))}
          <li>
            <button type="button" onClick={() => setCreating(true)} className="flex h-full min-h-72 w-full flex-col items-center justify-center gap-3 rounded-[1.75rem] border-2 border-dashed border-ink/20 p-6 text-muted transition-colors hover:border-accent hover:text-ink">
              <span className="grid h-16 w-16 place-items-center rounded-full border border-ink/20">
                <Icon name="plus" size={26} />
              </span>
              <span className="font-medium">Add a profile</span>
            </button>
          </li>
        </ul>
      )}

      <CreateProfileModal open={creating} onClose={() => setCreating(false)} onCreated={() => markChosen()} />
      <RenameProfileModal profile={renaming} onClose={() => setRenaming(null)} />
      <DeleteProfileModal profile={deleting} onClose={() => setDeleting(null)} />
    </div>
  )
}
