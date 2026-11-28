import { useEffect, useRef, useState } from 'react'
import { BRAND } from '../../brand'
import type { BoundaryKind, FeatureId, HandProfile, Message } from '../../api/types'
import Icon from '../../components/ui/icons'
import { featureNumber } from '../../lib/features'
import { t, tServer } from '../../i18n'

// One message in the chat. The assistant's answers can carry a few extras, all driven by flags from the server:
//   - chips for the lines the answer was based on (point back at the hands)
//   - a small reminder that palmistry is an old art and not a science
//   - a note when the question was outside what a reading can do, or about something that was not seen
//   - a button to switch profile when the question was about someone else
//   - who wrote the answer when the language model was involved: "written by Gemini, and checked", or the reason the
//     fixed wording answered instead (a used-up allowance, a failed check, a slow reply)

export type MessageHandlers = {
  onFocusLine: (id: FeatureId) => void
  onShowSection: (section: 'summary' | 'comparison' | 'uncertainty' | 'themes' | 'shape') => void
  onSwitchProfile: (profileId: string) => void
}

const BOUNDARY_LABEL: Record<BoundaryKind, string> = {
  medical: t("Outside what a reading can do: health"),
  financial: t("Outside what a reading can do: money"),
  employment: t("Outside what a reading can do: work"),
  relationship: t("Outside what a reading can do: relationships"),
  lifespan: t("The life line is not a clock"),
  prediction: t("The road ahead is read, not fixed"),
  not_seen: t("Not seen clearly in the photos, so not described"),
  off_topic: t("Outside what this reading covers"),
}

const SECTION_LABEL = { summary: t("The summary"), comparison: t("The comparison"), uncertainty: t("What was unclear"), themes: t("The themes"), shape: t("The hand shape") } as const

export function AssistantAvatar() {
  return (
    <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent/30 text-accent-ink">
      <Icon name="spark" size={16} />
    </span>
  )
}

/** Bullets and paragraphs from the plain text the server sends ("• " starts a bullet, a blank line a new paragraph). */
export function MessageText({ text }: { text: string }) {
  const blocks = text.split('\n\n')
  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        const lines = block.split('\n')
        const groups: { bullets: boolean; lines: string[] }[] = []
        for (const line of lines) {
          const bullet = line.startsWith('• ')
          const body = bullet ? line.slice(2) : line
          const last = groups[groups.length - 1]
          if (last && last.bullets === bullet) last.lines.push(body)
          else groups.push({ bullets: bullet, lines: [body] })
        }
        return (
          <div key={i} className="space-y-1.5">
            {groups.map((g, j) =>
              g.bullets ? (
                <ul key={j} className="list-disc space-y-1 pl-5 marker:text-muted">
                  {g.lines.map((l, k) => (
                    <li key={k}>{l}</li>
                  ))}
                </ul>
              ) : (
                g.lines.map((l, k) => <Line key={`${j}-${k}`} text={l} />)
              ),
            )}
          </div>
        )
      })}
    </div>
  )
}

/** "Left hand (detected): ..." gets its hand picked out, so a two-hand answer is easy to scan. */
function Line({ text }: { text: string }) {
  const m = /^(Left hand|Right hand|Side by side)(?: \(([^)]+)\))?:\s*([\s\S]*)$/.exec(text)
  if (!m) return <p>{text}</p>
  return (
    <p>
      <strong className="font-medium">{m[1]}</strong>
      {m[2] && <span className="text-muted"> ({m[2]})</span>}: {m[3]}
    </p>
  )
}

/** Reveals text a few characters at a time. Skipped entirely when `enabled` is false. */
function useTyped(text: string, enabled: boolean, onTick: () => void) {
  const [shown, setShown] = useState(enabled ? 0 : text.length)
  const tick = useRef(onTick)
  useEffect(() => {
    tick.current = onTick
  })
  useEffect(() => {
    if (!enabled) return
    let n = 0
    const step = Math.max(2, Math.ceil(text.length / 140))
    const timer = window.setInterval(() => {
      n = Math.min(text.length, n + step)
      setShown(n)
      tick.current()
      if (n >= text.length) window.clearInterval(timer)
    }, 16)
    return () => window.clearInterval(timer)
  }, [text, enabled])
  return enabled ? shown : text.length
}

