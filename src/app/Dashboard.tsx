import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { HandProfile, ReadingSummary } from '../api/types'
import StatusDot from '../components/StatusDot'
import PlanetAvatar from '../components/ui/PlanetAvatar'
import Icon from '../components/ui/icons'
import Spinner from '../components/ui/Spinner'
import { formatDate, greeting, plural, relativeDay } from '../lib/format'
import { useResource } from '../lib/useResource'
import { useData } from '../state/data'
import { useSession } from '../state/session'
import { CreateProfileModal, DeleteProfileModal, RenameProfileModal } from './ProfileModals'

function ProfileCard({
  profile,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  profile: HandProfile
  active: boolean
  onSelect: () => void
  onRename: () => void
  onDelete: () => void
}) {
  const navigate = useNavigate()
  return (
    <li
      className={`card group flex flex-col p-5 transition-[border-color,box-shadow] ${active ? 'border-accent shadow-[0_0_0_1px_var(--accent)]' : 'hover:border-ink/25'}`}
    >
      <button type="button" onClick={onSelect} aria-pressed={active} className="flex items-center gap-4 text-left" data-cursor>
        <PlanetAvatar seed={profile.id} size={56} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-display text-xl">{profile.name}</span>
          <span className="block text-sm text-muted">{profile.owner === 'self' ? 'My hands' : 'Shared with permission'}</span>
        </span>
        {active && <span className="rounded-full bg-accent/25 px-3 py-1 text-xs font-medium text-accent-ink">Active</span>}
      </button>

      <p className="mt-4 text-sm text-muted">
        {profile.readingCount === 0 ? 'No readings yet' : `${plural(profile.readingCount, 'reading')} · latest: ${profile.lastReadingAt ? relativeDay(profile.lastReadingAt) : ''}`}
      </p>

      <div className="mt-5 flex items-center gap-2">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => {
            onSelect()
            navigate('/app/new')
          }}
        >
          <Icon name="plus" size={15} /> New reading
        </button>
        <span className="ml-auto flex gap-1">
          <button type="button" onClick={onRename} aria-label={`Rename ${profile.name}`} title="Rename" className="grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-ink/5 hover:text-ink">
            <Icon name="pencil" size={16} />
          </button>
          <button type="button" onClick={onDelete} aria-label={`Delete ${profile.name}`} title="Delete" className="grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-danger/10 hover:text-danger">
            <Icon name="trash" size={16} />
          </button>
        </span>
      </div>
    </li>
  )
}

function ReadingRow({ reading }: { reading: ReadingSummary }) {
  const when = formatDate(reading.createdAt)
  return (
    // the whole row opens the reading (a stretched link); the Chat button sits above it and has its own target
    <li className="card group relative flex flex-wrap items-center gap-x-6 gap-y-3 p-5 transition-colors hover:border-accent">
      <Link to={`/app/readings/${reading.id}`} className="min-w-0 flex-1 basis-60 after:absolute after:inset-0 after:rounded-[inherit] after:content-['']" data-cursor>
        <span className="block font-display text-lg [overflow-wrap:anywhere]">{reading.name ?? reading.headline}</span>
        <span className="block text-sm text-muted">
          {reading.profileName} · {when}
          {reading.name ? ` · ${reading.headline}` : ''}
        </span>
      </Link>
      <span className="flex items-center gap-4 text-sm" role="img" aria-label={`${reading.counts.detected} detected, ${reading.counts.uncertain} uncertain, ${reading.counts.not_visible} not visible`}>
        <span className="flex items-center gap-1.5"><StatusDot status="detected" /> {reading.counts.detected}</span>
        <span className="flex items-center gap-1.5"><StatusDot status="uncertain" /> {reading.counts.uncertain}</span>
        <span className="flex items-center gap-1.5"><StatusDot status="not_visible" /> {reading.counts.not_visible}</span>
      </span>
      <Link
        to={`/app/chat?reading=${reading.id}`}
        aria-label={`Chat about ${reading.name ? `“${reading.name}”` : `the reading of ${when}`}${reading.conversationCount > 0 ? ` (${plural(reading.conversationCount, 'chat')} so far)` : ''}`}
        title="Chat about this reading"
        className="btn btn-ghost btn-sm relative z-10"
      >
        <Icon name="chat" size={15} /> Chat
        {reading.conversationCount > 0 && <span className="text-muted">{reading.conversationCount}</span>}
      </Link>
      <Icon name="arrow-right" className="text-muted" />
    </li>
  )
}

