import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { HandProfile, ReadingSummary } from '../api/types'
import StatusDot from '../components/StatusDot'
import PlanetAvatar from '../components/ui/PlanetAvatar'
import Icon from '../components/ui/icons'
import { formatDate, greeting, plural } from '../lib/format'
import { useResource } from '../lib/useResource'
import { useData } from '../state/data'
import { useSession } from '../state/session'
import { RenameProfileModal } from './ProfileModals'

// Inside one hand profile: its home. Its readings, newest first, and the way to everything else for this profile.
// (Choosing a profile happens before this, on the profile picker: see ProfilePicker.tsx.)

function ReadingRow({ reading }: { reading: ReadingSummary }) {
  const when = formatDate(reading.createdAt)
  return (
    // the whole row opens the reading (a stretched link); the Chat button sits above it and has its own target
    <li className="card group relative flex flex-wrap items-center gap-x-6 gap-y-3 p-5 transition-colors hover:border-accent">
      <Link to={`/app/readings/${reading.id}`} className="min-w-0 flex-1 basis-60 after:absolute after:inset-0 after:rounded-[inherit] after:content-['']" data-cursor>
        <span className="block font-display text-lg [overflow-wrap:anywhere]">{reading.name ?? reading.headline}</span>
        <span className="block text-sm text-muted">
          {when}
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
  const { profiles, activeProfile, leaveProfile } = useData()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState<HandProfile | null>(null)

  // reload the readings whenever a reading comes or goes
  const signature = profiles?.map((p) => `${p.id}:${p.readingCount}`).join(',') ?? 'loading'
  const readings = useResource(() => (activeProfile ? api.listReadings(activeProfile.id) : Promise.resolve([] as ReadingSummary[])), [activeProfile?.id, signature])
  const name = session?.kind === 'user' ? session.user.displayName : null
  if (!activeProfile) return null
  const profile = activeProfile
  const others = (profiles?.length ?? 1) > 1

  // back to the profile picker; a locked profile locks again on the way out
  const leave = async () => {
    if (await leaveProfile()) navigate('/app')
  }

  return (
    <div className="space-y-12">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div className="flex items-center gap-5">
          <PlanetAvatar seed={profile.id} size={76} />
          <div className="min-w-0">
            <p className="kicker">{name ? `${greeting()}, ${name}` : greeting()}</p>
            <h1 className="mt-2 text-balance font-display text-4xl font-light tracking-tight md:text-6xl">{profile.name}</h1>
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
              <span>{profile.owner === 'self' ? 'My hands' : 'Shared with permission'}</span>
              <span>· {plural(profile.readingCount, 'reading')}</span>
              {profile.lock ? (
                <span className="inline-flex items-center gap-1 text-detected">
                  · <Icon name="shield" size={13} /> Palm lock on, unlocked here
                </span>
              ) : (
                session?.kind === 'user' && (
                  <Link to={`/app/lock/${profile.id}`} className="inline-flex items-center gap-1 underline hover:text-ink">
                    · <Icon name="shield" size={13} /> Add a palm lock
                  </Link>
                )
              )}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to="/app/chat" className="btn btn-ghost !px-6 !py-4">
            <Icon name="chat" size={17} /> Chat about a reading
          </Link>
          <Link to="/app/new" className="btn btn-primary !px-7 !py-4">
            <Icon name="plus" size={17} /> New reading
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {others && (
          <button type="button" onClick={leave} className="btn btn-ghost btn-sm">
            <Icon name="swap" size={14} /> Switch profile
          </button>
        )}
        {profile.lock && (
          <button type="button" onClick={leave} className="btn btn-ghost btn-sm">
            <Icon name="shield" size={14} /> Lock {profile.name} now
          </button>
        )}
        <button type="button" onClick={() => setRenaming(profile)} className="btn btn-ghost btn-sm">
          <Icon name="pencil" size={14} /> Rename
        </button>
      </div>

      <section aria-labelledby="readings-h">
        <h2 id="readings-h" className="mb-5 font-display text-2xl font-normal">
          {profile.name}’s readings
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
              <h3 className="font-display text-xl font-normal">No readings yet for {profile.name}</h3>
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

      <RenameProfileModal profile={renaming} onClose={() => setRenaming(null)} />
    </div>
  )
}
