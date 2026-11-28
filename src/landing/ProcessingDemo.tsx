import { useEffect, useRef, useState } from 'react'
import CanvasView from '../components/CanvasView'
import CompareSlider from '../components/CompareSlider'
import { drawDemoPalm } from '../lib/demoPalm'
import { runPipeline, type PipelineStages } from '../lib/stageFilters'
import { STAGES, type Stage } from './content'
import { t } from '../i18n'

/**
 * A hands-on version of the processing stage. A sample palm is drawn in the browser and run through the
 * same six classic steps the server uses, so a visitor can drag between the original and each result.
 * It is an illustration (no real person's hand, and the real pipeline is OpenCV on the backend).
 */
export default function ProcessingDemo() {
  const root = useRef<HTMLElement>(null)
  const [stages, setStages] = useState<PipelineStages | null>(null)
  const [active, setActive] = useState<Stage['key']>('gray')

  // The filters take a moment, so wait until the section is close to the screen before running them.
  useEffect(() => {
    const el = root.current
    if (!el) return
    let cancelled = false
    let timer = 0
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return
        io.disconnect()
        timer = window.setTimeout(() => {
          if (!cancelled) setStages(runPipeline(drawDemoPalm()))
        }, 60)
      },
      { rootMargin: '800px 0px' },
    )
    io.observe(el)
    return () => {
      cancelled = true
      io.disconnect()
      window.clearTimeout(timer)
    }
  }, [])

  const stage = STAGES.find((s) => s.key === active) ?? STAGES[0]

  return (
    <section id="demo" ref={root} aria-labelledby="demo-title" className="relative px-6 py-[14svh] md:px-12 lg:px-20">
      <div className="mx-auto max-w-[88rem]">
        <div data-ui className="rounded-[2rem] border border-ink/10 bg-surface/75 p-6 backdrop-blur-xl md:p-12">
          <div className="grid gap-10 md:grid-cols-[minmax(0,26rem)_1fr] md:gap-16">
            <div>
              {stages ? (
                <CompareSlider
                  aspect="441 / 560"
                  beforeLabel={t("Original")}
                  afterLabel={stage.label}
                  before={<CanvasView source={stages.original} />}
                  after={<CanvasView source={stages[active]} />}
                />
              ) : (
                <div className="w-full animate-pulse rounded-2xl bg-ink/5" style={{ aspectRatio: '441 / 560' }} role="status">
                  <span className="sr-only">{t("Preparing the sample photo")}</span>
                </div>
              )}
              <p className="mt-3 text-xs text-muted">
                {t("A sample hand drawn in your browser to illustrate each step. The real processing runs in OpenCV on the server, on your own photos.")}
              </p>
            </div>

            <div className="flex flex-col justify-center">
              <p className="reveal kicker">{t("See the steps")}</p>
              <h2
                id="demo-title"
                className="split-heading mt-4 font-display text-[calc(clamp(2.2rem,4.6vw,4.2rem)*var(--display-scale,1))] font-light leading-[1] tracking-tight"
              >
                {t("Watch a photo turn into evidence.")}
              </h2>
              <p className="reveal mt-5 max-w-lg text-base text-muted md:text-lg">
                {t("Drag the handle across the picture, then pick a step to see what it adds.")}
              </p>

              <div role="group" aria-label={t("Processing step")} className="reveal mt-8 flex flex-col gap-2">
                {STAGES.map((s, i) => {
                  const on = s.key === active
                  return (
                    <button
                      key={s.key}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setActive(s.key)}
                      className={`rounded-2xl border px-5 py-4 text-left transition-colors ${
                        on ? 'border-accent bg-accent/25' : 'border-ink/12 hover:border-ink/30'
                      }`}
                    >
                      <span className="flex items-baseline gap-3">
                        <span className="font-display text-lg italic text-accent-ink">0{i + 1}</span>
                        <span className="font-medium">{s.label}</span>
                      </span>
                      {on && <span className="mt-2 block max-w-lg text-sm text-muted">{s.body}</span>}
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
