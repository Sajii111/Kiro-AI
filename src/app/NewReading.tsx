import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { errorMessage, isAbort } from '../api/errors'
import type { HandSide, HandProfile, Reading } from '../api/types'
import PlanetAvatar from '../components/ui/PlanetAvatar'
import Icon from '../components/ui/icons'
import Menu from '../components/ui/Menu'
import Spinner from '../components/ui/Spinner'
import TextField from '../components/ui/TextField'
import { useToast } from '../components/ui/Toast'
import { plural } from '../lib/format'
import { makeSamplePhoto, PhotoProblem, preparePhoto, releasePhoto, SAMPLE_LABEL, type PreparedPhoto, type SampleKind } from '../lib/photo'
import { cleanReadingName, validateReadingName } from '../lib/validate'
import { useData } from '../state/data'
import { keepPhotos } from '../state/media'
import { PHOTO_PRIVACY, PHOTO_TIPS } from './copy'
import PhotoSlot from './new/PhotoSlot'
import Processing from './new/Processing'
import { isUsable, photoOf, type Slot } from './new/slots'
import { initialStages, type PreviewMap, type StageMap } from './new/stages'
import { CreateProfileModal } from './ProfileModals'

// The new-reading flow: choose whose palms, add one photo of each, see the checks, then watch the reading being made.
//
//   photos  -> processing -> done
//                         -> failed (try again, or go back and replace the photos)
//
// Photos stay in this tab's memory. They are shrunk in the browser, checked, and sent for the length of one request.

type Phase = 'photos' | 'processing' | 'done' | 'failed'
type Slots = Record<HandSide, Slot>
type Job = { photos: Record<HandSide, PreparedPhoto>; aligned: boolean }

const SIDES: HandSide[] = ['left', 'right']
const EMPTY: Slots = { left: { status: 'empty' }, right: { status: 'empty' } }

/** Sample photos that are drawn from the same hand as the sample backend's lines, so the lines sit exactly on them. */
const LINES_FIT: SampleKind[] = ['clear', 'blurry', 'dark']

/**
 * The built-in sample photos are drawings. The server is told so, because the hand finder it uses for real photos cannot
 * find a hand in a sketch. The one exception is "not a palm": it is meant to be refused, so it is judged like a real photo.
 */
const isSampleDrawing = (kind: SampleKind | null) => kind !== null && kind !== 'not_a_palm'

const isWorking = (slot: Slot) => slot.status === 'preparing' || slot.status === 'checking'

function problemWith(side: HandSide, slot: Slot): string | null {
  switch (slot.status) {
    case 'empty':
      return `Add your ${side} palm to continue.`
    case 'rejected':
      return `Replace the ${side} palm photo: it could not be used.`
    case 'ready':
      return slot.result.ok ? null : `Replace the ${side} palm photo: it did not pass the checks.`
    default:
      return null
  }
}

