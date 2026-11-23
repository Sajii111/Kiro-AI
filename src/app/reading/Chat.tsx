import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { api } from '../../api'
import { errorMessage } from '../../api/errors'
import type { Conversation, FeatureId, HandProfile, Message, Reading } from '../../api/types'
import PlanetAvatar from '../../components/ui/PlanetAvatar'
import Icon from '../../components/ui/icons'
import Menu from '../../components/ui/Menu'
import { formatDate } from '../../lib/format'
import { useResource } from '../../lib/useResource'
import { MESSAGE_MAX } from '../../lib/validate'
import { useData } from '../../state/data'
import { DISCLAIMER_SHORT } from '../copy'
import { DeleteChatModal } from '../ReadingModals'
import MessageView, { Typing, type MessageHandlers } from './ChatMessage'

// The chat about ONE reading of ONE profile. It starts empty, creates its conversation when the first question
// is sent (so opening a reading never leaves empty chats behind), and can be switched to an earlier chat or a new
// one. Every chat is keyed to the reading, so nothing carries over from another reading or another profile.

type Props = MessageHandlers & {
  reading: Reading
  profile: HandProfile
  className?: string
  /** a chat to open first, when a link asks for one (from the history list) */
  openChat?: string | null
}

export default function ChatPanel({ className = '', openChat = null, ...props }: Props) {
  const { reading } = props
  const list = useResource(() => api.listConversations({ readingId: reading.id }), [reading.id])
  const start = list.data ? (list.data.find((c) => c.id === openChat) ?? list.data[0])?.id ?? null : null

  return (
    <section aria-label="Chat about this reading" className={`flex flex-col overflow-hidden rounded-3xl border border-ink/10 bg-surface shadow-sm ${className}`}>
      {list.data !== undefined ? (
        <ChatShell key={reading.id} {...props} first={start} conversations={list.data} reload={list.reload} />
      ) : list.error ? (
        <div className="grid flex-1 place-items-center p-8 text-center">
          <div>
            <p role="alert" className="text-sm text-danger">
              {list.error}
            </p>
            <button type="button" onClick={list.reload} className="btn btn-ghost btn-sm mt-4">
              Try again
            </button>
          </div>
        </div>
      ) : (
        <div className="flex-1 space-y-4 p-6" aria-busy="true">
          <div className="h-10 w-2/3 animate-pulse rounded-2xl bg-ink/5" />
          <div className="ml-auto h-10 w-1/2 animate-pulse rounded-2xl bg-ink/5" />
          <div className="h-16 w-3/4 animate-pulse rounded-2xl bg-ink/5" />
        </div>
      )}
    </section>
  )
}

type ShellProps = Props & { first: string | null; conversations: Conversation[]; reload: () => void }

