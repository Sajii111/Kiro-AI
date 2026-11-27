import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Conversation, ReadingSummary } from '../api/types'
import StatusDot from '../components/StatusDot'
import Icon from '../components/ui/icons'
import { formatDate, plural, relativeDay } from '../lib/format'
import { readingLabel } from '../lib/readings'
import { useResource } from '../lib/useResource'
import { useData } from '../state/data'
import { useSession } from '../state/session'
import { DeleteChatModal, DeleteReadingModal } from './ReadingModals'

// Everything that has been made, in one place: readings and chats, newest first, with a filter per profile and a
// delete button on each. For a guest this is "this session": temporary, and it says so.

function ReadingEntry({ reading, onDelete }: { reading: ReadingSummary; onDelete: () => void }) {
  const when = formatDate(reading.createdAt)
  return (
    <li className="card flex items-center gap-2 p-2 pl-5 transition-colors hover:border-ink/25 md:pl-6">
      <Link to={`/app/readings/${reading.id}`} className="group flex min-w-0 flex-1 flex-wrap items-center gap-x-6 gap-y-2 py-3" data-cursor>
        <span className="min-w-0 flex-1 basis-56">
          {/* a reading with a name shows it as the title, and moves what it found down to the small line */}
          <span className="block font-display text-lg [overflow-wrap:anywhere] group-hover:text-accent-ink">{reading.name ?? reading.headline}</span>
          <span className="block text-sm text-muted">
            {reading.profileName} · {when}
            {reading.name ? ` · ${reading.headline}` : ''}
          </span>
        </span>
        <span className="flex items-center gap-4 text-sm" role="img" aria-label={`${reading.counts.detected} detected, ${reading.counts.uncertain} uncertain, ${reading.counts.not_visible} not visible`}>
          <span className="flex items-center gap-1.5">
            <StatusDot status="detected" /> {reading.counts.detected}
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot status="uncertain" /> {reading.counts.uncertain}
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot status="not_visible" /> {reading.counts.not_visible}
          </span>
        </span>
        <span className="flex items-center gap-1.5 text-sm text-muted">
          <Icon name="chat" size={15} /> {plural(reading.conversationCount, 'chat')}
        </span>
      </Link>
      <button
        type="button"
        onClick={onDelete}
        aria-label={`Delete ${readingLabel(reading, reading.profileName)}`}
        title="Delete this reading"
        className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-danger/10 hover:text-danger"
      >
        <Icon name="trash" size={17} />
      </button>
    </li>
  )
}

function ChatEntry({ chat, profileName, aboutReading, onDelete }: { chat: Conversation; profileName: string; aboutReading: string | null; onDelete: () => void }) {
  return (
    <li className="card flex items-center gap-2 p-2 pl-5 transition-colors hover:border-ink/25 md:pl-6">
      <Link to={`/app/readings/${chat.readingId}?chat=${chat.id}`} className="group min-w-0 flex-1 py-3" data-cursor>
        <span className="block truncate font-medium group-hover:text-accent-ink">{chat.title}</span>
        <span className="block text-sm text-muted">
          {profileName}
          {aboutReading ? ` · about ${aboutReading}` : ''} · {plural(chat.messageCount, 'message')} · {relativeDay(chat.updatedAt)}
        </span>
      </Link>
      <button
        type="button"
        onClick={onDelete}
        aria-label={`Delete chat: ${chat.title}`}
        title="Delete this chat"
        className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-muted transition-colors hover:bg-danger/10 hover:text-danger"
      >
        <Icon name="trash" size={17} />
      </button>
    </li>
  )
}

function Skeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-3" aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="card h-20 animate-pulse bg-ink/5" />
      ))}
    </div>
  )
}

