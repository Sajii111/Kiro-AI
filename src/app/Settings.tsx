import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { errorMessage } from '../api/errors'
import type { AccountStorage, DataCounts, HandProfile } from '../api/types'
import Avatar from '../components/ui/Avatar'
import PlanetAvatar from '../components/ui/PlanetAvatar'
import { originOf } from '../lib/themeTransition'
import ChoiceCard from '../components/ui/ChoiceCard'
import Icon from '../components/ui/icons'
import Modal from '../components/ui/Modal'
import Spinner from '../components/ui/Spinner'
import Switch from '../components/ui/Switch'
import TextField from '../components/ui/TextField'
import { useToast } from '../components/ui/Toast'
import { formatDate, plural } from '../lib/format'
import { useResource } from '../lib/useResource'
import { useData } from '../state/data'
import { forgetAllPhotos } from '../state/media'
import { useSession } from '../state/session'
import { useUi } from '../state/ui'
import { DISCLAIMER_LONG } from './copy'
import { RemoveLockModal } from './palm/LockModals'
import { DeleteProfileModal, RenameProfileModal } from './ProfileModals'

// Settings: who you are, how it looks, what happens to your data, and the controls for taking it with you or
// deleting it. In the sample build there is also a small set of demonstration tools.

function Section({ id, title, lead, className = '', children }: { id: string; title: string; lead?: string; className?: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className={`card p-6 md:p-8 ${className}`}>
      <h2 id={id} className="text-balance font-display text-2xl font-normal">
        {title}
      </h2>
      {lead && <p className="mt-2 max-w-2xl text-sm text-muted">{lead}</p>}
      <div className="mt-6">{children}</div>
    </section>
  )
}

// the three colours shown on each card are that theme's paper, accent and ink (see the tokens in index.css)
const THEMES = [
  { id: 'dark', name: 'Night Sky', note: 'Deep, starry and dark (the default)', swatch: ['#080B1C', '#9F8CFF', '#EEF0FF'] },
  { id: 'light', name: 'Golden Hour', note: 'A warm, bright dawn sky', swatch: ['#FFF4E8', '#FFB287', '#241B3F'] },
] as const

const STORAGE_NOTE: Record<AccountStorage, string> = {
  firestore: 'Saved in the app’s online database, so your profiles, readings and chats are here every time you sign in.',
  memory: 'This server keeps accounts only until it restarts, because it has no online database set up.',
  browser: 'This sample version keeps your account in this browser only.',
}

const PRIVACY: { title: string; text: string }[] = [
  { title: 'Photos are never stored.', text: 'They are processed in memory and deleted straight after, also when a reading fails.' },
  { title: 'Only results are kept.', text: 'The lines that were found, the written report and your chats. With an account they are saved in the app’s online database (Google Cloud Firestore) when the server has one set up, so they are there next time. The Account box says where yours are kept.' },
  { title: 'The writer never sees your photos.', text: 'Gemini, an AI run by Google, writes the report text and the chat answers. It only receives the results as words, plus your chat questions with names, e-mail addresses, phone numbers and links removed. Never a photo, your name or your contact details, and every passage it writes is checked against the results before you see it. If one Gemini model is busy, another of Google’s takes over.' },
  { title: 'Google may keep what Gemini receives.', text: 'This app uses Gemini’s free tier, where Google may use what it receives to improve its products and people may read it. Keep private details out of the chat. If the server has no Gemini key, the app’s own written notes are used instead and no results leave the server.' },
  { title: 'The hand finder runs on the server.', text: 'It is Google’s MediaPipe model, running here, not at Google. The library is built to tell Google once that it was used, naming its version and the server’s operating system. No photo goes with that.' },
  { title: 'One chat belongs to one reading.', text: 'Chats never mix between readings or between profiles.' },
  { title: 'Someone else’s palms need their yes.', text: 'A profile for another person records that they agreed.' },
  { title: 'Guest sessions are temporary.', text: 'Everything from one is deleted when it ends, unless you choose to copy it into a new account.' },
  { title: 'A palm lock keeps no photo.', text: 'Locking a profile keeps an encrypted template: numbers made from the palm’s creases, which cannot be turned back into a picture. It is never sent to Gemini, and taking the lock off deletes it. The attempt log keeps times, outcomes and scores only.' },
]