export default function NewReading() {
  const navigate = useNavigate()
  const toast = useToast()
  const { profiles, activeProfile, setActiveProfileId, refresh } = useData()

  const [slots, setSlotsState] = useState<Slots>(EMPTY)
  const slotsRef = useRef<Slots>(EMPTY)
  const tokens = useRef<Record<HandSide, number>>({ left: 0, right: 0 })
  const kinds = useRef<Record<HandSide, SampleKind | null>>({ left: null, right: null })
  const [tried, setTried] = useState(false)
  const [adding, setAdding] = useState(false)
  /** what the person typed as this reading's name; optional, and kept out of the photos' way */
  const [readingName, setReadingName] = useState('')

  const [phase, setPhase] = useState<Phase>('photos')
  const [runId, setRunId] = useState(0)
  const [job, setJob] = useState<Job | null>(null)
  const [stages, setStages] = useState<StageMap>(initialStages)
  const [previews, setPreviews] = useState<PreviewMap>({})
  const [reading, setReading] = useState<Reading | null>(null)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const runRef = useRef(0)
  /** true once the photos have been handed to the reading page, which frees them when the reading is deleted */
  const transferred = useRef(false)

  const setSlot = useCallback((side: HandSide, slot: Slot) => {
    slotsRef.current = { ...slotsRef.current, [side]: slot }
    setSlotsState(slotsRef.current)
  }, [])

  // ------------------------------------------------------------------ photos

  /** Opens a photo, shrinks it, then has it checked. A newer choice for the same side always wins. */
  const load = useCallback(
    async (side: HandSide, source: File | Promise<File>, label: string, kind: SampleKind | null) => {
      const token = ++tokens.current[side]
      const current = () => token === tokens.current[side]
      kinds.current[side] = kind
      releasePhoto(photoOf(slotsRef.current[side]))
      setSlot(side, { status: 'preparing', name: label })

      let photo: PreparedPhoto
      try {
        photo = await preparePhoto(await source, kind !== null)
      } catch (err) {
        if (!current()) return
        const message = err instanceof PhotoProblem ? err.message : 'This photo could not be opened. Please try another one.'
        setSlot(side, { status: 'rejected', name: label, message })
        return
      }
      if (!current()) {
        releasePhoto(photo)
        return
      }

      setSlot(side, { status: 'checking', photo })
      try {
        const result = await api.validatePhoto(side, photo.blob, { sample: isSampleDrawing(kind) })
        if (current()) setSlot(side, { status: 'ready', photo, result })
      } catch (err) {
        if (!current()) return
        releasePhoto(photo)
        setSlot(side, { status: 'rejected', name: label, message: errorMessage(err) })
      }
    },
    [setSlot],
  )

  const onFile = (side: HandSide, file: File) => void load(side, file, file.name, null)
  const onSample = (side: HandSide, kind: SampleKind) => void load(side, makeSamplePhoto(kind, side), SAMPLE_LABEL[kind], kind)

  const clear = (side: HandSide) => {
    tokens.current[side]++
    kinds.current[side] = null
    releasePhoto(photoOf(slotsRef.current[side]))
    setSlot(side, { status: 'empty' })
  }

  const useSamples = () => {
    onSample('left', 'clear')
    onSample('right', 'clear')
  }

  // ------------------------------------------------------------------ the reading

  const start = useCallback(async () => {
    const left = slotsRef.current.left
    const right = slotsRef.current.right
    if (!activeProfile || !isUsable(left) || !isUsable(right) || validateReadingName(readingName)) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const run = ++runRef.current
    const alive = () => runRef.current === run && !controller.signal.aborted

    // A sample reading (from the sample backend, from the built-in sample drawings, or from a server without the hand
    // model) is only drawn to fit the built-in sample photos. A real reading is drawn on the person's own photo.
    const fits = (kind: SampleKind | null) => kind !== null && LINES_FIT.includes(kind)
    const samplePhotos = fits(kinds.current.left) && fits(kinds.current.right)

    setJob({ photos: { left: left.photo, right: right.photo }, aligned: false })
    setStages(initialStages())
    setPreviews({})
    setReading(null)
    setError(null)
    setRunId(run)
    setPhase('processing')

    try {
      const result = await api.createReading(
        {
          profileId: activeProfile.id,
          name: cleanReadingName(readingName) || undefined,
          left: left.photo.blob,
          right: right.photo.blob,
          leftSample: isSampleDrawing(kinds.current.left),
          rightSample: isSampleDrawing(kinds.current.right),
        },
        (event) => {
          if (!alive()) return
          setStages((prev) => ({ ...prev, [event.stage]: { state: event.state, detail: event.detail ?? prev[event.stage].detail } }))
          if (event.previews) {
            const shown = event.previews
            setPreviews((prev) => ({ ...prev, [event.stage]: { ...prev[event.stage], ...shown } }))
          }
        },
        controller.signal,
      )
      if (!alive()) return
      const aligned = result.meta.mock ? samplePhotos : true
      setJob((prev) => (prev ? { ...prev, aligned } : prev))
      keepPhotos(result.id, { left: left.photo.url, right: right.photo.url, aligned })
      transferred.current = true
      setReading(result)
      setPhase('done')
      refresh()
    } catch (err) {
      if (!alive() || isAbort(err)) return
      // whatever step was running when it broke is the one to mark
      setStages((prev) => {
        const running = (Object.keys(prev) as (keyof StageMap)[]).find((key) => prev[key].state === 'running')
        return running ? { ...prev, [running]: { state: 'failed' } } : prev
      })
      setError(errorMessage(err))
      setPhase('failed')
    }
  }, [activeProfile, readingName, refresh])

  const cancel = () => {
    runRef.current++
    abortRef.current?.abort()
    setPhase('photos')
    toast('Cancelled. Nothing was saved.')
  }

  const another = () => {
    // the photos now belong to the reading that was just made, so they are not freed here
    transferred.current = false
    tokens.current.left++
    tokens.current.right++
    kinds.current = { left: null, right: null }
    slotsRef.current = EMPTY
    setSlotsState(EMPTY)
    setReadingName('')
    setTried(false)
    setJob(null)
    setReading(null)
    setPhase('photos')
  }

  // leaving the page: stop any work, and let go of photos nobody else holds
  useEffect(
    () => () => {
      runRef.current++
      abortRef.current?.abort()
      tokens.current.left++
      tokens.current.right++
      if (!transferred.current) {
        releasePhoto(photoOf(slotsRef.current.left))
        releasePhoto(photoOf(slotsRef.current.right))
      }
    },
    [],
  )

  // (braces matter: modern browsers return a Promise from scrollTo, and an effect must not return one)
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [phase])

  // ------------------------------------------------------------------ what the screen says

  const busy = isWorking(slots.left) || isWorking(slots.right)
  const ready = isUsable(slots.left) && isUsable(slots.right)
  // an empty name is fine (the reading then goes by its date); a name that breaks the rules holds the reading back
  const nameProblem = validateReadingName(readingName)
  const canStart = ready && !busy && !!activeProfile && !nameProblem
  const warned = SIDES.filter((s) => {
    const slot = slots[s]
    return slot.status === 'ready' && slot.result.checks.some((c) => c.status === 'warn')
  }).length

  const problems = SIDES.map((side) => problemWith(side, slots[side])).filter((text): text is string => text !== null)
  const bothEmpty = slots.left.status === 'empty' && slots.right.status === 'empty'
  const helper = !activeProfile
    ? 'Choose or add a hand profile to continue.'
    : busy
      ? 'Checking your photos…'
      : canStart
        ? warned === 0
          ? `Both photos passed. Ready to read ${activeProfile.name}’s palms.`
          : `Both photos can be used, ${warned === 1 ? 'one has a note' : 'both have notes'}. Continue, or swap ${warned === 1 ? 'it' : 'them'} for a better photo.`
        : ready
          ? (nameProblem ?? '')
          : bothEmpty
            ? 'Add a photo of each palm to continue.'
            : problems.join(' ')

  const explain = () => {
    setTried(true)
    const first = SIDES.find((side) => !isUsable(slotsRef.current[side]) && !isWorking(slotsRef.current[side]))
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const target = first ? `slot-${first}` : nameProblem ? 'reading-name' : null
    if (target) document.getElementById(target)?.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' })
  }

  // ------------------------------------------------------------------ the three views

  if (phase !== 'photos' && job) {
    return (
      <Processing
        key={runId}
        phase={phase}
        stages={stages}
        previews={previews}
        photos={job.photos}
        reading={reading}
        aligned={job.aligned}
        error={error}
        onCancel={cancel}
        onRetry={() => void start()}
        onReplace={() => setPhase('photos')}
        onOpen={() => reading && navigate(`/app/readings/${reading.id}`)}
        onAnother={another}
      />
    )
  }

  return (
    <div>
      <p className="kicker">New reading</p>
      <h1 className="mt-3 max-w-3xl text-balance font-display text-4xl font-light tracking-tight md:text-6xl">One clear photo of each palm.</h1>
      <p className="mt-4 max-w-xl text-muted">Both photos are checked before anything is done with them. They are shrunk here in your browser and are never saved.</p>

      <div className="mt-8">
        {profiles === null ? (
          <div className="h-12 w-56 animate-pulse rounded-full bg-ink/5" aria-busy="true" />
        ) : profiles.length === 0 ? (
          <NoProfile onAdd={() => setAdding(true)} />
        ) : (
          activeProfile && (
            <>
              <ProfilePicker profiles={profiles} active={activeProfile} onPick={setActiveProfileId} onAdd={() => setAdding(true)} />
              {activeProfile.readingCount > 0 && (
                // a profile can have many readings; this says what happens to the older ones, and which one the chat uses
                <p className="mt-3 max-w-xl text-sm text-muted">
                  This adds a new reading to {activeProfile.name}’s history ({plural(activeProfile.readingCount, 'reading')} so far). Earlier ones stay as they are. The chat uses the newest reading unless you pick another.
                </p>
              )}
            </>
          )
        )}
      </div>

      {(profiles === null || profiles.length > 0) && (
        <>
          <div id="reading-name" className="mt-8 max-w-md scroll-mt-28">
            <TextField
              label="Name this reading (optional)"
              value={readingName}
              onChange={(e) => setReadingName(e.target.value)}
              placeholder="For example: Before my trip"
              autoComplete="off"
              error={nameProblem}
              hint="Without a name, the reading goes by its date. You can add or change it later."
            />
          </div>

          <div className="mt-8 grid gap-5 md:grid-cols-2">
            {SIDES.map((side) => (
              <div key={side} id={`slot-${side}`} className="scroll-mt-28">
                <PhotoSlot
                  side={side}
                  slot={slots[side]}
                  onFile={(file) => onFile(side, file)}
                  onSample={(kind) => onSample(side, kind)}
                  onClear={() => clear(side)}
                  attention={tried && !isUsable(slots[side]) && !isWorking(slots[side])}
                />
              </div>
            ))}
          </div>

          <div className="mt-6 grid gap-5 md:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <section aria-labelledby="tips-h" className="card p-6">
              <h2 id="tips-h" className="font-display text-xl font-normal">
                For a photo that reads well
              </h2>
              <ul className="mt-4 space-y-3 text-sm">
                {PHOTO_TIPS.map((tip) => (
                  <li key={tip} className="flex items-start gap-3">
                    <Icon name="check" size={16} className="mt-0.5 shrink-0 text-accent-ink" />
                    <span>{tip}</span>
                  </li>
                ))}
              </ul>
            </section>

            <section aria-labelledby="priv-h" className="card flex flex-col gap-4 p-6">
              <div>
                <h2 id="priv-h" className="flex items-center gap-2 font-display text-xl font-normal">
                  <Icon name="shield" size={18} className="text-accent-ink" /> Your photos
                </h2>
                <p className="mt-3 text-sm text-muted">{PHOTO_PRIVACY}</p>
              </div>
              <div className="mt-auto border-t border-ink/10 pt-4">
                <p className="text-sm text-muted">No palm to hand? Try the screens with sample photos made from a drawing.</p>
                <button type="button" onClick={useSamples} disabled={busy} className="btn btn-ghost btn-sm mt-3">
                  <Icon name="spark" size={15} /> Use sample palms for both
                </button>
              </div>
            </section>
          </div>

          {/* ---------------------------------------------------------- start */}
          <div className="sticky bottom-[4.5rem] z-20 mt-8 md:bottom-4">
            <div className="card flex flex-wrap items-center gap-x-6 gap-y-3 border-ink/15 p-4 shadow-xl md:px-6">
              <p id="start-help" aria-live="polite" className={`flex min-w-0 flex-1 basis-56 items-center gap-2 text-sm ${canStart ? '' : tried ? 'text-danger' : 'text-muted'}`}>
                {busy && <Spinner size={14} />}
                {helper}
              </p>
              <button
                type="button"
                className="btn btn-primary !px-8 !py-4"
                aria-disabled={!canStart}
                data-explain={!canStart}
                aria-describedby="start-help"
                onClick={canStart ? () => void start() : explain}
              >
                Start reading <Icon name="arrow-right" size={17} />
              </button>
            </div>
          </div>
        </>
      )}

      <CreateProfileModal open={adding} onClose={() => setAdding(false)} />
    </div>
  )
}

