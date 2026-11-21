import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { FeatureResult, FeatureId, HandProfile, Reading, ReadingSummary } from '../api/types'
import StatusDot from '../components/StatusDot'
import ChoiceCard from '../components/ui/ChoiceCard'
import Icon from '../components/ui/icons'
import Modal from '../components/ui/Modal'
import PlanetAvatar from '../components/ui/PlanetAvatar'
import { useToast } from '../components/ui/Toast'
import { FEATURE_ORDER } from '../lib/features'
import { formatDate, plural } from '../lib/format'
import { countStatuses } from '../lib/readings'
import { STATUS_LABEL } from '../lib/status'
import { useResource } from '../lib/useResource'
import { useData } from '../state/data'
import Chat from './reading/Chat'

// The Chat page: talk about ONE reading.
//
// Which reading is the "import": by default the newest reading of the active profile, or any reading of any profile
// chosen in the picker (the link ?reading=… does the same). A person can make many readings for one profile, and that
// is fine, because a chat is tied to exactly one of them: choosing another reading starts a fresh chat, so the findings
// of two readings never mix, and nobody has to throw an old reading away to get a clean chat.
//
// With the real backend the findings come from the database: this page only names the reading, and the server attaches
// its stored findings and report to every question (the browser never sends them).

function Skeleton() {
  return (
    <div aria-busy="true" className="mt-8 grid gap-6 xl:grid-cols-[22rem_minmax(0,1fr)]">
      <div className="card h-72 animate-pulse bg-ink/5" />
      <div className="card h-[28rem] animate-pulse bg-ink/5" />
    </div>
  )
}

function Empty({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card mt-8 flex flex-col items-start gap-5 p-8 md:flex-row md:items-center md:justify-between md:p-10">
      <div className="max-w-xl">
        <h2 className="font-display text-2xl font-normal">{title}</h2>
        <p className="mt-2 text-muted">A chat talks about one reading: the lines that were found in it, and the lines that were not.</p>
      </div>
      <div className="flex flex-wrap gap-3">{children}</div>
    </div>
  )
}

/** One cell of the findings table: the status as a shape and a word, never colour alone. */
function Finding({ feature }: { feature?: FeatureResult }) {
  if (!feature) return <span className="text-muted">—</span>
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs">
      <StatusDot status={feature.status} /> {STATUS_LABEL[feature.status]}
    </span>
  )
}

