import { useId, useRef, useState } from 'react'
import type { HandSide } from '../../api/types'
import { cameraAvailable } from '../../lib/camera'
import { ACCEPT, preparePhoto, PhotoProblem, type PreparedPhoto } from '../../lib/photo'
import Icon from '../ui/icons'
import Spinner from '../ui/Spinner'
import CameraCapture from './CameraCapture'
import { t } from '../../i18n'

/**
 * One palm photo: take it with the camera (with a hand outline to guide), or choose a file. It is shrunk in the browser and
 * shown. The photo is kept only in this page's memory until it is sent, and is never saved anywhere.
 */
export default function PalmPhotoInput({
  photo,
  onPhoto,
  label,
  side = 'right',
  error,
  compact = false,
  disabled = false,
}: {
  photo: PreparedPhoto | null
  onPhoto: (photo: PreparedPhoto | null) => void
  label: string
  /** which palm is asked for: it decides which way the camera's hand outline faces */
  side?: HandSide
  /** a problem the server found with this photo */
  error?: string | null
  compact?: boolean
  disabled?: boolean
}) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [camera, setCamera] = useState(false)
  const canCamera = cameraAvailable()

  const choose = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    setProblem(null)
    try {
      onPhoto(await preparePhoto(file))
    } catch (e) {
      setProblem(e instanceof PhotoProblem ? e.message : t("That photo could not be opened. Please choose another one."))
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  const shown = problem ?? error ?? null
  const size = compact ? 'aspect-square' : 'aspect-[4/3]'
  const off = disabled || busy
  const pick = () => input.current?.click()

  return (
    <div>
      <input ref={input} id={id} type="file" accept={ACCEPT} className="sr-only" disabled={off} onChange={(e) => choose(e.target.files?.[0])} tabIndex={-1} />
      {photo ? (
        <div className={`relative overflow-hidden rounded-2xl border ${shown ? 'border-danger' : 'border-ink/15'} bg-ink/5 ${size}`}>
          <img src={photo.url} alt={label} className="h-full w-full object-cover" />
          {!disabled && (
            <div className="absolute inset-x-2 bottom-2 flex justify-end gap-2">
              {canCamera && (
                <button type="button" onClick={() => setCamera(true)} className="btn btn-ghost btn-sm bg-surface/85 backdrop-blur" aria-label={t("Retake {label} with the camera", { label: label })} title={t("Retake with the camera")}>
                  <Icon name="camera" size={14} /> {!compact && t("Retake")}
                </button>
              )}
              <button type="button" onClick={pick} className="btn btn-ghost btn-sm bg-surface/85 backdrop-blur" aria-label={t("Choose another file for {label}", { label: label })} title={t("Upload another photo")}>
                <Icon name="upload" size={14} /> {!compact && t("Upload")}
              </button>
              <button type="button" onClick={() => onPhoto(null)} className="btn btn-ghost btn-sm bg-surface/85 backdrop-blur" aria-label={t("Remove {label}", { label: label })} title={t("Remove")}>
                <Icon name="x" size={14} />
              </button>
            </div>
          )}
        </div>
      ) : (
        <div
          className={`flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed ${shown ? 'border-danger' : 'border-ink/20'} p-3 text-center text-sm text-muted ${size} ${disabled ? 'pointer-events-none opacity-50' : ''}`}
        >
          {busy ? <Spinner size={22} /> : <Icon name="hand" size={compact ? 22 : 34} />}
          <span className="font-medium text-ink">{label}</span>
          <div className={`flex ${compact ? 'flex-col' : 'flex-row'} flex-wrap items-center justify-center gap-2`}>
            {canCamera && (
              <button type="button" onClick={() => setCamera(true)} disabled={off} className={`btn ${compact ? 'btn-ghost btn-sm' : 'btn-primary btn-sm'}`}>
                <Icon name="camera" size={14} /> {t("Camera")}
              </button>
            )}
            <button type="button" onClick={pick} disabled={off} className={`btn btn-ghost btn-sm`}>
              <Icon name="upload" size={14} /> {t("Upload")}
            </button>
          </div>
          {!compact && <span className="text-xs">{canCamera ? t("Take a photo now, or choose a JPG or PNG.") : t("Choose a JPG or PNG. On a phone this offers the camera.")}</span>}
        </div>
      )}
      {shown && (
        <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-danger">
          <Icon name="alert" size={14} className="mt-0.5 shrink-0" /> {shown}
        </p>
      )}
      {canCamera && (
        <CameraCapture
          open={camera}
          side={side}
          onClose={() => setCamera(false)}
          onCapture={(file) => {
            setCamera(false)
            void choose(file)
          }}
        />
      )}
    </div>
  )
}
