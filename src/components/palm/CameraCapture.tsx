import { useCallback, useEffect, useRef, useState } from 'react'
import type { HandSide } from '../../api/types'
import { cameraAvailable } from '../../lib/camera'
import Icon from '../ui/icons'
import Modal from '../ui/Modal'
import Spinner from '../ui/Spinner'

/** Why the camera could not be used, in words a person can act on. */
function cameraMessage(e: unknown): string {
  const name = e instanceof DOMException || e instanceof Error ? e.name : ''
  if (typeof window !== 'undefined' && !window.isSecureContext) return 'The browser only allows the camera on a secure page (https:// or localhost). Upload a photo instead.'
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'The camera is blocked. Allow it in the address bar of the browser and try again, or upload a photo instead.'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No camera was found on this device. Upload a photo instead.'
  if (name === 'NotReadableError' || name === 'AbortError') return 'The camera could not be started. Another app may be using it. Close that app and try again, or upload a photo instead.'
  return 'The camera could not be opened. Upload a photo instead.'
}

/**
 * A hand-shaped guide drawn over the live picture: four fingers and a thumb, dashed. `thumbLeft` says which side the thumb sits on
 * in what the person sees on screen.
 */
function HandGuide({ thumbLeft }: { thumbLeft: boolean }) {
  return (
    <svg viewBox="10 85 280 280" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" preserveAspectRatio="xMidYMid meet">
      <g
        transform={thumbLeft ? undefined : 'translate(300,0) scale(-1,1)'}
        fill="rgba(255,255,255,0.06)"
        stroke="rgba(255,255,255,0.8)"
        strokeWidth="2.5"
        strokeDasharray="7 6"
        strokeLinecap="round"
      >
        <rect x="95" y="205" width="112" height="128" rx="26" />
        <rect x="96" y="128" width="24" height="86" rx="12" />
        <rect x="124" y="108" width="24" height="106" rx="12" />
        <rect x="152" y="120" width="24" height="94" rx="12" />
        <rect x="180" y="146" width="24" height="68" rx="12" />
        <rect x="52" y="235" width="26" height="78" rx="13" transform="rotate(-32 90 300)" />
      </g>
    </svg>
  )
}

function CameraView({ side, onCapture, onClose }: { side: HandSide; onCapture: (file: File) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const timer = useRef<number | null>(null)
  const [phase, setPhase] = useState<'starting' | 'live' | 'error'>('starting')
  const [message, setMessage] = useState('')
  const [facing, setFacing] = useState<'environment' | 'user'>('environment')
  const [mirrored, setMirrored] = useState(true)
  const [cameras, setCameras] = useState(1)
  const [count, setCount] = useState<number | null>(null)

  const stopStream = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
  }, [])

  const stopTimer = useCallback(() => {
    if (timer.current !== null) window.clearInterval(timer.current)
    timer.current = null
  }, [])

  // open the camera (again when the person switches between the front and back camera); close it when this view goes away
  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        if (!cameraAvailable()) throw new Error('unavailable')
        const s = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } },
          audio: false,
        })
        if (dead) {
          s.getTracks().forEach((t) => t.stop())
          return
        }
        stream.current = s
        const el = video.current
        if (el) {
          el.srcObject = s
          await el.play()
        }
        // a picture from the back camera is shown as it is; a front camera or a webcam is shown mirrored, like a mirror. What is
        // saved is never mirrored: the server checks which hand it is.
        setMirrored(s.getVideoTracks()[0]?.getSettings().facingMode !== 'environment')
        const all = await navigator.mediaDevices.enumerateDevices()
        if (!dead) setCameras(all.filter((d) => d.kind === 'videoinput').length)
        if (!dead) setPhase('live')
      } catch (e) {
        if (dead) return
        stopStream()
        setMessage(cameraMessage(e))
        setPhase('error')
      }
    })()
    return () => {
      dead = true
      stopStream()
    }
  }, [facing, stopStream])

  useEffect(() => stopTimer, [stopTimer])

  const snap = useCallback(() => {
    const el = video.current
    if (!el || !el.videoWidth) return
    const canvas = document.createElement('canvas')
    canvas.width = el.videoWidth
    canvas.height = el.videoHeight
    canvas.getContext('2d')?.drawImage(el, 0, 0) // the frame as the camera saw it, not mirrored
    canvas.toBlob(
      (blob) => {
        if (blob) onCapture(new File([blob], 'camera.jpg', { type: 'image/jpeg' }))
      },
      'image/jpeg',
      0.92,
    )
  }, [onCapture])

  const startTimer = () => {
    if (timer.current !== null) {
      stopTimer()
      setCount(null)
      return
    }
    let left = 3
    setCount(left)
    timer.current = window.setInterval(() => {
      left -= 1
      if (left <= 0) {
        stopTimer()
        setCount(null)
        snap()
      } else {
        setCount(left)
      }
    }, 1000)
  }

  const switchCamera = () => {
    stopTimer()
    setCount(null)
    setPhase('starting')
    setFacing((f) => (f === 'environment' ? 'user' : 'environment'))
  }

  // the thumb of a right palm held to the camera is on the right of the camera's picture; the mirror flips what is shown
  const thumbLeft = mirrored ? side === 'right' : side === 'left'

  if (phase === 'error') {
    return (
      <div>
        <p role="alert" className="flex items-start gap-2 rounded-2xl bg-danger/10 p-4 text-sm">
          <Icon name="alert" size={16} className="mt-0.5 shrink-0 text-danger" /> {message}
        </p>
        <div className="mt-4 flex justify-end">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="relative aspect-[4/3] overflow-hidden rounded-2xl bg-black">
        <video ref={video} playsInline muted className={`h-full w-full object-cover ${mirrored ? '[transform:scaleX(-1)]' : ''}`} aria-label="Live camera picture" />
        {phase === 'live' && <HandGuide thumbLeft={thumbLeft} />}
        {phase === 'starting' && (
          <div className="absolute inset-0 grid place-items-center text-white">
            <span className="flex items-center gap-2 text-sm">
              <Spinner size={18} /> Opening the camera…
            </span>
          </div>
        )}
        {count !== null && (
          <div className="absolute inset-0 grid place-items-center bg-black/25" aria-live="assertive">
            <span className="font-display text-8xl font-light text-white">{count}</span>
          </div>
        )}
      </div>
      <p className="mt-3 text-sm text-muted">
        Hold your {side} palm flat to the camera inside the outline, fingers together, in even light. Keep the whole hand in the picture.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button type="button" className="btn btn-primary" onClick={snap} disabled={phase !== 'live' || count !== null}>
          <Icon name="camera" size={16} /> Take photo
        </button>
        <button type="button" className="btn btn-ghost" onClick={startTimer} disabled={phase !== 'live'}>
          <Icon name="clock" size={16} /> {count !== null ? 'Cancel timer' : 'Timer: 3 seconds'}
        </button>
        {cameras > 1 && (
          <button type="button" className="btn btn-ghost" onClick={switchCamera} disabled={phase === 'starting'}>
            <Icon name="swap" size={16} /> Other camera
          </button>
        )}
        <button type="button" className="btn btn-ghost ml-auto" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  )
}

/** The camera in a dialog. `onCapture` gets one JPEG file; the dialog is closed by whoever opened it. Nothing is saved. */
export default function CameraCapture({ open, side, onClose, onCapture }: { open: boolean; side: HandSide; onClose: () => void; onCapture: (file: File) => void }) {
  return (
    <Modal open={open} onClose={onClose} title="Take a photo of your palm">
      <CameraView side={side} onCapture={onCapture} onClose={onClose} />
    </Modal>
  )
}