// ------------------------------------------------------------------ delete everything (type a word to confirm)

function DeleteAllModal({ open, onClose, counts }: { open: boolean; onClose: () => void; counts: { profiles: number; readings: number; chats: number; messages: number } | undefined }) {
  const [busy, setBusy] = useState(false)
  return (
    <Modal open={open} onClose={onClose} title="Delete all my data?" lead="This cannot be undone." locked={busy}>
      <DeleteAllForm onClose={onClose} onBusy={setBusy} counts={counts} />
    </Modal>
  )
}

function DeleteAllForm({ onClose, onBusy, counts }: { onClose: () => void; onBusy: (busy: boolean) => void; counts: { profiles: number; readings: number; chats: number; messages: number } | undefined }) {
  const navigate = useNavigate()
  const toast = useToast()
  const { refresh, profiles } = useData()
  const [text, setText] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusyState] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const needsPassword = !!profiles?.some((p) => p.locked)
  const ready = text.trim() === 'DELETE' && (!needsPassword || !!password)

  const setBusy = (value: boolean) => {
    setBusyState(value)
    onBusy(value)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!ready || busy) return
    setBusy(true)
    setError(null)
    try {
      const gone: DataCounts = await api.deleteAllData(needsPassword ? password : undefined)
      forgetAllPhotos()
      refresh()
      toast(`Deleted everything: ${plural(gone.profiles, 'profile')}, ${plural(gone.readings, 'reading')}, ${plural(gone.conversations, 'chat')} and ${plural(gone.messages, 'message')}.`)
      setBusy(false)
      onClose()
      navigate('/app')
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <ul className="space-y-2 rounded-2xl bg-ink/5 p-4 text-sm">
        <li className="flex items-center gap-2">
          <Icon name="trash" size={16} className="text-danger" />
          <span>{counts ? `${plural(counts.profiles, 'profile')} and ${plural(counts.readings, 'reading')}, with their results and reports` : 'Counting…'}</span>
        </li>
        <li className="flex items-center gap-2">
          <Icon name="trash" size={16} className="text-danger" />
          <span>{counts ? `${plural(counts.chats, 'chat')} with ${plural(counts.messages, 'message')} in them` : 'Counting…'}</span>
        </li>
        <li className="flex items-center gap-2 text-muted">
          <Icon name="check" size={16} />
          <span>Your account stays, so you can start again. Photos were never saved.</span>
        </li>
      </ul>
      <TextField
        label="Type DELETE to confirm"
        value={text}
        onChange={(e) => setText(e.target.value)}
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        autoFocus
        error={needsPassword ? null : error}
      />
      {needsPassword && (
        <TextField
          label="Account password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          hint="Some profiles are locked, and their readings go too, so your password stands in for their palms."
          error={error}
        />
      )}
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          Keep my data
        </button>
        <button type="submit" disabled={!ready || busy} className="btn btn-danger">
          {busy && <Spinner />} Delete everything
        </button>
      </div>
    </form>
  )
}

// ------------------------------------------------------------------ end a guest session

function EndGuestModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="End this guest session?">
      <EndGuestForm onClose={onClose} />
    </Modal>
  )
}

