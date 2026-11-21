import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import Magnetic from '../components/Magnetic'
import { useSession } from '../state/session'
import { LINES } from './content'

// The sections that sit over the 3D world. Everything here is deliberately text-light: the camera
// is the star, and each block only has to say one thing next to the object it belongs to.

/**
 * Text that sits over the moving 3D scene lives on a frosted card, so a bright object drifting past can never swallow it.
 * On phones the object sits in the top half and the text drops to the bottom, inside the same card.
 */
const FROST = 'rounded-3xl border border-ink/10 bg-paper/70 p-6 backdrop-blur-md md:p-10'

function ChapterText({ n, id, title, children }: { n: string; id: string; title: string; children: ReactNode }) {
  return (
    <div data-ui className={`max-w-xl ${FROST}`}>
      <p className="reveal font-display text-3xl italic text-accent-ink">{n}</p>
      <h2 id={id} className="split-heading mt-3 font-display text-[clamp(2.6rem,6vw,5.4rem)] font-light leading-[0.98] tracking-tight">
        {title}
      </h2>
      {children}
    </div>
  )
}

function Marquee() {
  return (
    <div data-ui className="overflow-hidden border-y border-ink/10 bg-paper/55 py-5 backdrop-blur-sm" aria-hidden="true">
      <div className="marquee flex w-max font-display text-[clamp(2rem,4.4vw,3.8rem)] font-light italic">
        {[0, 1].map((k) => (
          <div key={k} className="flex shrink-0 gap-10 pr-10">
            {LINES.map((l) => (
              <span key={l}>
                {l} <span className="text-accent-ink">✦</span>
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

/** The breath between the hero and chapter one: the camera passes through the palm here. */
export function Dive() {
  return (
    <section id="dive" aria-label="Scroll to continue" className="relative flex min-h-[88svh] flex-col justify-between py-[14svh]">
      <p className="reveal px-6 text-center font-display text-[clamp(2rem,4.4vw,3.6rem)] font-light italic">Come a little closer.</p>
      <Marquee />
    </section>
  )
}

export function ChapterOne() {
  return (
    <section
      id="ch1"
      aria-labelledby="ch1-title"
      className="relative flex min-h-[110svh] items-end px-6 pb-[10svh] md:items-center md:px-12 md:pb-0 lg:px-20"
    >
      <div className="mx-auto w-full max-w-[88rem]">
        <ChapterText n="01" id="ch1-title" title="Show us both palms.">
          <p className="reveal mt-6 text-base text-muted md:text-lg">
            Your left and right hands are read side by side, so bring one photo of each. Before anything else we check the light, the
            focus and the framing, and tell you plainly how to retake a photo that will not work.
          </p>
          <ul className="reveal mt-7 flex flex-wrap gap-2 text-sm" aria-label="What to bring">
            {['JPG or PNG', 'One photo per hand', 'Swap either one any time'].map((t) => (
              <li key={t} className="rounded-full border border-ink/15 bg-surface/60 px-4 py-2 backdrop-blur">
                {t}
              </li>
            ))}
          </ul>
        </ChapterText>
      </div>
    </section>
  )
}

export function ChapterThree() {
  return (
    <section
      id="ch3"
      aria-labelledby="ch3-title"
      className="relative flex min-h-[100svh] items-end px-6 pb-[10svh] md:items-center md:px-12 md:pb-0 lg:px-20"
    >
      <div className="mx-auto w-full max-w-[88rem]">
        <ChapterText n="03" id="ch3-title" title="Ask anything.">
          <p className="reveal mt-6 text-base text-muted md:text-lg">
            Your reading opens a chat that knows your reading: which lines were found, which were not, and what each hand showed. It
            stays with one person and one reading at a time, so nothing leaks between profiles.
          </p>
          <ul className="reveal mt-7 flex flex-wrap gap-2 text-sm" aria-label="Example questions">
            {['Explain my heart line', 'How do my hands differ?', 'Which line was unclear?'].map((q) => (
              <li key={q} className="rounded-full border border-ink/15 bg-surface/60 px-4 py-2 italic backdrop-blur">
                “{q}”
              </li>
            ))}
          </ul>
          <p className="reveal mt-6 text-sm text-muted">
            Always traditional, always for reflection. Never medical, financial or relationship advice.
          </p>
        </ChapterText>
      </div>
    </section>
  )
}

export function FinalCta() {
  const { status, session } = useSession()
  const inside = status === 'ready' && !!session
  return (
    <section id="cta" aria-labelledby="cta-title" className="relative grid min-h-[100svh] place-items-center px-6 pt-[24svh] text-center">
      <div data-ui className={`max-w-3xl ${FROST}`}>
        <p className="reveal kicker">Ready when you are</p>
        <h2
          id="cta-title"
          className="split-heading mt-5 font-display text-[clamp(2.8rem,7.4vw,6.6rem)] font-light leading-[0.96] tracking-tight"
        >
          Let’s meet your hands.
        </h2>
        <div className="reveal mt-10 flex flex-wrap items-center justify-center gap-3">
          <Magnetic>
            <Link to={inside ? '/app' : '/app/new'} className="btn btn-primary !px-8 !py-4 text-base">
              {inside ? 'Open your dashboard' : 'Begin as a guest'} <span aria-hidden="true">→</span>
            </Link>
          </Magnetic>
          <Magnetic>
            <Link to={inside ? '/app/new' : '/signin'} className="btn btn-ghost !px-8 !py-4 text-base">
              {inside ? 'Start a new reading' : 'Sign in or create an account'}
            </Link>
          </Magnetic>
        </div>
        <p className="reveal mx-auto mt-6 max-w-md text-sm text-muted">
          Guest readings are temporary. Create an account to keep profiles, readings and chats, and delete them whenever you like.
        </p>
      </div>
    </section>
  )
}
