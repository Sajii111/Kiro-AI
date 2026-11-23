import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { errorMessage } from '../api/errors'
import type { Conversation, DeleteSummary } from '../api/types'
import Icon from '../components/ui/icons'
import Modal from '../components/ui/Modal'
import Spinner from '../components/ui/Spinner'
import TextField from '../components/ui/TextField'
import { useToast } from '../components/ui/Toast'
import { plural } from '../lib/format'
import { useResource } from '../lib/useResource'
import { validateReadingName } from '../lib/validate'
import { useData } from '../state/data'
import { forgetPhotos } from '../state/media'

// Name or rename a reading, and delete a reading or one chat. Deleting says exactly what goes with it before anything is removed.

type ReadingRef = { id: string; label: string }

/** A reading's name is optional and can be changed any time, so a typo never means doing the photos again. Saving it empty takes the name away. */
export function RenameReadingModal({ reading, onClose, onRenamed }: { reading: { id: string; name?: string } | null; onClose: () => void; onRenamed?: () => void }) {
  return (
    <Modal open={!!reading} onClose={onClose} title="Name this reading">
      {reading && <RenameReadingForm key={reading.id} reading={reading} onClose={onClose} onRenamed={onRenamed} />}
    </Modal>
  )
}

function RenameReadingForm({ reading, onClose, onRenamed }: { reading: { id: string; name?: string }; onClose: () => void; onRenamed?: () => void }) {
  const { refresh } = useData()
  const toast = useToast()
  const [name, setName] = useState(reading.name ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const bad = validateReadingName(name)
    setError(bad)
    if (bad) return
    setBusy(true)
    try {
      const saved = await api.renameReading(reading.id, name)
      refresh()
      toast(saved.name ? `Named the reading “${saved.name}”.` : 'Took the name off. The reading goes by its date again.')
      onRenamed?.()
      onClose()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <TextField
        label="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="For example: Before my trip"
        autoFocus
        autoComplete="off"
        error={error}
        hint="Leave it empty to go back to the date."
      />
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

export function DeleteReadingModal({ reading, onClose, onDeleted }: { reading: ReadingRef | null; onClose: () => void; onDeleted?: (gone: DeleteSummary) => void }) {
  return (
    <Modal open={!!reading} onClose={onClose} title="Delete this reading?">
      {reading && <DeleteReadingForm key={reading.id} reading={reading} onClose={onClose} onDeleted={onDeleted} />}
    </Modal>
  )
}

function DeleteReadingForm({ reading, onClose, onDeleted }: { reading: ReadingRef; onClose: () => void; onDeleted?: (gone: DeleteSummary) => void }) {
  const { refresh } = useData()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const chats = useResource(() => api.listConversations({ readingId: reading.id }), [reading.id])
  const messages = chats.data?.reduce((n, c) => n + c.messageCount, 0)

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      const gone = await api.deleteReading(reading.id)
      forgetPhotos(reading.id)
      refresh()
      toast(`Deleted ${reading.label}: ${plural(gone.conversations, 'chat')} and ${plural(gone.messages, 'message')} removed.`)
      onDeleted?.(gone)
      onClose()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">This permanently removes the reading and everything that belongs to it. It cannot be undone.</p>
      <ul className="space-y-2 rounded-2xl bg-ink/5 p-4 text-sm">
        <li className="flex items-center gap-2">
          <Icon name="trash" size={16} className="text-danger" />
          <span>{reading.label}, with its results and written report</span>
        </li>
        <li className="flex items-center gap-2">
          <Icon name="trash" size={16} className="text-danger" />
          <span>
            {chats.data === undefined ? 'Counting…' : `${plural(chats.data.length, 'chat')}`} with {messages === undefined ? 'every message' : `${plural(messages, 'message')}`} in {chats.data?.length === 1 ? 'it' : 'them'}
          </span>
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
        <button type="button" onClick={remove} disabled={busy || chats.loading} className="btn btn-danger">
          {busy && <Spinner />} Delete reading
        </button>
      </div>
    </div>
  )
}

export function DeleteChatModal({ chat, onClose, onDeleted }: { chat: Conversation | null; onClose: () => void; onDeleted?: (id: string) => void }) {
  return (
    <Modal open={!!chat} onClose={onClose} title="Delete this chat?">
      {chat && <DeleteChatForm key={chat.id} chat={chat} onClose={onClose} onDeleted={onDeleted} />}
    </Modal>
  )
}

function DeleteChatForm({ chat, onClose, onDeleted }: { chat: Conversation; onClose: () => void; onDeleted?: (id: string) => void }) {
  const { refresh } = useData()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      const gone = await api.deleteConversation(chat.id)
      refresh()
      toast(`Deleted the chat and its ${plural(gone.messages, 'message')}.`)
      onDeleted?.(chat.id)
      onClose()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">
        “{chat.title}” and its {plural(chat.messageCount, 'message')} will be removed. The reading itself stays.
      </p>
      {error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-danger">
          <Icon name="alert" className="mt-0.5" /> {error}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3">
        <button type="button" onClick={onClose} disabled={busy} className="btn btn-ghost">
          Keep it
        </button>
        <button type="button" onClick={remove} disabled={busy} className="btn btn-danger">
          {busy && <Spinner />} Delete chat
        </button>
      </div>
    </div>
  )
}
