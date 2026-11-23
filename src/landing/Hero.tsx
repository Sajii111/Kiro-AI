import { Link } from 'react-router-dom'
import { BRAND } from '../brand'
import Magnetic from '../components/Magnetic'
import { useSession } from '../state/session'
import { goTo } from './goTo'

/** A slowly turning ring of text with an arrow in the middle. */
function ScrollBadge() {
  return (
    <a
      href="#dive"
      onClick={goTo('dive')}
      aria-label="Scroll to discover"
      className="scroll-badge absolute bottom-7 right-6 grid h-24 w-24 place-items-center md:bottom-10 md:right-12 md:h-28 md:w-28"
    >
      <svg viewBox="0 0 120 120" className="spin-slow absolute inset-0" aria-hidden="true">
        <defs>
          <path id="badge-ring" d="M60 60m-45 0a45 45 0 1 1 90 0a45 45 0 1 1 -90 0" />
        </defs>
        <text className="fill-ink" fontSize="10" fontWeight="600" letterSpacing="2.4">
          <textPath href="#badge-ring" textLength="280" lengthAdjust="spacing">
            SCROLL TO DISCOVER ✦ SCROLL TO DISCOVER ✦
          </textPath>
        </text>
      </svg>
      <svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M11 4v13M5.5 12 11 17.5 16.5 12" />
      </svg>
    </a>
  )
}

export default function Hero() {
  const { status, session } = useSession()
  const inside = status === 'ready' && !!session
  return (
    <section
      id="hero"
      aria-labelledby="hero-title"
      className="relative flex min-h-[100svh] items-end px-6 pb-24 pt-28 md:items-center md:px-12 md:pb-16 lg:px-20"
    >
      <div className="mx-auto w-full max-w-[88rem]">
        <div className="hero-panel max-w-[54rem] max-md:rounded-3xl max-md:bg-paper/60 max-md:p-5 max-md:backdrop-blur-md">
          <p className="hero-kicker inline-flex items-center gap-2 rounded-full border border-ink/15 bg-surface/60 px-4 py-1.5 text-[0.66rem] font-semibold uppercase tracking-[0.14em] backdrop-blur md:text-[0.7rem] md:tracking-[0.16em]">
            <span className="h-1.5 w-1.5 rounded-full bg-accent-ink" aria-hidden="true" />
            Palm reading<span className="max-md:hidden"> · what your lines foretell</span>
          </p>

          <h1
            id="hero-title"
            className="hero-title mt-6 font-display text-[clamp(3rem,9.2vw,8.6rem)] font-light leading-[0.92] tracking-tight md:mt-8"
          >
            <span className="block">Your hands,</span>
            <span className="block italic text-accent-ink">read gently.</span>
          </h1>

          <p className="hero-sub mt-5 max-w-xl text-[0.95rem] leading-relaxed text-muted md:mt-8 md:text-xl">{BRAND.tagline}</p>

          <div className="hero-cta mt-6 flex flex-wrap items-center gap-3 md:mt-10">
            <Magnetic>
              <Link to={inside ? '/app' : '/app/new'} className="btn btn-primary !px-5 !py-3.5 text-[0.95rem] md:!px-7 md:!py-4 md:text-base">
                {inside ? 'Open your dashboard' : 'Begin as a guest'} <span aria-hidden="true">→</span>
              </Link>
            </Magnetic>
            <Magnetic>
              <Link to={inside ? '/app/new' : '/signin'} className="btn btn-ghost !px-5 !py-3.5 text-[0.95rem] md:!px-7 md:!py-4 md:text-base">
                {inside ? 'New reading' : 'Sign in'}
              </Link>
            </Magnetic>
          </div>

          <p className="hero-fine mt-4 text-[0.8rem] text-muted md:mt-5 md:text-sm">No account needed · Photos are not kept</p>
        </div>
      </div>

      <ScrollBadge />
    </section>
  )
}
