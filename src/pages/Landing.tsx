import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { SplitText } from 'gsap/SplitText'
import { useGSAP } from '@gsap/react'
import IntroGate from '../components/IntroGate'
import { lenis, useSmoothScroll } from '../lib/smoothScroll'
import { afterVeil } from '../lib/veil'
import { useUi } from '../state/ui'
import Hero from '../landing/Hero'
import HowItWorks from '../landing/HowItWorks'
import { Disclaimer, Faq, Footer, Privacy } from '../landing/Info'
import LandingHeader from '../landing/LandingHeader'
import ProcessingDemo from '../landing/ProcessingDemo'
import { unclip } from '../landing/reveal'
import { world } from '../landing/scene/state'
import { ChapterOne, ChapterThree, Dive, FinalCta } from '../landing/Sections'

gsap.registerPlugin(ScrollTrigger, SplitText, useGSAP)

// The 3D engine (three.js) is a big chunk, so it loads separately while the intro gate is showing.
const Scene = lazy(() => import('../landing/scene/Scene'))

const matches = (query: string) => window.matchMedia(query).matches

/**
 * Works out where each camera stop sits on the page (journey.ts names them) from the real layout.
 * The pinned "how it works" stops are recorded by HowItWorks itself.
 */
/** Tells the stylesheet how far down the window the end of the 3D world is (the scene fades out there). */
function placeSceneEnd() {
  const root = document.documentElement
  const end = Math.round(document.getElementById('world')?.getBoundingClientRect().bottom ?? window.innerHeight)
  root.style.setProperty('--scene-end', `${end}px`)
  root.classList.toggle('scene-fading', end < window.innerHeight + 240)
}

function measureMarks() {
  const vh = window.innerHeight
  const byId = (id: string) => document.getElementById(id)
  const top = (el: HTMLElement | null) => (el ? el.getBoundingClientRect().top + window.scrollY : 0)
  const height = (el: HTMLElement | null) => (el ? el.offsetHeight : 0)
  const centred = (id: string) => top(byId(id)) + height(byId(id)) / 2 - vh / 2

  const m = world.marks
  const hero = byId('hero')
  const dive = byId('dive')
  m.top = 0
  m.near = top(hero) + height(hero) * 0.55
  m.dive = top(dive) + height(dive) * 0.35
  m.ch1c = centred('ch1')
  m.ch3c = centred('ch3')
  m.ctac = centred('cta')

  if (world.reduced) {
    // not pinned: the camera simply follows the plain list
    const how = byId('how')
    m.howStart = top(how)
    m.howEnd = top(how) + height(how) - vh
    m.howMid = (m.howStart + m.howEnd) / 2
  }
  world.version++
  placeSceneEnd()
}

