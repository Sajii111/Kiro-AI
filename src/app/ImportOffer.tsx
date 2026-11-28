import { useState } from 'react'
import { errorMessage } from '../api/errors'
import Icon from '../components/ui/icons'
import Modal from '../components/ui/Modal'
import Spinner from '../components/ui/Spinner'
import { useToast } from '../components/ui/Toast'
import { plural } from '../lib/format'
import { useData } from '../state/data'
import { useSession } from '../state/session'
import { t } from '../i18n'

/**
 * Shown after signing in when a guest session still holds data. Nothing is ever moved silently:
 * the person chooses to import it or to throw it away.
 */
export default function ImportOffer() {
  const { importOffer, acceptImport, declineImport } = useSession()
  const { refresh } = useData()
  const toast = useToast()
  const [busy, setBusy] = useState<'import' | 'discard' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async (which: 'import' | 'discard') => {
    setBusy(which)
    setError(null)
    try {
      if (which === 'import') {
        const counts = await acceptImport()
        toast(t("Imported {0}, {1} and {2} into your account.", { "0": plural(counts.profiles, 'profile'), "1": plural(counts.readings, 'reading'), "2": plural(counts.conversations, 'chat') }))
      } else {
        await declineImport()
        toast(t("The guest session was discarded."))
      }
      refresh()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Modal open={!!importOffer} onClose={() => {}} locked title={t("Bring your guest session with you?")} lead={t("You were using a guest session before signing in. Nothing moves into your account unless you say so.")}>
      {importOffer && (
        <div className="space-y-5">
          <ul className="space-y-1.5 rounded-2xl bg-ink/5 p-4 text-sm">
            <li>{plural(importOffer.profiles, 'hand profile')}</li>
            <li>{plural(importOffer.readings, 'reading')}</li>
            <li>
              {plural(importOffer.conversations, 'chat')} ({plural(importOffer.messages, 'message')})
            </li>
          </ul>
          <p className="text-sm text-muted">{t("Only the results, reports and chats can move across. Photos were never saved. If you discard the guest session, this data is deleted for good.")}</p>
          {error && (
            <p role="alert" className="flex items-start gap-2 text-sm text-danger">
              <Icon name="alert" className="mt-0.5" /> {error}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-3">
            <button type="button" className="btn btn-ghost" disabled={!!busy} onClick={() => run('discard')}>
              {busy === 'discard' && <Spinner />} {t("Discard it")}
            </button>
            <button type="button" className="btn btn-primary" disabled={!!busy} onClick={() => run('import')}>
              {busy === 'import' && <Spinner />} {t("Import into my account")}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