function EndGuestForm({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const { signOut } = useSession()
  const [busy, setBusy] = useState(false)
  const held = useResource(() => api.auth.guestSummary(), [])

  const end = async () => {
    setBusy(true)
    await signOut()
    onClose()
    navigate('/', { replace: true })
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">
        {held.data === undefined
          ? 'Counting what this session holds…'
          : held.data === null
            ? 'Nothing was made in this session, so nothing is lost.'
            : `Everything from it is deleted: ${plural(held.data.profiles, 'profile')}, ${plural(held.data.readings, 'reading')} and ${plural(held.data.conversations, 'chat')}.`}
      </p>
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          Keep going
        </button>
        <button type="button" onClick={end} disabled={busy || held.data === undefined} className="btn btn-danger">
          {busy && <Spinner />} End session
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ the page

// ------------------------------------------------------------------ the open profile, apart from the account

function ProfileSection({ profile, canLock }: { profile: HandProfile | null; canLock: boolean }) {
  const { refresh } = useData()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState<HandProfile | null>(null)
  const [deleting, setDeleting] = useState<HandProfile | null>(null)
  const [removing, setRemoving] = useState<HandProfile | null>(null)

  return (
    <Section id="set-profile" title={profile ? `This profile: ${profile.name}` : 'This profile'} lead="Settings for the hand profile open now. The account’s own settings are below.">
      {!profile ? (
        <p className="text-sm text-muted">
          No profile is open. <Link to="/app" className="underline">Choose one on the profiles page</Link> (a locked one opens with its palm).
        </p>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <PlanetAvatar seed={profile.id} size={52} />
              <div className="min-w-0">
                <p className="truncate font-display text-xl">{profile.name}</p>
                <p className="text-sm text-muted">
                  {profile.owner === 'self' ? 'My hands' : 'Shared with permission'} · {plural(profile.readingCount, 'reading')}
                </p>
              </div>
            </div>
            <p className="break-all font-mono text-xs text-muted">User ID: {profile.id}</p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => setRenaming(profile)} className="btn btn-ghost btn-sm">
                <Icon name="pencil" size={14} /> Rename
              </button>
              <button type="button" onClick={() => setDeleting(profile)} className="btn btn-ghost btn-sm">
                <Icon name="trash" size={14} /> Delete profile
              </button>
            </div>
          </div>
          <div className="rounded-2xl border border-ink/10 p-5">
            <h3 className="flex items-center gap-2 font-medium">
              <Icon name="shield" size={16} /> Palm lock
            </h3>
            {profile.lock ? (
              <>
                <p className="mt-1 text-sm text-muted">
                  On, with the {profile.lock.side} palm, since {formatDate(profile.lock.createdAt)} ({plural(profile.lock.samples, 'photo')}). Unlocked in this browser for now.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={async () => {
                      await api.closeProfile().catch(() => undefined)
                      refresh()
                      navigate('/app')
                    }}
                  >
                    <Icon name="shield" size={14} /> Lock now
                  </button>
                  <Link to={`/app/lock/${profile.id}`} className="btn btn-ghost btn-sm">
                    <Icon name="swap" size={14} /> Replace
                  </Link>
                  <button type="button" onClick={() => setRemoving(profile)} className="btn btn-ghost btn-sm">
                    <Icon name="x" size={14} /> Take it off
                  </button>
                </div>
              </>
            ) : canLock ? (
              <>
                <p className="mt-1 text-sm text-muted">Off. With a lock, this profile’s readings and chats open only after its palm is shown.</p>
                <Link to={`/app/lock/${profile.id}`} className="btn btn-ghost btn-sm mt-4">
                  <Icon name="shield" size={14} /> Set up a palm lock
                </Link>
              </>
            ) : (
              <p className="mt-1 text-sm text-muted">Palm locks are for accounts. Create an account to lock a profile.</p>
            )}
            <p className="mt-4 text-xs text-muted">
              <Link to="/app/security" className="underline">
                Attempt log
              </Link>{' '}
              ·{' '}
              <Link to="/app/palm-lab" className="underline">
                How the palm lock decides
              </Link>
            </p>
          </div>
        </div>
      )}
      <RenameProfileModal profile={renaming} onClose={() => setRenaming(null)} />
      <DeleteProfileModal profile={deleting} onClose={() => setDeleting(null)} />
      <RemoveLockModal profile={removing} onClose={() => setRemoving(null)} />
    </Section>
  )
}

export default function Settings() {
  const { session, signOut, refresh: refreshSession } = useSession()
  const { theme, toggleTheme, soundOn, toggleSound } = useUi()
  const { profiles, activeProfile, refresh } = useData()
  const toast = useToast()
  const navigate = useNavigate()
  const guest = session?.kind === 'guest'
  const demo = api.demo

  const [deleting, setDeleting] = useState(false)
  const [endingGuest, setEndingGuest] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [failNext, setFailNext] = useState(() => demo?.failNext() ?? false)
  const [busyDemo, setBusyDemo] = useState<'samples' | 'expire' | null>(null)

  const storage = useResource(() => api.accountStorage(), [])
  const signature = profiles?.map((p) => `${p.id}:${p.readingCount}`).join(',') ?? 'loading'
  const totals = useResource(async () => {
    const [readings, chats] = await Promise.all([api.listReadings(), api.listConversations()])
    return { readings: readings.length, chats: chats.length, messages: chats.reduce((n, c) => n + c.messageCount, 0) }
  }, [signature])
  const counts = profiles && totals.data ? { profiles: profiles.length, ...totals.data } : undefined

  const exportData = async () => {
    setExporting(true)
    setExportError(null)
    try {
      const bundle = await api.exportData()
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `kiro-data-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 2000)
      toast(`Exported ${plural(bundle.profiles.length, 'profile')}, ${plural(bundle.readings.length, 'reading')} and ${plural(bundle.conversations.length, 'chat')}.`)
    } catch (err) {
      setExportError(errorMessage(err))
    } finally {
      setExporting(false)
    }
  }

  const loadSamples = async () => {
    if (!demo) return
    setBusyDemo('samples')
    await demo.loadSamples()
    refresh()
    setBusyDemo(null)
    toast('Sample profiles added.')
  }

  const expireGuest = async () => {
    if (!demo) return
    setBusyDemo('expire')
    await demo.expireGuest()
    await refreshSession()
    setBusyDemo(null)
  }

  return (
    <div className="space-y-8">
      <header>
        <p className="kicker">Settings</p>
        <h1 className="mt-3 text-balance font-display text-4xl font-light tracking-tight md:text-6xl">Your account and your data</h1>
        <p className="mt-3 max-w-2xl text-pretty text-muted">Choose how it looks, see what is kept, and take your data with you or delete it.</p>
      </header>

      <ProfileSection profile={activeProfile} canLock={session?.kind === 'user'} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Section id="set-account" title={guest ? 'Guest session' : 'Account'}>
          {session?.kind === 'user' ? (
            <div className="space-y-5">
              <div className="flex items-center gap-4">
                <Avatar size={52} />
                <div className="min-w-0">
                  <p className="truncate font-display text-xl">{session.user.displayName}</p>
                  <p className="truncate text-sm text-muted">{session.user.email}</p>
                </div>
              </div>
              {storage.data && <p className="text-sm text-muted">{STORAGE_NOTE[storage.data]}</p>}
              <button
                type="button"
                onClick={async () => {
                  await signOut()
                  navigate('/', { replace: true })
                }}
                className="btn btn-ghost btn-sm"
              >
                <Icon name="logout" size={15} /> Sign out
              </button>
            </div>
          ) : (
            <div className="space-y-5">
              <div className="flex items-center gap-4">
                <Avatar size={52} />
                <p className="text-sm text-muted">You are using a guest session. Everything here is temporary and is deleted when it ends.</p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Link to="/signin" state={{ mode: 'signup', from: '/app/settings' }} className="btn btn-primary btn-sm">
                  Create an account
                </Link>
                <button type="button" onClick={() => setEndingGuest(true)} className="btn btn-ghost btn-sm">
                  End guest session
                </button>
              </div>
            </div>
          )}
        </Section>

        <Section id="set-look" title="Look and sound">
          <div className="space-y-5">
            <div role="radiogroup" aria-label="Colour theme" className="grid grid-cols-2 gap-3">
              {THEMES.map((t) => (
                <ChoiceCard
                  key={t.id}
                  name="theme"
                  value={t.id}
                  checked={theme === t.id}
                  onChange={(e) => {
                    if (theme !== t.id) toggleTheme(originOf(e.currentTarget))
                  }}
                  title={t.name}
                  note={t.note}
                  extra={
                    <span aria-hidden="true" className="mt-3 flex">
                      {t.swatch.map((colour) => (
                        <span key={colour} className="-ml-1.5 h-5 w-5 rounded-full border border-ink/25 first:ml-0" style={{ background: colour }} />
                      ))}
                    </span>
                  }
                />
              ))}
            </div>
            <Switch checked={soundOn} onChange={() => toggleSound()} label="Ambient sound" />
          </div>
        </Section>
      </div>

      <Section id="set-privacy" title="What is kept, and what is not" lead="The short version, in plain words.">
        <ul className="grid gap-x-10 gap-y-5 md:grid-cols-2">
          {PRIVACY.map((item) => (
            <li key={item.title} className="flex items-start gap-3 text-sm">
              <Icon name="shield" size={18} className="mt-0.5 shrink-0 text-accent-ink" />
              <span>
                <strong className="font-medium">{item.title}</strong> <span className="text-muted">{item.text}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-6 rounded-2xl bg-ink/5 p-4 text-sm">{DISCLAIMER_LONG}</p>
      </Section>

      <Section id="set-data" title="Your data" lead="Take a copy of everything that is kept, or remove it all.">
        <dl className="grid grid-cols-2 gap-4 md:grid-cols-4" aria-busy={!counts}>
          {[
            ['Profiles', counts?.profiles],
            ['Readings', counts?.readings],
            ['Chats', counts?.chats],
            ['Messages', counts?.messages],
          ].map(([label, value]) => (
            <div key={label as string} className="rounded-2xl bg-ink/5 p-4">
              <dt className="text-xs font-semibold uppercase tracking-wider text-muted">{label}</dt>
              <dd className="mt-1 font-display text-3xl font-light">{value ?? '–'}</dd>
            </div>
          ))}
        </dl>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl border border-ink/10 p-5">
            <h3 className="font-medium">Export my data</h3>
            <p className="mt-1 text-sm text-muted">One file (JSON) with your profiles, readings with their results and reports, and chats. It holds no photos, because none are kept.</p>
            <button type="button" onClick={exportData} disabled={exporting} className="btn btn-ghost btn-sm mt-4">
              {exporting ? <Spinner /> : <Icon name="download" size={15} />} Download my data
            </button>
            {exportError && (
              <p role="alert" className="mt-3 flex items-start gap-2 text-sm text-danger">
                <Icon name="alert" className="mt-0.5" /> {exportError}
              </p>
            )}
          </div>
          <div className="rounded-2xl border border-danger/40 p-5">
            <h3 className="font-medium">Delete all my data</h3>
            <p className="mt-1 text-sm text-muted">Removes every profile, reading and chat in one go. {guest ? 'Your guest session carries on, empty.' : 'Your account stays, so you can start again.'}</p>
            <button type="button" onClick={() => setDeleting(true)} className="btn btn-danger btn-sm mt-4">
              <Icon name="trash" size={15} /> Delete all my data
            </button>
          </div>
        </div>
      </Section>

      {demo && (
        <section aria-labelledby="set-demo" className="rounded-3xl border border-dashed border-ink/30 p-6 md:p-8">
          <h2 id="set-demo" className="font-display text-2xl font-normal">
            Demo tools
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">This copy uses built-in sample data: there is no server, and your photos are not really read. These tools only exist here, to help show every screen.</p>
          <div className="mt-6 space-y-6">
            <div>
              <Switch
                checked={failNext}
                onChange={(next) => {
                  demo.setFailNext(next)
                  setFailNext(next)
                }}
                label="Make the next reading fail"
              />
              <p className="ml-14 text-xs text-muted">Shows the error screen: the reading stops at a step, nothing is saved and the photos are discarded.</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button type="button" onClick={loadSamples} disabled={busyDemo !== null} className="btn btn-ghost btn-sm">
                {busyDemo === 'samples' && <Spinner />} Add sample profiles
              </button>
              {guest && (
                <button type="button" onClick={expireGuest} disabled={busyDemo !== null} className="btn btn-ghost btn-sm">
                  {busyDemo === 'expire' && <Spinner />} End the guest session now
                </button>
              )}
            </div>
          </div>
        </section>
      )}

      <DeleteAllModal open={deleting} onClose={() => setDeleting(false)} counts={counts} />
      <EndGuestModal open={endingGuest} onClose={() => setEndingGuest(false)} />
    </div>
  )
}