export default function History() {
  const { session } = useSession()
  const { profiles, activeProfile } = useData()
  const guest = session?.kind === 'guest'
  const [deletingReading, setDeletingReading] = useState<ReadingSummary | null>(null)
  const [deletingChat, setDeletingChat] = useState<Conversation | null>(null)

  // inside one profile, the history is that profile's: load again whenever its readings come or go
  const profileId = activeProfile?.id ?? ''
  const signature = profiles?.map((p) => `${p.id}:${p.readingCount}`).join(',') ?? 'loading'
  const readings = useResource(() => (profileId ? api.listReadings(profileId) : Promise.resolve([] as ReadingSummary[])), [profileId, signature])
  const chats = useResource(() => (profileId ? api.listConversations({ profileId }) : Promise.resolve([] as Conversation[])), [profileId, signature])
  const reloadAll = () => {
    readings.reload()
    chats.reload()
  }

  const shownReadings = readings.data
  const shownChats = chats.data
  const nameOf = (id: string) => profiles?.find((p) => p.id === id)?.name ?? 'Someone'
  /** which reading a chat is about, in words: its name when it has one, otherwise its date */
  const aboutReading = (id: string) => {
    const r = readings.data?.find((x) => x.id === id)
    return r ? (r.name ? `“${r.name}”` : `the reading of ${formatDate(r.createdAt)}`) : null
  }

  return (
    <div className="space-y-12">
      <header>
        <p className="kicker">{guest ? 'Guest session' : 'History'}</p>
        <h1 className="mt-3 text-balance font-display text-4xl font-light tracking-tight md:text-6xl">{guest ? 'This session' : `Everything for ${activeProfile?.name ?? 'this profile'}`}</h1>
        <p className="mt-3 max-w-xl text-muted">
          {guest
            ? `${activeProfile?.name ?? 'This profile'}’s readings and chats from this guest session. They are temporary: when the session ends they are deleted, so this is not saved history.`
            : `Every reading and chat of ${activeProfile?.name ?? 'this profile'}, newest first. You can open any of them, or delete the ones you no longer want. Other profiles keep their own history.`}
        </p>
        {guest && (
          <Link to="/signin" state={{ mode: 'signup', from: '/app/history' }} className="btn btn-ghost btn-sm mt-5">
            Create an account to keep them <Icon name="arrow-right" size={15} />
          </Link>
        )}
      </header>

      <section aria-labelledby="history-readings">
        <h2 id="history-readings" className="mb-5 font-display text-2xl font-normal">
          Readings
        </h2>
        {readings.error ? (
          <p role="alert" className="text-sm text-danger">
            {readings.error}
          </p>
        ) : shownReadings === undefined ? (
          <Skeleton rows={2} />
        ) : shownReadings.length === 0 ? (
          <div className="card flex flex-wrap items-center justify-between gap-4 p-8">
            <div>
              <h3 className="font-display text-xl font-normal">No readings for {nameOf(profileId)} yet</h3>
              <p className="mt-1 text-sm text-muted">Upload a clear photo of each palm and the reading appears here.</p>
            </div>
            <Link to="/app/new" className="btn btn-primary">
              Start a reading <Icon name="arrow-right" size={16} />
            </Link>
          </div>
        ) : (
          <ul className="space-y-3">
            {shownReadings.map((r) => (
              <ReadingEntry key={r.id} reading={r} onDelete={() => setDeletingReading(r)} />
            ))}
          </ul>
        )}
        <p className="mt-4 text-sm text-muted">Photos are not listed because they are never kept. Only the results, the report and the chats are.</p>
      </section>

      <section aria-labelledby="history-chats">
        <h2 id="history-chats" className="mb-5 font-display text-2xl font-normal">
          Chats
        </h2>
        {chats.error ? (
          <p role="alert" className="text-sm text-danger">
            {chats.error}
          </p>
        ) : shownChats === undefined ? (
          <Skeleton rows={1} />
        ) : shownChats.length === 0 ? (
          <div className="card p-8">
            <h3 className="font-display text-xl font-normal">No chats for {nameOf(profileId)} yet</h3>
            <p className="mt-1 text-sm text-muted">Open a reading and ask a question. Each chat belongs to one reading and never mixes with another.</p>
          </div>
        ) : (
          <ul className="space-y-3">
            {shownChats.map((c) => (
              <ChatEntry key={c.id} chat={c} profileName={nameOf(c.profileId)} aboutReading={aboutReading(c.readingId)} onDelete={() => setDeletingChat(c)} />
            ))}
          </ul>
        )}
      </section>

      <DeleteReadingModal
        reading={deletingReading ? { id: deletingReading.id, label: readingLabel(deletingReading, deletingReading.profileName) } : null}
        onClose={() => setDeletingReading(null)}
        onDeleted={reloadAll}
      />
      <DeleteChatModal chat={deletingChat} onClose={() => setDeletingChat(null)} onDeleted={reloadAll} />
    </div>
  )
}
