import { useState } from 'react'
import type { FeatureId, HandAnalysis, HandSide, Reading } from '../../api/types'
import AnalysisPanel from '../../components/palm/AnalysisPanel'
import { FeatureDetail, FeatureTable } from '../../components/palm/FeatureTable'
import StatusLegend from '../../components/palm/StatusLegend'
import Switch from '../../components/ui/Switch'
import { getPhotos } from '../../state/media'

// THE annotated analysis. Both hands side by side, each line drawn in a style that says how sure we were,
// a table of all ten findings, and a detail card for the line that is selected.

const SIDES: HandSide[] = ['left', 'right']

function Quality({ analysis }: { analysis: HandAnalysis }) {
  const q = analysis.quality
  return (
    <p className="mt-2 text-xs text-muted">
      Photo quality: focus {q.sharpness}, light {q.lighting}, size {q.resolution}
      {q.palmVisible ? '' : '. The palm was not clearly in view'}.
    </p>
  )
}

/** The shape of the hand and the creases that are none of the five lines, in words. Visual only. */
function ShapeAndCreases({ analysis }: { analysis: HandAnalysis }) {
  const s = analysis.palmShape
  const n = analysis.otherCreases.length
  return (
    <div className="mt-3 space-y-1.5 rounded-2xl bg-ink/5 p-4 text-sm">
      <p>
        <span className="font-medium">Hand shape.</span> {s.observation}
        {s.confidence !== null && <span className="text-muted"> Detection score {Math.round(s.confidence * 100)}%.</span>}
      </p>
      <p>
        <span className="font-medium">Other creases.</span>{' '}
        {n === 0 ? 'None found besides the five lines.' : `${n} found besides the five lines, drawn as thin dotted marks. They have no name, and nothing is said about what they mean.`}
      </p>
    </div>
  )
}

type Props = {
  reading: Reading
  selected: FeatureId | null
  onSelect: (id: FeatureId | null) => void
}

export default function LinesSection({ reading, selected, onSelect }: Props) {
  const photos = getPhotos(reading.id)
  const fits = !!photos?.aligned
  const [picture, setPicture] = useState<'photo' | 'sketch'>('photo')
  const [showLines, setShowLines] = useState(true)
  const [hover, setHover] = useState<FeatureId | null>(null)

  const active = hover ?? selected
  const toggle = (id: FeatureId) => onSelect(selected === id ? null : id)
  const usePhoto = fits && picture === 'photo'

  const note = usePhoto
    ? 'Your photo is shown from this tab’s memory only. It was never saved, and it disappears when you reload or close the tab.'
    : photos && !fits && reading.meta.mock
      ? 'Sample reading: a stand-in placed these lines, and it only fits the built-in sample photos, so they are drawn on a sketch of the hand instead of your photo.'
      : photos
        ? 'A sketch of the hand, redrawn from the saved outline.'
        : 'A sketch of the hand, redrawn from the saved outline. Photos are never stored, so the sketch is what remains.'

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="max-w-xl">
          <p className="kicker">The lines</p>
          <h2 className="mt-2 font-display text-2xl font-light tracking-tight sm:text-3xl md:text-4xl">What was found on each hand</h2>
          <p className="mt-2 text-sm text-muted sm:text-base">Select a numbered mark, on a hand or in the table, to look closer.</p>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <Switch checked={showLines} onChange={setShowLines} label="Show lines" />
          {fits && (
            <div role="group" aria-label="Picture under the lines" className="inline-flex rounded-full border border-ink/15 bg-surface/70 p-1 text-sm">
              {(['photo', 'sketch'] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  aria-pressed={picture === p}
                  onClick={() => setPicture(p)}
                  className={`rounded-full px-4 py-1.5 transition-colors ${picture === p ? 'bg-ink text-paper' : 'text-ink/75 hover:text-ink'}`}
                >
                  {p === 'photo' ? 'Your photo' : 'Sketch'}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="mt-6 grid gap-6 sm:grid-cols-2">
        {SIDES.map((side) => (
          <figure key={side}>
            <figcaption className="mb-3">
              <h3 className="font-display text-2xl font-normal">{side === 'left' ? 'Left palm' : 'Right palm'}</h3>
            </figcaption>
            <AnalysisPanel
              analysis={reading.hands[side]}
              photoUrl={usePhoto && photos ? photos[side] : null}
              showLines={showLines}
              active={active}
              selected={selected}
              onHover={setHover}
              onToggle={toggle}
              className="mx-auto max-w-md"
            />
            <Quality analysis={reading.hands[side]} />
            <ShapeAndCreases analysis={reading.hands[side]} />
          </figure>
        ))}
      </div>
      <StatusLegend className="mt-6" />
      <p className="mt-4 text-xs text-muted">{note}</p>

      <div className="mt-8 space-y-4">
        <FeatureTable hands={reading.hands} active={active} selected={selected} onHover={setHover} onToggle={toggle} />
        <FeatureDetail hands={reading.hands} id={selected} />
      </div>
    </div>
  )
}
