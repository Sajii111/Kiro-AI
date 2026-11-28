import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { useSession } from '../state/session'
import { CONSENT_NOTE } from './copy'
import { t } from '../i18n'
import { tx } from '../i18n/rich'

// Create, rename and delete a hand profile. Used on the dashboard and inside the new-reading flow.

type CreateProps = { open: boolean; onClose: () => void; onCreated?: (profile: HandProfile) => void }

export function CreateProfileModal({ open, onClose, onCreated }: CreateProps) {
  const [busy, setBusy] = useState(false)
  return (
    <Modal open={open} onClose={onClose} title={t("Add a hand profile")} lead={t("Each profile has its own readings and chats, so nothing gets mixed up between people.")} locked={busy}>
      <CreateForm onClose={onClose} onCreated={onCreated} onBusy={setBusy} />
    </Modal>
  )
}

function CreateForm({ onClose, onCreated, onBusy }: { onClose: () => void; onCreated?: (profile: HandProfile) => void; onBusy: (busy: boolean) => void }) {
  const { refresh, setActiveProfileId, profiles } = useData()
  const { session } = useSession()
  const navigate = useNavigate()
  const toast = useToast()
  const canLock = session?.kind === 'user'
  const [lockNext, setLockNext] = useState(false)
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
      setFormError(t("Please confirm that this person has agreed to you uploading their palms."))
      return
    }
    setBusy(true)
    try {
      const created = await api.createProfile({ name, owner, consent: owner === 'self' ? true : consent })
      refresh()
      setActiveProfileId(created.id)
      toast(t("Added {name}.", { name: created.name }))
      onCreated?.(created)
      setBusy(false)
      onClose()
      if (canLock && lockNext) navigate(`/app/lock/${created.id}`)
    } catch (err) {
      setFormError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <TextField
        label={t("Name")}
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={PROFILE_NAME_MAX + 10}
        autoComplete="off"
        autoFocus
        hint={t("A first name or nickname is plenty.")}
        error={nameError}
      />

      <fieldset>
        <legend className="mb-2 text-sm font-medium">{t("Whose hands are these?")}</legend>
        <div className="grid grid-cols-2 gap-3">
          {(['self', 'other'] as const).map((value) => (
            <ChoiceCard
              key={value}
              name="owner"
              value={value}
              checked={owner === value}
              onChange={() => setOwner(value)}
              title={value === 'self' ? t("Mine") : t("Someone else")}
              note={value === 'self' ? t("My own palms") : t("They have said yes")}
            />
          ))}
        </div>
      </fieldset>

      {owner === 'other' && (
        <label className="flex cursor-pointer items-start gap-3 rounded-2xl bg-accent2/20 p-4 text-sm">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--accent-ink)]" />
          <span>
            {tx('{agreed} to me uploading their palms.', { agreed: <strong className="font-medium">{t('This person has agreed')}</strong> })}
            <span className="mt-1 block text-xs text-muted">{CONSENT_NOTE}</span>
          </span>
        </label>
      )}

      {canLock && (
        <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-ink/15 p-4 text-sm">
          <input type="checkbox" checked={lockNext} onChange={(e) => setLockNext(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--accent-ink)]" />
          <span>
            <strong className="font-medium">{t("Lock it with a palm")}</strong> {t('(optional)')}
            <span className="mt-1 block text-xs text-muted">{t("Its readings and chats then open only after the palm is shown. You can also add a lock later.")}</span>
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
          {t("Cancel")}
        </button>
        <button type="submit" disabled={busy} className="btn btn-primary">
          {busy && <Spinner />} {canLock && lockNext ? t("Add, then lock") : t("Add profile")}
        </button>
      </div>
    </form>
  )
}

export function RenameProfileModal({ profile, onClose }: { profile: HandProfile | null; onClose: () => void }) {
  return (
    <Modal open={!!profile} onClose={onClose} title={t("Rename profile")}>
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
      <TextField label={t("Name")} value={name} onChange={(e) => setName(e.target.value)} autoFocus autoComplete="off" error={error} hint={t("A first name or nickname is plenty.")} />
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          {t("Cancel")}
        </button>
        <button type="submit" disabled={busy} className="btn btn-primary">
          {busy && <Spinner />} {t("Save")}
        </button>
      </div>
    </form>
  )
}

export function DeleteProfileModal({ profile, onClose }: { profile: HandProfile | null; onClose: () => void }) {
  return (
    <Modal open={!!profile} onClose={onClose} title={profile ? t("Delete {name}?", { name: profile.name }) : t("Delete profile")}>
      {profile && <DeleteForm key={profile.id} profile={profile} onClose={onClose} />}
    </Modal>
  )
}

function DeleteForm({ profile, onClose }: { profile: HandProfile; onClose: () => void }) {
  const { refresh } = useData()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  // a locked profile's readings stay hidden, so they are not counted (asking for them would only be refused)
  const readings = useResource(() => (profile.locked ? Promise.resolve(null) : api.listReadings(profile.id)), [profile.id, profile.locked])

  const chats = readings.data?.reduce((n, r) => n + r.conversationCount, 0)

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      const gone = await api.deleteProfile(profile.id, profile.locked ? password : undefined)
      refresh()
      toast(t("Deleted {name}: {1}, {2} and {3} removed.", { name: profile.name, "1": plural(gone.readings, 'reading'), "2": plural(gone.conversations, 'chat'), "3": plural(gone.messages, 'message') }))
      onClose()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">{t("This permanently removes the profile and everything that belongs to it. It cannot be undone.")}</p>
      <ul className="space-y-2 rounded-2xl bg-ink/5 p-4 text-sm">
        <li className="flex items-center gap-2">
          <Icon name="trash" size={16} className="text-danger" />
          <span>
            {profile.locked ? t('All its readings, with their results and reports') : readings.loading || !readings.data ? t("Counting…") : t('{count}, with their results and reports', { count: plural(readings.data.length, 'reading') })}
          </span>
        </li>
        <li className="flex items-center gap-2">
          <Icon name="trash" size={16} className="text-danger" />
          <span>{profile.locked ? t('All its chats, with every message in them') : chats === undefined ? t("Counting…") : t('{count}, with every message in them', { count: plural(chats, 'chat') })}</span>
        </li>
        {profile.lock && (
          <li className="flex items-center gap-2">
            <Icon name="trash" size={16} className="text-danger" />
            <span>{t("Its palm lock (the encrypted template)")}</span>
          </li>
        )}
        <li className="flex items-center gap-2 text-muted">
          <Icon name="check" size={16} />
          <span>{t("Photos were never saved, so there is nothing else to remove.")}</span>
        </li>
      </ul>
      {profile.locked && (
        <TextField
          label={t("Account password")}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          hint={t("{name} is locked, so your password stands in for the palm (or unlock it first). This is written to the attempt log.", { name: profile.name })}
        />
      )}
      {error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger">
          <Icon name="alert" className="mt-0.5" /> {error}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          {t("Keep it")}
        </button>
        <button type="button" onClick={remove} disabled={busy || readings.loading || (profile.locked && !password)} className="btn btn-danger">
          {busy && <Spinner />} {t('Delete {name}', { name: profile.name })}
        </button>
      </div>
    </div>
  )
}
