import { useRef, useState } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useGSAP } from '@gsap/react'
import StatusDot from '../components/StatusDot'
import { STATUS_LABEL } from '../lib/status'
import { HOW_STEPS, type HowStep } from './content'
import { world } from './scene/state'

gsap.registerPlugin(ScrollTrigger, useGSAP)

// "How it works" is the section the camera orbits the scanning ring for. On a normal visit it is pinned
// to the screen for about five and a half screens of scrolling: the six steps swap as you scroll, and the
// scroll position (world.howProgress) also drives the 3D scene. With reduced motion it is a plain list.

function StepBody({ step }: { step: HowStep }) {
  return (
    <>
      <p className="font-display text-4xl italic text-accent-ink md:text-6xl" aria-hidden="true">
        {step.n}
      </p>
      <h3 className="mt-2 font-display text-[clamp(1.85rem,4.4vw,4rem)] font-light leading-[1.02] tracking-tight">{step.title}</h3>
      <p className="mt-4 max-w-md text-[0.95rem] leading-relaxed text-muted md:mt-5 md:text-lg">{step.body}</p>
      {step.chips && (
        <ul className="mt-5 flex flex-wrap gap-2 text-sm md:mt-6">
          {step.chips.map((c) => (
            <li key={c.label} className="inline-flex items-center gap-2 rounded-full border border-ink/15 bg-surface/70 px-3.5 py-1.5 backdrop-blur md:px-4 md:py-2">
              {c.status && <StatusDot status={c.status} />}
              {c.status ? STATUS_LABEL[c.status] : c.label}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function Pinned() {
  const root = useRef<HTMLElement>(null)
  const [active, setActive] = useState(0)

  useGSAP(
    () => {
      const steps = gsap.utils.toArray<HTMLElement>('.how-step')
      gsap.set(steps.slice(1), { opacity: 0, y: 36 })

      const tl = gsap.timeline({
        defaults: { ease: 'none' },
        scrollTrigger: {
          trigger: root.current,
          start: 'top top',
          end: () => `+=${window.innerHeight * 5.5}`,
          pin: true,
          scrub: 0.6,
          anticipatePin: 1,
          invalidateOnRefresh: true,
          onUpdate: (self) => {
            world.howProgress = self.progress
            const idx = Math.min(steps.length - 1, Math.floor(self.progress * steps.length))
            setActive((prev) => (prev === idx ? prev : idx))
          },
          onRefresh: (self) => {
            world.marks.howStart = self.start
            world.marks.howMid = (self.start + self.end) / 2
            world.marks.howEnd = self.end
          },
        },
      })

      // each step is visible for roughly half of its slot: fade in, hold, fade out
      steps.forEach((el, i) => {
        if (i > 0) tl.to(el, { opacity: 1, y: 0, duration: 0.22, ease: 'power2.out' }, i + 0.02)
        if (i < steps.length - 1) tl.to(el, { opacity: 0, y: -36, duration: 0.22, ease: 'power2.in' }, i + 0.76)
      })
      tl.set({}, {}, steps.length) // makes the timeline exactly one unit per step

      return () => {
        world.howProgress = 0
      }
    },
    { scope: root },
  )

  return (
    <section
      id="how"
      ref={root}
      aria-labelledby="how-title"
      className="relative h-[100svh] overflow-hidden px-6 pb-[9svh] md:px-12 md:pb-0 lg:px-20"
    >
      <div className="mx-auto flex h-full max-w-[88rem] items-end md:items-center">
        <div data-ui className="w-full md:w-[46%] lg:w-[40%] max-md:rounded-3xl max-md:bg-paper/75 max-md:p-6 max-md:backdrop-blur-md">
          <h2 id="how-title" className="kicker">
            How it works
          </h2>

          <div className="mt-5 grid">
            {HOW_STEPS.map((s) => (
              <div key={s.n} className="how-step col-start-1 row-start-1">
                <StepBody step={s} />
              </div>
            ))}
          </div>

          <ol className="mt-8 flex items-center gap-2" aria-label="Progress through the six steps">
            {HOW_STEPS.map((s, i) => (
              <li
                key={s.n}
                aria-current={i === active ? 'step' : undefined}
                className={`h-1 rounded-full transition-all duration-500 ${
                  i === active ? 'w-12 bg-ink' : i < active ? 'w-6 bg-ink/55' : 'w-6 bg-ink/15'
                }`}
              >
                <span className="sr-only">
                  Step {i + 1}: {s.title}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  )
}

function Plain() {
  return (
    <section id="how" aria-labelledby="how-title" className="relative px-6 py-[16svh] md:px-12 lg:px-20">
      <div className="mx-auto max-w-[88rem]">
        <h2 id="how-title" className="kicker">
          How it works
        </h2>
        <ol className="mt-10 space-y-[22svh]">
          {HOW_STEPS.map((s) => (
            <li key={s.n} className="max-w-xl">
              <StepBody step={s} />
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

export default function HowItWorks() {
  return world.reduced ? <Plain /> : <Pinned />
}