export function Typing() {
  return (
    <div className="flex gap-3" role="status" aria-label={t("{short} is writing a reply", { short: BRAND.short })}>
      <AssistantAvatar />
      <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-md border border-ink/10 bg-surface px-4 py-3.5">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-2 w-2 animate-bounce rounded-full bg-muted motion-reduce:animate-pulse" style={{ animationDelay: `${i * 140}ms` }} />
        ))}
      </div>
    </div>
  )
}

type Props = MessageHandlers & {
  message: Message
  /** type this answer out (only the newest one, and only when motion is welcome) */
  animate: boolean
  profiles: HandProfile[]
  lineName: (id: FeatureId) => string
  onTick: () => void
}

export default function MessageView({ message, animate, profiles, lineName, onTick, onFocusLine, onShowSection, onSwitchProfile }: Props) {
  const typed = useTyped(message.text, animate && message.role === 'assistant', onTick)
  const finished = typed >= message.text.length

  // when typing ends, the chips and reminder appear under the answer: keep the end of it in view
  useEffect(() => {
    if (animate && finished) onTick()
  }, [animate, finished, onTick])

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[88%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-sm text-paper">{message.text}</p>
      </div>
    )
  }

  const done = finished
  const flags = message.flags
  const refs = message.refs
  const ids = refs?.featureIds ?? []
  const wholeReport = ids.length >= 5
  const sec = refs?.section
  const section = sec === 'summary' || sec === 'comparison' || sec === 'uncertainty' || sec === 'themes' || sec === 'shape' ? sec : null
  const switchTo = flags?.switchProfileId ? profiles.find((p) => p.id === flags.switchProfileId) : null

  return (
    <div className="flex gap-3">
      <AssistantAvatar />
      <div className="min-w-0 max-w-[92%] rounded-2xl rounded-tl-md border border-ink/10 bg-surface px-4 py-3 text-sm leading-relaxed">
        {done ? (
          <MessageText text={message.text} />
        ) : (
          <>
            <span className="sr-only">{message.text}</span>
            <div aria-hidden="true">
              <MessageText text={message.text.slice(0, typed)} />
            </div>
          </>
        )}

        {done && (
          <div className="page-in mt-3 space-y-3">
            {flags?.boundary && (
              <p className="inline-flex items-center gap-2 rounded-full bg-accent2/20 px-3 py-1 text-xs">
                <Icon name="info" size={13} /> {BOUNDARY_LABEL[flags.boundary]}
              </p>
            )}

            {switchTo && (
              <button type="button" onClick={() => onSwitchProfile(switchTo.id)} className="btn btn-primary btn-sm">
                {t('Switch to {name}', { name: switchTo.name })} <Icon name="arrow-right" size={14} />
              </button>
            )}

            {(section || (ids.length > 0 && !wholeReport)) && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted">{t("Based on")}</span>
                {!wholeReport &&
                  ids.map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => onFocusLine(id)}
                      className="inline-flex items-center gap-1.5 rounded-full border border-ink/15 py-0.5 pl-0.5 pr-2.5 text-xs transition-colors hover:border-accent"
                    >
                      <span className="grid h-5 w-5 place-items-center rounded-full bg-ink text-[0.65rem] font-semibold text-paper">{featureNumber(id)}</span>
                      {t(lineName(id))}
                    </button>
                  ))}
                {section && (
                  <button
                    type="button"
                    onClick={() => onShowSection(section)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-ink/15 px-2.5 py-1 text-xs transition-colors hover:border-accent"
                  >
                    {SECTION_LABEL[section]}
                  </button>
                )}
              </div>
            )}

            {message.source === 'gemini' && (
              <p className="flex items-start gap-1.5 text-xs text-muted">
                <Icon name="spark" size={13} className="mt-0.5 shrink-0" /> {t("Written by Gemini from your results and our palmistry notes, and checked before it was shown.")}
              </p>
            )}
            {message.source === 'knowledge-base' && message.note && (
              <p className="flex items-start gap-1.5 text-xs text-muted">
                <Icon name="info" size={13} className="mt-0.5 shrink-0" /> {tServer(message.note)}
              </p>
            )}

            {flags?.disclaimer && <p className="text-xs text-muted">{t("An old art, not a science: a story about who you may become, not a promise.")}</p>}
          </div>
        )}
      </div>
    </div>
  )
}