/** What has been imported into the chat: whose reading, which one, and what it found. */
function ReadingData({ reading, profile, newest, onChange }: { reading: Reading; profile: HandProfile; newest: boolean; onChange: () => void }) {
  const counts = countStatuses(reading)
  const [open] = useState(() => window.matchMedia('(min-width: 1280px)').matches)

  return (
    <aside aria-label="Reading data used by this chat" className="card p-5 md:p-6 xl:sticky xl:top-[7.5rem] xl:self-start">
      <p className="kicker flex items-center gap-2">
        <Icon name="book" size={15} /> Reading in this chat
      </p>
      <div className="mt-4 flex items-center gap-3.5">
        <PlanetAvatar seed={profile.id} size={52} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-display text-xl leading-tight">{profile.name}</p>
          <p className="text-sm text-muted">
            Reading of {formatDate(reading.createdAt)}
            {newest && ' · newest'}
          </p>
        </div>
        {/* on narrow screens the way to change the reading is right here, without opening anything */}
        <button type="button" onClick={onChange} className="btn btn-ghost btn-sm shrink-0 xl:hidden">
          <Icon name="download" size={15} /> Change
        </button>
      </div>

      {/* open on wide screens; tucked away on narrow ones so the chat itself is not pushed off the screen */}
      <details open={open} className="group mt-4 border-t border-ink/10 pt-3">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-lg text-sm font-medium [&::-webkit-details-marker]:hidden">
          What the chat can see
          <Icon name="chevron-down" size={16} className="text-muted transition-transform group-open:rotate-180" />
        </summary>

        {reading.meta.mock && <p className="mt-3 inline-block rounded-full bg-uncertain/25 px-3 py-0.5 text-xs font-medium text-ink">Sample reading</p>}
        <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
          <span className="flex items-center gap-1.5">
            <StatusDot status="detected" /> {counts.detected} detected
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot status="uncertain" /> {counts.uncertain} uncertain
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot status="not_visible" /> {counts.not_visible} not visible
          </span>
        </p>

        <table className="mt-3 w-full text-sm">
          <caption className="sr-only">Findings for each line, on each hand</caption>
          <thead>
            <tr className="text-left text-xs text-muted">
              <th scope="col" className="pb-2 font-medium">
                Line
              </th>
              <th scope="col" className="pb-2 font-medium">
                Left
              </th>
              <th scope="col" className="pb-2 font-medium">
                Right
              </th>
            </tr>
          </thead>
          <tbody>
            {FEATURE_ORDER.map((id: FeatureId) => {
              const left = reading.hands.left.features.find((f) => f.id === id)
              const right = reading.hands.right.features.find((f) => f.id === id)
              return (
                <tr key={id} className="border-t border-ink/10">
                  <th scope="row" className="py-2 pr-2 text-left font-normal">
                    {left?.name ?? id}
                  </th>
                  <td className="py-2 pr-2">
                    <Finding feature={left} />
                  </td>
                  <td className="py-2">
                    <Finding feature={right} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        <div className="mt-5 flex flex-col gap-2">
          <button type="button" onClick={onChange} className="btn btn-ghost btn-sm w-full max-xl:hidden">
            <Icon name="download" size={15} /> Import another reading
          </button>
          <Link to={`/app/readings/${reading.id}`} className="btn btn-ghost btn-sm w-full">
            <Icon name="eye" size={15} /> Open the full reading
          </Link>
        </div>
        <p className="mt-4 text-xs leading-relaxed text-muted">
          Only these findings and the report go to the chat. Photos are never stored. A chat uses one reading, so importing a different one starts a fresh chat and two readings never mix.
        </p>
      </details>
    </aside>
  )
}

// ------------------------------------------------------------------ the picker

function PickerBody({ currentReadingId, currentProfileId, onClose, onPick }: { currentReadingId: string | null; currentProfileId: string | null; onClose: () => void; onPick: (r: ReadingSummary) => void }) {
  const { profiles } = useData()
  const [profileId, setProfileId] = useState<string | null>(currentProfileId ?? profiles?.[0]?.id ?? null)
  const [choice, setChoice] = useState<string | null>(null)
  const group = useId()
  const list = useResource(() => (profileId ? api.listReadings(profileId) : Promise.resolve([] as ReadingSummary[])), [profileId])

  const readings = list.data
  // nothing chosen yet: the reading already in the chat (if it is this profile's), otherwise this profile's newest
  const selected = (choice && readings?.some((r) => r.id === choice) ? choice : null) ?? readings?.find((r) => r.id === currentReadingId)?.id ?? readings?.[0]?.id ?? null
  const picked = readings?.find((r) => r.id === selected) ?? null
  const profile = profiles?.find((p) => p.id === profileId)

  return (
    <>
      {profiles && profiles.length > 1 && (
        <div role="group" aria-label="Whose reading" className="flex flex-wrap gap-2">
          {profiles.map((p) => (
            <button
              key={p.id}
              type="button"
              aria-pressed={p.id === profileId}
              onClick={() => {
                setProfileId(p.id)
                setChoice(null)
              }}
              className={`inline-flex items-center gap-2 rounded-full border py-1.5 pl-1.5 pr-3.5 text-sm transition-colors ${p.id === profileId ? 'border-ink bg-accent/15' : 'border-ink/20 hover:border-ink/40'}`}
            >
              <PlanetAvatar seed={p.id} size={26} /> {p.name}
              <span className="text-muted">{p.readingCount}</span>
            </button>
          ))}
        </div>
      )}

      <div className={profiles && profiles.length > 1 ? 'mt-4' : ''}>
        {list.error ? (
          <p role="alert" className="text-sm text-danger">
            {list.error}
          </p>
        ) : readings === undefined ? (
          <div aria-busy="true" className="space-y-3">
            {[0, 1].map((i) => (
              <div key={i} className="h-16 animate-pulse rounded-2xl bg-ink/5" />
            ))}
          </div>
        ) : readings.length === 0 ? (
          <p className="rounded-2xl border border-ink/15 p-5 text-sm text-muted">
            {profile ? `${profile.name} has no readings yet.` : 'There are no readings yet.'} Make one with New reading, then come back to chat about it.
          </p>
        ) : (
          <div role="radiogroup" aria-label="Readings" className="grid max-h-[min(22rem,48vh)] gap-2 overflow-y-auto p-1">
            {readings.map((r) => (
              <ChoiceCard
                key={r.id}
                name={group}
                value={r.id}
                checked={r.id === selected}
                onChange={() => setChoice(r.id)}
                title={r.headline}
                note={`${formatDate(r.createdAt)}${r.id === readings[0].id ? ' · newest' : ''}${r.id === currentReadingId ? ' · in this chat now' : ''} · ${plural(r.conversationCount, 'chat')}`}
                extra={
                  <span className="mt-2 flex items-center gap-4 text-xs" role="img" aria-label={`${r.counts.detected} detected, ${r.counts.uncertain} uncertain, ${r.counts.not_visible} not visible`}>
                    <span className="flex items-center gap-1.5">
                      <StatusDot status="detected" /> {r.counts.detected}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <StatusDot status="uncertain" /> {r.counts.uncertain}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <StatusDot status="not_visible" /> {r.counts.not_visible}
                    </span>
                  </span>
                }
              />
            ))}
          </div>
        )}
      </div>

      <div className="mt-6 flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} className="btn btn-ghost">
          Cancel
        </button>
        <button type="button" disabled={!picked} onClick={() => picked && (picked.id === currentReadingId ? onClose() : onPick(picked))} className="btn btn-primary">
          {picked && picked.id === currentReadingId ? 'Keep this reading' : 'Import this reading'}
        </button>
      </div>
    </>
  )
}

function ReadingPicker({ open, onClose, ...rest }: { open: boolean; onClose: () => void; currentReadingId: string | null; currentProfileId: string | null; onPick: (r: ReadingSummary) => void }) {
  return (
    <Modal open={open} onClose={onClose} title="Import reading data" lead="Choose the reading this chat should talk about. A chat uses one reading, so a different one starts a fresh chat.">
      <PickerBody {...rest} onClose={onClose} />
    </Modal>
  )
}

// ------------------------------------------------------------------ the page

export default function ChatPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const { profiles, profilesError, activeProfile, setActiveProfileId, refresh } = useData()
  const [picking, setPicking] = useState(false)

  const wanted = params.get('reading')
  const signature = profiles?.map((p) => `${p.id}:${p.readingCount}`).join(',') ?? 'loading'

  // without a reading in the link, the chat uses the newest reading of the active profile
  const newest = useResource(() => (wanted || !activeProfile ? Promise.resolve([] as ReadingSummary[]) : api.listReadings(activeProfile.id)), [wanted, activeProfile?.id, signature])
  const readingId = wanted ?? newest.data?.[0]?.id ?? null
  const reading = useResource(() => (readingId ? api.getReading(readingId) : Promise.resolve(null)), [readingId])

  // A reading belongs to one profile: a link to someone else's reading makes that profile the active one, once.
  // (Choosing another profile in the header afterwards drops the link, so it is never undone.)
  const activeId = useRef(activeProfile?.id)
  useEffect(() => {
    activeId.current = activeProfile?.id
  })
  const ownerId = reading.data?.profileId
  useEffect(() => {
    if (ownerId && activeId.current !== ownerId) setActiveProfileId(ownerId)
  }, [ownerId, setActiveProfileId])

  // is the reading in the chat the newest one of its profile? (the lists come newest first)
  const ownerReadings = useResource(() => (ownerId ? api.listReadings(ownerId) : Promise.resolve([] as ReadingSummary[])), [ownerId, signature])
  const isNewest = !!reading.data && ownerReadings.data?.[0]?.id === reading.data.id

  const importReading = (r: ReadingSummary) => {
    setPicking(false)
    setActiveProfileId(r.profileId)
    setParams({ reading: r.id })
    toast(`Imported ${r.profileName}’s reading from ${formatDate(r.createdAt)}. The chat starts fresh.`)
  }

  const switchTo = (profileId: string) => {
    const target = profiles?.find((p) => p.id === profileId)
    setActiveProfileId(profileId)
    toast(`Switched to ${target?.name ?? 'that profile'}. Their chat starts fresh.`)
    navigate('/app/chat')
  }

  const owner = reading.data ? profiles?.find((p) => p.id === reading.data!.profileId) : undefined

  let body: React.ReactNode
  if (profilesError) {
    body = (
      <div className="card mt-8 p-8">
        <p role="alert" className="text-sm text-danger">
          {profilesError}
        </p>
        <button type="button" onClick={refresh} className="btn btn-ghost btn-sm mt-4">
          Try again
        </button>
      </div>
    )
  } else if (profiles === null) {
    body = <Skeleton />
  } else if (profiles.length === 0) {
    body = (
      <Empty title="Start with a hand profile">
        <Link to="/app" className="btn btn-primary">
          Go to the dashboard
        </Link>
      </Empty>
    )
  } else if (!wanted && newest.error) {
    body = (
      <div className="card mt-8 p-8">
        <p role="alert" className="text-sm text-danger">
          {newest.error}
        </p>
        <button type="button" onClick={newest.reload} className="btn btn-ghost btn-sm mt-4">
          Try again
        </button>
      </div>
    )
  } else if (!wanted && newest.data === undefined) {
    body = <Skeleton />
  } else if (!readingId) {
    const others = profiles.some((p) => p.id !== activeProfile?.id && p.readingCount > 0)
    body = (
      <Empty title={`No reading to talk about yet${activeProfile ? ` for ${activeProfile.name}` : ''}`}>
        <Link to="/app/new" className="btn btn-primary">
          <Icon name="plus" size={16} /> New reading
        </Link>
        {others && (
          <button type="button" onClick={() => setPicking(true)} className="btn btn-ghost">
            <Icon name="download" size={16} /> Import another profile’s reading
          </button>
        )}
      </Empty>
    )
  } else if (reading.error) {
    body = (
      <Empty title="That reading is not here">
        <button type="button" onClick={() => setParams({})} className="btn btn-primary">
          Use the newest reading
        </button>
      </Empty>
    )
  } else if (reading.data === undefined || !reading.data || !owner) {
    body = <Skeleton />
  } else {
    const r = reading.data
    body = (
      // keyed by reading: a different reading is a fresh chat, with nothing carried over
      <div key={r.id} className="mt-8 grid gap-6 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <ReadingData reading={r} profile={owner} newest={isNewest} onChange={() => setPicking(true)} />
        <Chat
          reading={r}
          profile={owner}
          openChat={params.get('chat')}
          className="h-[34rem] max-h-[80dvh] xl:h-[calc(100dvh-19rem)] xl:max-h-none xl:min-h-[34rem]"
          onFocusLine={(id) => navigate(`/app/readings/${r.id}?line=${id}`)}
          onShowSection={(section) => navigate(`/app/readings/${r.id}?section=${section}`)}
          onSwitchProfile={switchTo}
        />
      </div>
    )
  }

  return (
    <div>
      <p className="kicker">Chat</p>
      <h1 className="mt-3 text-balance font-display text-4xl font-light tracking-tight md:text-5xl">Talk about a reading</h1>
      <p className="mt-3 max-w-xl text-muted">Choose a reading to import, then ask about its lines. The chat only knows that one reading.</p>
      {body}
      <ReadingPicker open={picking} onClose={() => setPicking(false)} currentReadingId={reading.data?.id ?? null} currentProfileId={reading.data?.profileId ?? activeProfile?.id ?? null} onPick={importReading} />
    </div>
  )
}
