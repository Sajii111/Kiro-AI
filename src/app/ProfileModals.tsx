import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { errorMessage } from '../api/errors'
import type { HandProfile } from '../api/types'
import ChoiceCard from '../components/ui/ChoiceCard'
import Icon from '../components/ui/icons'
import Modal from '../components/ui/Modal'
import Spinner from '../components/ui/Spinner'
import TextField from '../components/ui/TextField'
import { useToast } from '../components/ui/Toast'
import { plural } from '../lib/format'
import { useResource } from '../lib/useResource'
import { PROFILE_NAME_MAX, validateProfileName } from '../lib/validate'
import { useData } from '../state/data'
import { CONSENT_NOTE } from './copy'

// Create, rename and delete a hand profile. Used on the dashboard and inside the new-reading flow.

type CreateProps = { open: boolean; onClose: () => void; onCreated?: (profile: HandProfile) => void }

export function CreateProfileModal({ open, onClose, onCreated }: CreateProps) {
  const [busy, setBusy] = useState(false)
  return (
    <Modal open={open} onClose={onClose} title="Add a hand profile" lead="Each profile has its own readings and chats, so nothing gets mixed up between people." locked={busy}>
      <CreateForm onClose={onClose} onCreated={onCreated} onBusy={setBusy} />
    </Modal>
  )
}

function CreateForm({ onClose, onCreated, onBusy }: { onClose: () => void; onCreated?: (profile: HandProfile) => void; onBusy: (busy: boolean) => void }) {
  const { refresh, setActiveProfileId, profiles } = useData()
  const toast = useToast()
  const [name, setName] = useState('')
  const [owner, setOwner] = useState<'self' | 'other'>(profiles && profiles.length === 0 ? 'self' : 'other')
  const [consent, setConsent] = useState(false)
  const [busy, setBusyState] = useState(false)
  const [nameError, setNameError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const setBusy = (value: boolean) => {
    setBusyState(value)
    onBusy(value)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const bad = validateProfileName(name)
    setNameError(bad)
    setFormError(null)
    if (bad) return
    if (owner === 'other' && !consent) {
      setFormError('Please confirm that this person has agreed to you uploading their palms.')
      return
    }
    setBusy(true)
    try {
      const created = await api.createProfile({ name, owner, consent: owner === 'self' ? true : consent })
      refresh()
      setActiveProfileId(created.id)
      toast(`Added ${created.name}.`)
      onCreated?.(created)
      setBusy(false)
      onClose()
    } catch (err) {
      setFormError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <TextField
        label="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={PROFILE_NAME_MAX + 10}
        autoComplete="off"
        autoFocus
        hint="A first name or nickname is plenty."
        error={nameError}
      />

      <fieldset>
        <legend className="mb-2 text-sm font-medium">Whose hands are these?</legend>
        <div className="grid grid-cols-2 gap-3">
          {(['self', 'other'] as const).map((value) => (
            <ChoiceCard
              key={value}
              name="owner"
              value={value}
              checked={owner === value}
              onChange={() => setOwner(value)}
              title={value === 'self' ? 'Mine' : 'Someone else'}
              note={value === 'self' ? 'My own palms' : 'They have said yes'}
            />
          ))}
        </div>
      </fieldset>

      {owner === 'other' && (
        <label className="flex cursor-pointer items-start gap-3 rounded-2xl bg-accent2/20 p-4 text-sm">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--accent-ink)]" />
          <span>
            <strong className="font-medium">This person has agreed</strong> to me uploading their palms.
            <span className="mt-1 block text-xs text-muted">{CONSENT_NOTE}</span>
          </span>
        </label>
      )}

      {formError && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger">
          <Icon name="alert" className="mt-0.5" /> {formError}
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-3 pt-1">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          Cancel
        </button>
        <button type="submit" disabled={busy} className="btn btn-primary">
          {busy && <Spinner />} Add profile
        </button>
      </div>
    </form>
  )
}

export function RenameProfileModal({ profile, onClose }: { profile: HandProfile | null; onClose: () => void }) {
  return (
    <Modal open={!!profile} onClose={onClose} title="Rename profile">
      {profile && <RenameForm key={profile.id} profile={profile} onClose={onClose} />}
    </Modal>
  )
}

function RenameForm({ profile, onClose }: { profile: HandProfile; onClose: () => void }) {
  const { refresh } = useData()
  const [name, setName] = useState(profile.name)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const bad = validateProfileName(name)
    setError(bad)
    if (bad) return
    setBusy(true)
    try {
      await api.renameProfile(profile.id, name)
      refresh()
      onClose()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} autoFocus autoComplete="off" error={error} hint="A first name or nickname is plenty." />
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          Cancel
        </button>
        <button type="submit" disabled={busy} className="btn btn-primary">
          {busy && <Spinner />} Save
        </button>
      </div>
    </form>
  )
}

export function DeleteProfileModal({ profile, onClose }: { profile: HandProfile | null; onClose: () => void }) {
  return (
    <Modal open={!!profile} onClose={onClose} title={profile ? `Delete ${profile.name}?` : 'Delete profile'}>
      {profile && <DeleteForm key={profile.id} profile={profile} onClose={onClose} />}
    </Modal>
  )
}

function DeleteForm({ profile, onClose }: { profile: HandProfile; onClose: () => void }) {
  const { refresh } = useData()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const readings = useResource(() => api.listReadings(profile.id), [profile.id])

  const chats = readings.data?.reduce((n, r) => n + r.conversationCount, 0)

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      const gone = await api.deleteProfile(profile.id)
      refresh()
      toast(`Deleted ${profile.name}: ${plural(gone.readings, 'reading')}, ${plural(gone.conversations, 'chat')} and ${plural(gone.messages, 'message')} removed.`)
      onClose()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">This permanently removes the profile and everything that belongs to it. It cannot be undone.</p>
      <ul className="space-y-2 rounded-2xl bg-ink/5 p-4 text-sm">
        <li className="flex items-center gap-2">
          <Icon name="trash" size={16} className="text-danger" />
          <span>
            {readings.loading || readings.data === undefined ? 'Counting…' : `${plural(readings.data.length, 'reading')}`} and their results and reports
          </span>
        </li>
        <li className="flex items-center gap-2">
          <Icon name="trash" size={16} className="text-danger" />
          <span>{chats === undefined ? 'Counting…' : `${plural(chats, 'chat')}`} with every message in them</span>
        </li>
        <li className="flex items-center gap-2 text-muted">
          <Icon name="check" size={16} />
          <span>Photos were never saved, so there is nothing else to remove.</span>
        </li>
      </ul>
      {error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger">
          <Icon name="alert" className="mt-0.5" /> {error}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          Keep it
        </button>
        <button type="button" onClick={remove} disabled={busy || readings.loading} className="btn btn-danger">
          {busy && <Spinner />} Delete {profile.name}
        </button>
      </div>
    </div>
  )
}
