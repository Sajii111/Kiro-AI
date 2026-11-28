import { useRef, useState, type DragEvent } from 'react'
import type { HandSide } from '../../api/types'
import HandMark from '../../components/HandMark'
import Icon from '../../components/ui/icons'
import Menu from '../../components/ui/Menu'
import Spinner from '../../components/ui/Spinner'
import { formatBytes } from '../../lib/format'
import { ACCEPT, SAMPLE_LABEL, type SampleKind } from '../../lib/photo'
import CheckList from './CheckList'
import type { Slot } from './slots'
import { t } from '../../i18n'

type Props = {
  side: HandSide
  slot: Slot
  onFile: (file: File) => void
  onSample: (kind: SampleKind) => void
  onClear: () => void
  /** draw the eye to this slot (the person tried to continue without it) */
  attention?: boolean
}

const SAMPLES: SampleKind[] = ['clear', 'blurry', 'dark', 'cropped', 'small', 'not_a_palm']

export default function PhotoSlot({ side, slot, onFile, onSample, onClear, attention = false }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const label = side === 'left' ? t("Left palm") : t("Right palm")
  const thumb = side === 'left' ? 'left' : 'right'

  const pick = () => input.current?.click()
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    const file = e.dataTransfer.files[0]
    if (file) onFile(file)
  }
  const dropProps = {
    onDragOver: (e: DragEvent) => {
      e.preventDefault()
      setOver(true)
    },
    onDragLeave: () => setOver(false),
    onDrop,
  }

  const sampleMenu = (
    <Menu
      ariaLabel={t("Try a sample photo for the {side} palm", { side: side })}
      align="left"
      button={
        <span className="btn btn-ghost btn-sm">
          {t("Try a sample")}{' '}<Icon name="chevron-down" size={14} />
        </span>
      }
    >
      {(close) => (
        <ul>
          <li className="px-3 pb-1 pt-2 text-xs text-muted">{t("Made from a drawing, not a real hand.")}</li>
          {SAMPLES.map((kind) => (
            <li key={kind}>
              <button
                type="button"
                onClick={() => {
                  close()
                  onSample(kind)
                }}
                className="w-full rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5"
              >
                {SAMPLE_LABEL[kind]}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Menu>
  )

  return (
    <section aria-label={label} className={`card flex flex-col p-5 md:p-6 ${attention ? 'border-danger shadow-[0_0_0_1px_var(--danger)]' : ''}`}>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (file) onFile(file)
        }}
      />

      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="font-display text-2xl font-normal">{label}</h2>
        <p className="text-xs text-muted">{thumb === 'left' ? t('Palm to camera, thumb on the left') : t('Palm to camera, thumb on the right')}</p>
      </div>

      {/* ---------------------------------------------------------- empty */}
      {(slot.status === 'empty' || slot.status === 'rejected') && (
        <>
          <div
            {...dropProps}
            className={`flex aspect-[4/5] max-h-[26rem] w-full flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed px-6 text-center transition-colors ${
              over ? 'border-accent bg-accent/15' : attention ? 'border-danger/60 bg-danger/5' : 'border-ink/20 bg-paper/50'
            }`}
          >
            <span className="grid h-16 w-16 place-items-center rounded-full bg-accent/25 text-accent-ink">
              <HandMark size={42} />
            </span>
            <div>
              <p className="font-medium">{over ? t("Drop to use this photo") : t("Add a photo of your {side} palm", { side: side })}</p>
              <p className="mt-1 text-sm text-muted">{t("Drag it here, or choose one. JPG or PNG.")}</p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <button type="button" onClick={pick} className="btn btn-primary btn-sm">
                <Icon name="upload" size={15} /> {t("Choose a photo")}
              </button>
              {sampleMenu}
            </div>
          </div>
          {slot.status === 'rejected' && (
            <p role="alert" className="mt-4 flex items-start gap-2 rounded-2xl bg-danger/10 p-4 text-sm text-danger">
              <Icon name="alert" className="mt-0.5" />
              <span>
                <strong className="font-medium">{slot.name}</strong>
                <span className="mt-0.5 block">{slot.message}</span>
              </span>
            </p>
          )}
        </>
      )}

      {/* ---------------------------------------------------------- working */}
      {slot.status === 'preparing' && (
        <div className="flex aspect-[4/5] max-h-[26rem] w-full flex-col items-center justify-center gap-3 rounded-2xl bg-ink/5 text-sm text-muted" role="status">
          <Spinner size={22} />
          <p>{t("Opening and shrinking the photo…")}</p>
          <p className="max-w-[80%] truncate text-xs">{slot.name}</p>
        </div>
      )}

      {/* ---------------------------------------------------------- photo + checks */}
      {(slot.status === 'checking' || slot.status === 'ready') && (
        <div {...dropProps}>
          <div className={`relative overflow-hidden rounded-2xl bg-ink/5 ${over ? 'ring-2 ring-focus' : ''}`}>
            <img src={slot.photo.url} alt={t("Your {side} palm photo", { side: side })} className="mx-auto block max-h-[26rem] w-auto max-w-full object-contain" />
            {slot.status === 'checking' && (
              <div className="absolute inset-0 grid place-items-center bg-paper/55 backdrop-blur-[2px]">
                <span className="flex items-center gap-2 rounded-full bg-paper px-4 py-2 text-sm shadow">
                  <Spinner size={14} /> {t("Checking the photo…")}
                </span>
              </div>
            )}
          </div>

          <p className="mt-3 truncate text-xs text-muted" title={slot.photo.name}>
            {slot.photo.name} · {slot.photo.width} × {slot.photo.height} px · {formatBytes(slot.photo.blob.size)}
            {slot.photo.originalWidth !== slot.photo.width && t(" · shrunk from {originalWidth} × {originalHeight} px ({2})", { originalWidth: slot.photo.originalWidth, originalHeight: slot.photo.originalHeight, "2": formatBytes(slot.photo.originalBytes) })}
          </p>

          {slot.status === 'ready' && <Verdict slot={slot} />}

          <div className="mt-3">
            <CheckList checks={slot.status === 'ready' ? slot.result.checks : null} />
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" onClick={pick} disabled={slot.status === 'checking'} className="btn btn-ghost btn-sm">
              <Icon name="swap" size={15} /> {t("Replace")}
            </button>
            <button type="button" onClick={onClear} disabled={slot.status === 'checking'} className="btn btn-ghost btn-sm">
              <Icon name="x" size={15} /> {t("Remove")}
            </button>
            {slot.status === 'ready' && sampleMenu}
          </div>
        </div>
      )}
    </section>
  )
}

function Verdict({ slot }: { slot: Extract<Slot, { status: 'ready' }> }) {
  const failed = slot.result.checks.filter((c) => c.status === 'fail').length
  const warned = slot.result.checks.filter((c) => c.status === 'warn').length
  const tone = failed ? 'bg-danger/10 text-danger' : warned ? 'bg-uncertain/15 text-ink' : 'bg-detected/12 text-ink'
  const text = failed ? t("This photo needs replacing") : warned ? t("Usable, with a note") : t("This photo looks good")
  const sub = failed
    ? t("It did not pass every check. Choose a new photo to continue.")
    : warned
      ? t("You can continue, or swap it for a better one first.")
      : t("It passed every check.")
  return (
    <div role="status" className={`mt-3 flex items-start gap-3 rounded-2xl p-4 text-sm ${tone}`}>
      <Icon name={failed ? 'alert' : warned ? 'info' : 'check'} className="mt-0.5" />
      <span>
        <strong className="font-medium">{text}.</strong> {sub}
      </span>
    </div>
  )
}