function ProfilePicker({ profiles, active, onPick, onAdd }: { profiles: HandProfile[]; active: HandProfile; onPick: (id: string) => void; onAdd: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <Menu
        align="left"
        ariaLabel={`Reading for ${active.name}. Choose whose palms these are`}
        button={
          <span className="flex items-center gap-3 rounded-full border border-ink/20 bg-surface py-1.5 pl-1.5 pr-4 transition-colors hover:border-accent">
            <PlanetAvatar seed={active.id} size={40} />
            <span className="text-left">
              <span className="block text-xs leading-none text-muted">Reading for</span>
              <span className="mt-1 block font-medium leading-none">{active.name}</span>
            </span>
            <Icon name="chevron-down" size={15} className="text-muted" />
          </span>
        }
      >
        {(close) => (
          <>
            <ul>
              {profiles.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    aria-current={p.id === active.id}
                    onClick={() => {
                      onPick(p.id)
                      close()
                    }}
                    className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5"
                  >
                    <PlanetAvatar seed={p.id} size={34} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{p.name}</span>
                      <span className="block text-xs text-muted">{p.owner === 'self' ? 'My hands' : 'Shared with permission'}</span>
                    </span>
                    {p.id === active.id && <Icon name="check" size={16} className="text-accent-ink" />}
                  </button>
                </li>
              ))}
            </ul>
            <div className="mt-1 border-t border-ink/10 pt-1">
              <button
                type="button"
                onClick={() => {
                  close()
                  onAdd()
                }}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5"
              >
                <Icon name="plus" size={16} /> Add a profile
              </button>
            </div>
          </>
        )}
      </Menu>
      <p className="text-sm text-muted">
        {active.owner === 'self' ? 'These are your own palms.' : `${active.name} has agreed to these palms being uploaded.`}
      </p>
    </div>
  )
}

function NoProfile({ onAdd }: { onAdd: () => void }) {
  const { refresh } = useData()
  const [loading, setLoading] = useState(false)
  const demo = api.demo
  return (
    <div className="card flex flex-col items-start gap-5 p-8 md:flex-row md:items-center md:justify-between">
      <div className="max-w-xl">
        <h2 className="font-display text-2xl font-normal">First, whose palms are these?</h2>
        <p className="mt-2 text-muted">A reading belongs to a hand profile: yours, or someone who has said yes. It keeps their readings and chats apart from everyone else’s.</p>
      </div>
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={onAdd} className="btn btn-primary">
          <Icon name="plus" size={16} /> Create a profile
        </button>
        {demo && (
          <button
            type="button"
            disabled={loading}
            className="btn btn-ghost"
            onClick={async () => {
              setLoading(true)
              await demo.loadSamples()
              refresh()
              setLoading(false)
            }}
          >
            {loading && <Spinner />} Load sample profiles
          </button>
        )}
      </div>
    </div>
  )
}
