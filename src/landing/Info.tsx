import { useState } from 'react'
import { Link } from 'react-router-dom'
import { BRAND } from '../brand'
import { goTo } from './goTo'
import { FAQ, PRIVACY } from './content'

// The calm, solid-background part of the page below the 3D world: privacy, the disclaimer, the FAQ and the footer.

export function Privacy() {
  return (
    <section
      id="privacy"
      aria-labelledby="privacy-title"
      className="relative px-6 pb-[12svh] pt-[16svh] before:pointer-events-none before:absolute before:inset-x-0 before:-top-56 before:h-56 before:bg-gradient-to-b before:from-transparent before:to-paper/70 md:px-12 lg:px-20"
    >
      <div className="mx-auto max-w-[88rem]">
        <p className="reveal kicker">Privacy</p>
        <h2
          id="privacy-title"
          className="split-heading mt-4 max-w-3xl font-display text-[clamp(2.4rem,5.4vw,4.8rem)] font-light leading-[1] tracking-tight"
        >
          Your palms stay yours.
        </h2>
        <ul className="mt-14 grid gap-x-10 gap-y-12 md:grid-cols-2 lg:grid-cols-3">
          {PRIVACY.map((p, i) => (
            <li key={p.title} className="reveal border-t border-ink/15 pt-6">
              <p className="font-display text-lg italic text-accent-ink" aria-hidden="true">
                0{i + 1}
              </p>
              <h3 className="mt-2 font-display text-2xl font-light tracking-tight">{p.title}</h3>
              <p className="mt-3 text-muted">{p.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

export function Disclaimer() {
  return (
    <section id="disclaimer" aria-labelledby="disclaimer-title" className="relative px-6 py-[10svh] md:px-12 lg:px-20">
      <div className="reveal mx-auto max-w-[64rem] rounded-[2rem] border border-ink/12 bg-surface p-8 md:p-14">
        <p className="kicker">A note before you begin</p>
        <h2
          id="disclaimer-title"
          className="mt-4 font-display text-[clamp(2rem,4.2vw,3.6rem)] font-light leading-[1.04] tracking-tight"
        >
          Palmistry is an old art, not a science.
        </h2>
        <p className="mt-6 max-w-3xl text-base text-muted md:text-lg">
          Your reading speaks like a fortune teller, and a fortune is a story, not a promise. Palmistry is not a scientifically
          validated way to know your future, your health, your wealth or the people in your life, so take what you read as something
          to enjoy and to think about, never as fact, and never as medical, financial, employment or relationship advice. When a
          line is unclear or missing, we say so rather than guess.
        </p>
      </div>
    </section>
  )
}

export function Faq() {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <section id="faq" aria-labelledby="faq-title" className="relative px-6 py-[12svh] md:px-12 lg:px-20">
      <div className="mx-auto grid max-w-[88rem] gap-12 lg:grid-cols-[minmax(0,24rem)_1fr] lg:gap-24">
        <div>
          <p className="reveal kicker">FAQ</p>
          <h2
            id="faq-title"
            className="split-heading mt-4 font-display text-[clamp(2.4rem,5vw,4.4rem)] font-light leading-[1] tracking-tight"
          >
            Good questions.
          </h2>
        </div>
        <ul className="border-b border-ink/15">
          {FAQ.map((f, i) => {
            const isOpen = open === i
            return (
              <li key={f.q} className="border-t border-ink/15">
                <h3>
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    aria-controls={`faq-panel-${i}`}
                    id={`faq-button-${i}`}
                    onClick={() => setOpen(isOpen ? null : i)}
                    className="flex w-full items-center justify-between gap-6 py-6 text-left font-display text-xl font-light md:text-2xl"
                  >
                    {f.q}
                    <span
                      aria-hidden="true"
                      className={`grid h-9 w-9 shrink-0 place-items-center rounded-full border border-ink/20 text-lg transition-transform duration-300 ${
                        isOpen ? 'rotate-45' : ''
                      }`}
                    >
                      +
                    </span>
                  </button>
                </h3>
                <div
                  id={`faq-panel-${i}`}
                  role="region"
                  aria-labelledby={`faq-button-${i}`}
                  className={`grid transition-[grid-template-rows] duration-500 ease-out ${isOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
                >
                  <div className="overflow-hidden">
                    <p className="max-w-2xl pb-6 text-muted">{f.a}</p>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}

export function Footer() {
  return (
    <footer className="relative overflow-hidden bg-paper/80 px-6 pt-20 md:px-12 lg:px-20">
      <div className="mx-auto max-w-[88rem]">
        <div className="flex flex-col gap-10 md:flex-row md:items-end md:justify-between">
          <p className="max-w-sm font-display text-2xl font-light leading-snug">
            Your palms, read like a fortune teller reads them. A story, not a promise.
          </p>
          <nav aria-label="Footer" className="flex flex-wrap gap-x-8 gap-y-3 text-sm">
            <Link to="/start" className="underline-offset-4 hover:underline">
              Begin as a guest
            </Link>
            <Link to="/signin" className="underline-offset-4 hover:underline">
              Sign in
            </Link>
            <a href="#how" onClick={goTo('how')} className="underline-offset-4 hover:underline">
              How it works
            </a>
            <a href="#privacy" onClick={goTo('privacy')} className="underline-offset-4 hover:underline">
              Privacy
            </a>
            <a href="#faq" onClick={goTo('faq')} className="underline-offset-4 hover:underline">
              FAQ
            </a>
          </nav>
        </div>
        <p className="mt-10 max-w-3xl text-xs text-muted">
          Palmistry is an old art, not a scientifically validated method. A reading is a story about who you may become, never a
          promise, and never medical, financial or relationship advice.
        </p>
      </div>
      <div
        aria-hidden="true"
        className="-mb-[0.1em] mt-6 select-none text-center font-display text-[clamp(8rem,27vw,26rem)] font-light leading-[0.8] tracking-tighter text-ink/90"
      >
        {BRAND.short}
        <span className="text-accent-ink">.</span>
      </div>
    </footer>
  )
}
