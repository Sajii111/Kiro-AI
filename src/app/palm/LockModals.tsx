import { useState, type FormEvent } from 'react'
import { api } from '../../api'
import { errorMessage } from '../../api/errors'
import type { HandProfile } from '../../api/types'
import Icon from '../../components/ui/icons'
import Modal from '../../components/ui/Modal'
import Spinner from '../../components/ui/Spinner'
import TextField from '../../components/ui/TextField'
import { useToast } from '../../components/ui/Toast'
import { useData } from '../../state/data'
import { t } from '../../i18n'

/**
 * Taking a palm lock off. While the profile is open (its palm was shown in this browser) it comes off with one click.
 * Otherwise the account password stands in for the palm, and the attempt log says so.
 */
export function RemoveLockModal({ profile, onClose }: { profile: HandProfile | null; onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  return (
    <Modal open={!!profile} onClose={onClose} title={profile ? t("Take the palm lock off {name}?", { name: profile.name }) : t("Take the lock off")} locked={busy}>
      {profile && <RemoveLockForm key={profile.id} profile={profile} onClose={onClose} onBusy={setBusy} />}
    </Modal>
  )
}

function RemoveLockForm({ profile, onClose, onBusy }: { profile: HandProfile; onClose: () => void; onBusy: (b: boolean) => void }) {
  const { refresh } = useData()
  const toast = useToast()
  const [password, setPassword] = useState('')
  const [busy, setBusyState] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const needsPassword = !profile.open

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusyState(true)
    onBusy(true)
    setError(null)
    try {
      await api.removeLock(profile.id, needsPassword ? password : undefined)
      refresh()
      toast(t("The palm lock is off {name}. Its template was deleted.", { name: profile.name }))
      onBusy(false)
      onClose()
    } catch (err) {
      setError(errorMessage(err))
      setBusyState(false)
      onBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <p className="text-sm text-muted">
        {t('Anyone signed in to this account will then reach {name}’s readings and chats without the palm. The encrypted template is deleted. The attempt log keeps its record.', { name: profile.name })}
      </p>
      {needsPassword && (
        <TextField
          label={t("Account password")}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          autoFocus
          hint={t("{name} is locked, so the password stands in for the palm. This is written to the attempt log.", { name: profile.name })}
        />
      )}
      {error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger">
          <Icon name="alert" className="mt-0.5 shrink-0" /> {error}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          {t("Keep the lock")}
        </button>
        <button type="submit" disabled={busy || (needsPassword && !password)} className="btn btn-danger">
          {busy && <Spinner />} {t("Take the lock off")}
        </button>
      </div>
    </form>
  )
}