export default function Dashboard() {
  const { session } = useSession()
  const { profiles, profilesError, activeProfile, setActiveProfileId, refresh } = useData()
  const [creating, setCreating] = useState(false)
  const [renaming, setRenaming] = useState<HandProfile | null>(null)
  const [deleting, setDeleting] = useState<HandProfile | null>(null)
  const [loadingSamples, setLoadingSamples] = useState(false)

  // reload the readings whenever a profile is added or deleted, or its reading count changes
  const signature = profiles?.map((p) => `${p.id}:${p.readingCount}`).join(',') ?? 'loading'
  const readings = useResource(() => api.listReadings(activeProfile?.id), [activeProfile?.id, signature])

  const name = session?.kind === 'user' ? session.user.displayName : null
  const demo = api.demo

  const loadSamples = async () => {
    if (!demo) return
    setLoadingSamples(true)
    await demo.loadSamples()
    refresh()
    setLoadingSamples(false)
  }

  return (
    <div className="space-y-14">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="kicker">{session?.kind === 'guest' ? 'Guest session' : 'Your readings'}</p>
          <h1 className="mt-3 text-balance font-display text-4xl font-light tracking-tight md:text-6xl">{name ? `${greeting()}, ${name}.` : `${greeting()}.`}</h1>
          <p className="mt-3 max-w-xl text-muted">Choose a hand profile, then look back at its readings or start a new one.</p>
        </div>
        {profiles && profiles.length > 0 && (
          <div className="flex flex-wrap gap-3">
            <Link to="/app/chat" className="btn btn-ghost !px-6 !py-4">
              <Icon name="chat" size={17} /> Chat about a reading
            </Link>
            <Link to="/app/new" className="btn btn-primary !px-7 !py-4">
              <Icon name="plus" size={17} /> New reading
            </Link>
          </div>
        )}
      </div>

      {profilesError && (
        <p role="alert" className="flex items-center gap-2 text-sm text-danger">
          <Icon name="alert" /> {profilesError}
        </p>
      )}

      {/* ----------------------------------------------------------- profiles */}
      <section aria-labelledby="profiles-h">
        <div className="mb-5 flex items-center justify-between gap-4">
          <h2 id="profiles-h" className="font-display text-2xl font-normal">
            Hand profiles
          </h2>
          {profiles && profiles.length > 0 && (
            <button type="button" onClick={() => setCreating(true)} className="btn btn-ghost btn-sm">
              <Icon name="plus" size={15} /> Add a profile
            </button>
          )}
        </div>

        {profiles === null ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
            {[0, 1].map((i) => (
              <div key={i} className="card h-44 animate-pulse bg-ink/5" />
            ))}
          </div>
        ) : profiles.length === 0 ? (
          <div className="card flex flex-col items-start gap-5 p-8 md:flex-row md:items-center md:justify-between md:p-10">
            <div className="max-w-xl">
              <h3 className="font-display text-2xl font-normal">Start with a hand profile</h3>
              <p className="mt-2 text-muted">
                A profile is one person&apos;s pair of hands: yours, or someone who has said yes. Each has its own readings and chats, so nothing gets mixed up.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
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
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {profiles.map((p) => (
              <ProfileCard key={p.id} profile={p} active={p.id === activeProfile?.id} onSelect={() => setActiveProfileId(p.id)} onRename={() => setRenaming(p)} onDelete={() => setDeleting(p)} />
            ))}
          </ul>
        )}
      </section>

      {/* ----------------------------------------------------------- readings */}
      {profiles && profiles.length > 0 && activeProfile && (
        <section aria-labelledby="readings-h">
          <h2 id="readings-h" className="mb-5 font-display text-2xl font-normal">
            Readings for {activeProfile.name}
          </h2>
          {readings.error ? (
            <p role="alert" className="text-sm text-danger">
              {readings.error}
            </p>
          ) : readings.data === undefined ? (
            <div className="space-y-3" aria-busy="true">
              {[0, 1].map((i) => (
                <div key={i} className="card h-20 animate-pulse bg-ink/5" />
              ))}
            </div>
          ) : readings.data.length === 0 ? (
            <div className="card flex flex-wrap items-center justify-between gap-4 p-8">
              <div>
                <h3 className="font-display text-xl font-normal">No readings yet for {activeProfile.name}</h3>
                <p className="mt-1 text-sm text-muted">Upload a clear photo of each palm and the reading appears here.</p>
              </div>
              <Link to="/app/new" className="btn btn-primary">
                Start a reading <Icon name="arrow-right" size={16} />
              </Link>
            </div>
          ) : (
            <ul className="space-y-3">
              {readings.data.map((r) => (
                <ReadingRow key={r.id} reading={r} />
              ))}
            </ul>
          )}
        </section>
      )}

      <CreateProfileModal open={creating} onClose={() => setCreating(false)} />
      <RenameProfileModal profile={renaming} onClose={() => setRenaming(null)} />
      <DeleteProfileModal profile={deleting} onClose={() => setDeleting(null)} />
    </div>
  )
}