function ChatShell({ reading, profile, first, conversations, reload, onFocusLine, onShowSection, onSwitchProfile }: ShellProps) {
  // `key` restarts the thread (new chat, or another chat); `id` is the conversation it is showing, if any yet
  const [view, setView] = useState<{ key: number; id: string | null }>({ key: 0, id: first })
  const [deleting, setDeleting] = useState<Conversation | null>(null)

  const restart = (id: string | null) => setView((v) => ({ key: v.key + 1, id }))

  return (
    <>
      <header className="flex items-center gap-3 border-b border-ink/10 px-4 py-3">
        <PlanetAvatar seed={profile.id} size={38} />
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-base leading-tight">Chat about {profile.name}’s reading</h2>
          <p className="text-xs leading-snug text-muted">Answers use only this reading</p>
        </div>
        <Menu
          ariaLabel="Chats for this reading"
          panelClassName="!min-w-72"
          button={
            <span className="btn btn-ghost btn-sm">
              Chats <span className="text-muted">{conversations.length}</span> <Icon name="chevron-down" size={14} />
            </span>
          }
        >
          {(close) => (
            <>
              <button
                type="button"
                onClick={() => {
                  close()
                  restart(null)
                }}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5"
              >
                <Icon name="plus" size={16} /> New chat
              </button>
              {conversations.length > 0 && (
                <ul className="mt-1 border-t border-ink/10 pt-1">
                  {conversations.map((c) => (
                    <li key={c.id} className="flex items-center gap-1">
                      <button
                        type="button"
                        aria-current={c.id === view.id}
                        onClick={() => {
                          close()
                          if (c.id !== view.id) restart(c.id)
                        }}
                        className={`min-w-0 flex-1 rounded-xl px-3 py-2 text-left text-sm hover:bg-ink/5 ${c.id === view.id ? 'bg-accent/15' : ''}`}
                      >
                        <span className="block truncate">{c.title}</span>
                        <span className="block text-xs text-muted">
                          {formatDate(c.updatedAt)} · {c.messageCount} messages
                        </span>
                      </button>
                      <button
                        type="button"
                        aria-label={`Delete chat: ${c.title}`}
                        onClick={() => {
                          close()
                          setDeleting(c)
                        }}
                        className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted hover:bg-danger/10 hover:text-danger"
                      >
                        <Icon name="trash" size={15} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Menu>
        <button type="button" onClick={() => restart(null)} aria-label="Start a new chat" title="New chat" className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-ink/20 hover:border-accent">
          <Icon name="plus" size={16} />
        </button>
      </header>

      <Thread
        key={view.key}
        reading={reading}
        profile={profile}
        startId={view.id}
        onCreated={(id) => setView((v) => ({ ...v, id }))}
        onChanged={reload}
        onFocusLine={onFocusLine}
        onShowSection={onShowSection}
        onSwitchProfile={onSwitchProfile}
      />

      <DeleteChatModal
        chat={deleting}
        onClose={() => setDeleting(null)}
        onDeleted={(id) => {
          reload()
          if (id === view.id) restart(null)
        }}
      />
    </>
  )
}

type ThreadProps = MessageHandlers & {
  reading: Reading
  profile: HandProfile
  startId: string | null
  onCreated: (id: string) => void
  onChanged: () => void
}

function Thread({ reading, profile, startId, onCreated, onChanged, onFocusLine, onShowSection, onSwitchProfile }: ThreadProps) {
  const { profiles } = useData()
  // the conversation this thread opened with never changes while it is mounted
  const [openedWith] = useState(startId)
  const saved = useResource(() => (openedWith ? api.getConversation(openedWith) : Promise.resolve(null)), [openedWith ?? ''])

  const [convoId, setConvoId] = useState(openedWith)
  const [added, setAdded] = useState<Message[]>([])
  const [freshId, setFreshId] = useState<string | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const log = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)
  const inputId = useId()
  const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

  // a chat opened from the list starts at its newest message, also when it finished loading while hidden in another tab
  const loadedChat = saved.data
  const startedAtEnd = useRef(false)
  useEffect(() => {
    const el = log.current
    if (!loadedChat || !el) return
    const toEnd = () => {
      if (startedAtEnd.current || el.clientHeight === 0) return
      startedAtEnd.current = true
      el.scrollTop = el.scrollHeight
    }
    toEnd()
    const watcher = new ResizeObserver(toEnd)
    watcher.observe(el)
    return () => watcher.disconnect()
  }, [loadedChat])

  const messages = [...(saved.data?.messages ?? []), ...added]
  const loadingSaved = !!openedWith && saved.data === undefined && !saved.error

  const lineName = useCallback((id: FeatureId) => reading.hands.left.features.find((f) => f.id === id)?.name ?? id, [reading])
  const others = (profiles ?? []).filter((p) => p.id !== profile.id)

  const pin = useCallback(() => {
    const el = log.current
    if (!el) return
    // keep up with the growing answer, unless the person has scrolled away from the bottom
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 220) el.scrollTop = el.scrollHeight
  }, [])
  const toBottom = () => {
    requestAnimationFrame(() => {
      const el = log.current
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: reduced ? 'auto' : 'smooth' })
    })
  }

  const grow = () => {
    const el = box.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 112)}px`
  }

  const send = async (raw: string) => {
    const text = raw.trim()
    if (!text || pending) return
    setError(null)
    setPending(text)
    setDraft('')
    requestAnimationFrame(grow)
    toBottom()
    let startedHere: string | null = null
    try {
      let id = convoId
      if (!id) {
        // the chat is only created when its first question is asked, so an unused chat never exists
        id = (await api.createConversation(reading.id)).id
        startedHere = id
      }
      const { user, assistant } = await api.sendMessage(id, text)
      if (startedHere) {
        setConvoId(startedHere)
        onCreated(startedHere)
      }
      setAdded((prev) => [...prev, user, assistant])
      setFreshId(assistant.id)
      onChanged()
    } catch (err) {
      // a first question that failed leaves no empty chat behind
      if (startedHere) void api.deleteConversation(startedHere).catch(() => {})
      setError(errorMessage(err))
      setDraft(text)
    } finally {
      setPending(null)
      box.current?.focus()
      toBottom()
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void send(draft)
    }
  }

  const suggestions = [
    'Summarise this reading',
    'What does the heart line say?',
    'Compare the two hands',
    'What was unclear in the photos?',
    ...(others[0] ? [`What about ${others[0].name}’s heart line?`] : []),
  ]

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={log} role="log" aria-label="Conversation" aria-live="polite" tabIndex={0} className="focus-own min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-5 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-focus">
        {loadingSaved ? (
          <div className="space-y-4" aria-busy="true">
            <div className="ml-auto h-10 w-1/2 animate-pulse rounded-2xl bg-ink/5" />
            <div className="h-20 w-3/4 animate-pulse rounded-2xl bg-ink/5" />
          </div>
        ) : saved.error ? (
          <p role="alert" className="text-sm text-danger">
            {saved.error}
          </p>
        ) : messages.length === 0 && !pending ? (
          <div className="flex min-h-full flex-col justify-center gap-5 py-4">
            <div>
              <p className="font-display text-2xl font-light leading-snug">Ask about {profile.name}’s reading.</p>
              <p className="mt-2 text-sm text-muted">Answers use only what was found in this reading. A line that was not seen is never described, and no other profile’s results are ever used here.</p>
            </div>
            <ul className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <li key={s}>
                  <button type="button" onClick={() => void send(s)} className="rounded-full border border-ink/20 px-3.5 py-2 text-left text-sm transition-colors hover:border-accent hover:bg-accent/10">
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <>
            {messages.map((m) => (
              <MessageView
                key={m.id}
                message={m}
                animate={!reduced && m.id === freshId}
                profiles={profiles ?? []}
                lineName={lineName}
                onTick={pin}
                onFocusLine={onFocusLine}
                onShowSection={onShowSection}
                onSwitchProfile={onSwitchProfile}
              />
            ))}
            {pending && (
              <>
                <div className="flex justify-end">
                  <p className="max-w-[88%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-sm text-paper">{pending}</p>
                </div>
                <Typing />
              </>
            )}
          </>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          void send(draft)
        }}
        className="border-t border-ink/10 p-3 md:p-4"
      >
        {error && (
          <p role="alert" className="mb-2 flex items-start gap-2 text-sm text-danger">
            <Icon name="alert" className="mt-0.5" /> {error}
          </p>
        )}
        <div className="flex items-end gap-2 rounded-2xl border border-ink/20 bg-paper/60 p-2 transition-[border-color,box-shadow] focus-within:border-focus focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus)_28%,transparent)]">
          <label htmlFor={inputId} className="sr-only">
            Your question
          </label>
          <textarea
            id={inputId}
            ref={box}
            rows={1}
            value={draft}
            maxLength={MESSAGE_MAX}
            onChange={(e) => {
              setDraft(e.target.value)
              grow()
            }}
            onKeyDown={onKey}
            placeholder="Ask about a line, or compare the hands"
            className="focus-own max-h-28 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm placeholder:text-muted"
          />
          <button
            type="submit"
            disabled={!draft.trim() || !!pending}
            aria-label="Send question"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-ink text-paper transition-colors hover:bg-accent hover:text-on-accent disabled:pointer-events-none disabled:opacity-40"
          >
            <Icon name="send" size={17} />
          </button>
        </div>
        <div className="mt-2 flex items-start justify-between gap-3 text-[0.7rem] leading-snug text-muted">
          <div className="space-y-1">
            <p>{DISCLAIMER_SHORT}</p>
            {!reading.meta.mock && (
              <p>Answers may be written by Gemini (Google). It gets your question with names and contact details removed, never the photos. Keep private details out.</p>
            )}
          </div>
          {draft.length > MESSAGE_MAX * 0.8 && (
            <p className="shrink-0 tabular-nums" aria-live="polite">
              {draft.length} / {MESSAGE_MAX}
            </p>
          )}
        </div>
      </form>
    </div>
  )
}