export default function Landing() {
  const { entered, enter } = useUi()
  const [gateGone, setGateGone] = useState(entered) // already inside in this tab: no gate
  const [revealed, setRevealed] = useState(entered) // the gate is lifting (or there is none): the headline may come in
  const [paused, setPaused] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const worldEl = useRef<HTMLDivElement>(null)
  // whether the intro film plays on this visit (decided once: the headline waits for it)
  const [withFilm] = useState(!entered)
  // the visitor pressed Skip: the headline then comes in sooner
  const skippedAhead = useRef(false)

  // read once, before the 3D scene renders for the first time
  const [narrow, setNarrow] = useState(() => {
    world.reduced = matches('(prefers-reduced-motion: reduce)')
    world.narrow = matches('(max-width: 767px)')
    world.entered = entered
    // The opening film is one camera move through the real 3D scene (landing/scene/film.ts). The scene waits in its first
    // shot (the hand as small as the loader's drawing) and the gate plays it. With no film (already inside in this tab, or
    // "reduce motion") the camera simply rests where the hero is.
    world.film.on = !entered && !world.reduced
    world.film.clock = 0
    world.film.load = entered || world.reduced ? 1 : 0
    return world.narrow
  })

  useSmoothScroll()

  // While the gate is up the page cannot scroll; when it is gone, layout is measured again.
  useEffect(() => {
    document.documentElement.style.overflow = gateGone ? '' : 'hidden'
    if (gateGone) lenis?.start()
    else lenis?.stop()
    if (!gateGone) return
    const id = requestAnimationFrame(() => ScrollTrigger.refresh())
    return () => cancelAnimationFrame(id)
  }, [gateGone])
  useEffect(
    () => () => {
      document.documentElement.style.overflow = ''
    },
    [],
  )

  // Feed the 3D scene: scroll position, pointer and screen size.
  useEffect(() => {
    const onScroll = () => {
      world.scrollY = window.scrollY
      placeSceneEnd()
    }
    const onPointer = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      world.pointer.x = (e.clientX / window.innerWidth) * 2 - 1
      world.pointer.y = -((e.clientY / window.innerHeight) * 2 - 1)
    }
    const phone = window.matchMedia('(max-width: 767px)')
    const onPhone = () => {
      world.narrow = phone.matches
      setNarrow(phone.matches)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll, { passive: true })
    window.addEventListener('pointermove', onPointer, { passive: true })
    phone.addEventListener('change', onPhone)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      window.removeEventListener('pointermove', onPointer)
      phone.removeEventListener('change', onPhone)
      document.documentElement.style.removeProperty('--scene-end')
      document.documentElement.classList.remove('scene-fading')
    }
  }, [])

  // Camera stops follow the real layout, and are re-measured whenever ScrollTrigger recalculates.
  useEffect(() => {
    // development only: lets test scripts read the camera stops (window.__world.marks)
    if (import.meta.env.DEV) Object.assign(window, { __world: world })
    ScrollTrigger.addEventListener('refresh', measureMarks)
    measureMarks()
    void document.fonts.ready.then(() => ScrollTrigger.refresh())
    return () => {
      ScrollTrigger.removeEventListener('refresh', measureMarks)
      Object.keys(world.marks).forEach((k) => delete world.marks[k])
      world.version++
    }
  }, [])

  // Pause 3D rendering once the world has scrolled out of sight (the privacy section onwards is solid).
  useGSAP(
    () => {
      ScrollTrigger.create({
        trigger: worldEl.current,
        start: 'top bottom',
        end: 'bottom top',
        onToggle: (self) => setPaused(!self.isActive),
      })
    },
    { scope: root },
  )

  // The hero introduces itself as the camera pulls back (or, with no film, as the page opens).
  useGSAP(
    () => {
      if (!revealed || world.reduced) return
      const split = SplitText.create('.hero-title', { type: 'words', mask: 'words' })
      unclip(split)
      // everything starts hidden and waits: for the film's reveal, and for the page-switch veil when arriving from another page
      const tl = gsap.timeline({ delay: withFilm ? (skippedAhead.current ? 0.3 : 0.9) : 0.1, paused: true })
      tl.from('.header-band', { opacity: 0, y: -18, duration: 0.9, ease: 'power3.out' })
        .from('.hero-panel', { opacity: 0, duration: 0.7, ease: 'power1.out' }, '<')
        .from('.hero-kicker', { opacity: 0, y: 14, duration: 0.8, ease: 'power3.out' }, '<0.1')
        .from(split.words, { yPercent: 115, duration: 1.2, ease: 'power4.out', stagger: 0.09 }, '<0.1')
        .from('.hero-sub, .hero-cta, .hero-fine', { opacity: 0, y: 22, duration: 0.9, stagger: 0.1, ease: 'power3.out' }, '-=0.7')
        .from('.scroll-badge', { opacity: 0, scale: 0.6, duration: 0.9, ease: 'back.out(1.6)' }, '-=0.6')
      const stop = afterVeil(() => tl.play())
      return () => {
        stop()
        split.revert()
      }
    },
    { scope: root, dependencies: [revealed] },
  )

  // Everything else slides into place once, as it is scrolled to.
  useGSAP(
    () => {
      if (world.reduced) return
      gsap.utils.toArray<HTMLElement>('.reveal').forEach((el) => {
        gsap.from(el, {
          opacity: 0,
          y: 48,
          duration: 1,
          ease: 'power3.out',
          scrollTrigger: { trigger: el, start: 'top 88%', once: true },
        })
      })
      gsap.utils.toArray<HTMLElement>('.split-heading').forEach((el) => {
        const split = SplitText.create(el, { type: 'words', mask: 'words' })
        unclip(split)
        gsap.from(split.words, {
          yPercent: 115,
          duration: 1.1,
          ease: 'power4.out',
          stagger: 0.06,
          scrollTrigger: { trigger: el, start: 'top 86%', once: true },
        })
      })
    },
    { scope: root },
  )

  // The film is nearly over: the page goes live (the header and headline come in) while the camera settles into the hero view.
  const reveal = ({ fast }: { fast: boolean }) => {
    skippedAhead.current = fast
    world.entered = true
    enter()
    setRevealed(true)
  }
  // The gate is gone and so is the film (it has ended on exactly the ordinary hero view, so nothing moves when it is switched off).
  const done = () => {
    world.film.on = false
    setGateGone(true)
  }

  return (
    <div ref={root} className={revealed ? undefined : 'intro-hold'}>
      {!gateGone && <IntroGate onReveal={reveal} onDone={done} />}

      <LandingHeader inert={!entered} />

      <Suspense fallback={null}>
        <Scene key={narrow ? 'narrow' : 'wide'} paused={paused} />
      </Suspense>

      <div inert={!entered}>
        <main id="main" className="relative z-10">
          <div ref={worldEl} id="world">
            <Hero />
            <Dive />
            <ChapterOne />
            <HowItWorks />
            <ProcessingDemo />
            <ChapterThree />
            <FinalCta />
          </div>
          <div data-ui className="relative bg-paper/70">
            <Privacy />
            <Disclaimer />
            <Faq />
          </div>
        </main>
        <div className="relative z-10">
          <Footer />
        </div>
      </div>
    </div>
  )
}
