// Generated ambient music: no audio files, no licensing. A real track can replace this later.
//
// The music is ON by default. Browsers only let a page make sound after the visitor has done something on it (a click,
// a key press or a tap; scrolling and moving the mouse do not count), so it works like this:
//
//   1. at start-up we try to play straight away (some browsers allow it, e.g. when the visitor has been here before);
//   2. if the browser says no, the music is "waiting" and starts by itself on the very first click, key press or tap;
//   3. the visitor can switch it off at any time, and that choice is remembered on this device (localStorage).
//
// 'off' = muted by the visitor, 'waiting' = wanted but held back by the browser, 'playing' = audible.
export type SoundMode = 'off' | 'waiting' | 'playing'

const PAD = [130.81, 196.0, 261.63, 329.63, 392.0] // soft C chord
const CHIMES = [523.25, 587.33, 659.25, 783.99, 880.0, 1046.5] // pentatonic
const LEVEL = 0.5
const KEY = 'kiro-sound'
/**
 * Things a visitor does that a browser accepts as "the visitor wants this page to make sound". A click is enough for a
 * mouse, a finger and a keyboard on a button alike (a tap makes a click too). They are listened to as late as possible
 * (after the page's own handlers) so that pressing the sound button itself is handled by the button, not twice.
 */
const GESTURES = ['click', 'keydown'] as const

function savedChoice(): 'on' | 'off' | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'on' || v === 'off' ? v : null
  } catch {
    return null
  }
}

function saveChoice(v: 'on' | 'off') {
  try {
    localStorage.setItem(KEY, v)
  } catch {
    /* private browsing: the choice just won't be remembered */
  }
}

class Ambient {
  private ctx: AudioContext | null = null
  private master!: GainNode
  private bus!: BiquadFilterNode
  private timer = 0
  private sleepTimer = 0
  private listeners = new Set<() => void>()
  private mode: SoundMode = 'off'
  private begun = false
  private armed = false
  /** the tab is in the background and the music is held quiet until it comes back */
  private away = false

  subscribe = (fn: () => void) => {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }

  getSnapshot = (): SoundMode => this.mode

  private set(mode: SoundMode) {
    if (mode === this.mode) return
    this.mode = mode
    this.listeners.forEach((l) => l())
  }

  private build() {
    const ctx = new AudioContext()
    const master = ctx.createGain()
    master.gain.value = 0

    const bus = ctx.createBiquadFilter()
    bus.type = 'lowpass'
    bus.frequency.value = 1400

    // gentle echo for a dreamy tail
    const delay = ctx.createDelay(1.5)
    delay.delayTime.value = 0.45
    const feedback = ctx.createGain()
    feedback.gain.value = 0.38
    const wet = ctx.createGain()
    wet.gain.value = 0.5
    delay.connect(feedback)
    feedback.connect(delay)

    bus.connect(master)
    bus.connect(delay)
    delay.connect(wet)
    wet.connect(master)
    master.connect(ctx.destination)

    PAD.forEach((freq, i) => {
      const osc = ctx.createOscillator()
      osc.type = 'sine'
      osc.frequency.value = freq
      osc.detune.value = (i % 2 ? 1 : -1) * 4
      const g = ctx.createGain()
      g.gain.value = 0.06
      const lfo = ctx.createOscillator()
      lfo.frequency.value = 0.05 + i * 0.023
      const lfoGain = ctx.createGain()
      lfoGain.gain.value = 0.035
      lfo.connect(lfoGain)
      lfoGain.connect(g.gain)
      osc.connect(g)
      g.connect(bus)
      osc.start()
      lfo.start()
    })

    // the browser tells us when it lets the sound start (or takes it away again, e.g. a phone call on iOS)
    ctx.onstatechange = () => this.onContextState()

    this.ctx = ctx
    this.master = master
    this.bus = bus
  }

  /**
   * Called once when the app starts. Plays straight away unless the visitor switched the music off on an earlier
   * visit; if the browser holds the sound back, it starts on the first click, key press or tap instead.
   */
  begin() {
    if (this.begun) return
    this.begun = true
    document.addEventListener('visibilitychange', this.onVisibility)
    if (savedChoice() !== 'off') this.want()
  }

  /** The sound button. A click is exactly the kind of action a browser accepts, so this always works. */
  toggle() {
    if (this.mode === 'playing') this.mute()
    else {
      saveChoice('on')
      this.want()
    }
  }

  /** Can sound start right now? Only if the visitor has already done something on the page, or the browser says it allows it. */
  private canStartNow(): boolean {
    const nav = navigator as Navigator & {
      userActivation?: { hasBeenActive: boolean }
      getAutoplayPolicy?: (type: 'audiocontext') => string
    }
    if (nav.userActivation?.hasBeenActive) return true
    try {
      return nav.getAutoplayPolicy?.('audiocontext') === 'allowed' // Firefox and Safari can tell in advance (a site the visitor allowed)
    } catch {
      return false
    }
  }

  /**
   * The music is wanted: play now if the browser allows it, otherwise wait for the first click, key press or tap.
   * (Nothing is created while it is not allowed, so the browser has nothing to complain about.)
   */
  private want() {
    if (this.mode === 'off') this.set('waiting')
    if (this.canStartNow()) this.wake()
    if (!this.ctx || this.ctx.state !== 'running') this.arm()
  }

  /** Asks the browser to start (or restart) the sound. It only says yes after a click, key press or tap. */
  private wake() {
    if (this.away) return
    if (!this.ctx) this.build()
    // when it does say yes the promise resolves (and a state-change event fires too: both lead to the same place)
    this.ctx!.resume().then(() => this.onContextState(), () => undefined)
  }

  private mute() {
    saveChoice('off')
    this.disarm()
    window.clearTimeout(this.timer)
    this.timer = 0
    this.set('off')
    const ctx = this.ctx
    if (!ctx) return
    this.master.gain.setTargetAtTime(0, ctx.currentTime, 0.4)
    window.clearTimeout(this.sleepTimer)
    this.sleepTimer = window.setTimeout(() => {
      if (this.mode === 'off') void ctx.suspend()
    }, 2000)
  }

  private onContextState() {
    const ctx = this.ctx
    if (!ctx || this.mode === 'off') return
    if (ctx.state === 'running') {
      this.disarm()
      window.clearTimeout(this.sleepTimer)
      this.set('playing')
      this.master.gain.setTargetAtTime(this.away ? 0 : LEVEL, ctx.currentTime, 1.5)
      if (!this.timer) this.loop()
    } else if (!this.away) {
      // the browser has not (yet) let us make sound, or took it away: wait for the visitor
      window.clearTimeout(this.timer)
      this.timer = 0
      this.set('waiting')
      this.arm()
    }
  }

  private onGesture = (e: Event) => {
    if (e instanceof KeyboardEvent) {
      // Escape does not count as "the visitor wants sound" for a browser, so it is not worth trying on
      if (e.key === 'Escape') return
      // Enter or Space on a button, switch or link turns into a click a moment later, and that click will do it
      const interactive = 'button, a, [role="switch"], [role="button"], input, select, textarea, summary'
      if ((e.key === 'Enter' || e.key === ' ') && e.target instanceof Element && e.target.closest(interactive)) return
    }
    this.wake()
  }

  private arm() {
    if (this.armed) return
    this.armed = true
    for (const type of GESTURES) window.addEventListener(type, this.onGesture, { passive: true })
  }

  private disarm() {
    if (!this.armed) return
    this.armed = false
    for (const type of GESTURES) window.removeEventListener(type, this.onGesture)
  }

  /** A background tab should not keep playing: fade out and sleep, then wake when the visitor is back. */
  private onVisibility = () => {
    const ctx = this.ctx
    if (!ctx || this.mode === 'off') return
    window.clearTimeout(this.sleepTimer)
    if (document.hidden) {
      this.away = true
      this.master.gain.setTargetAtTime(0, ctx.currentTime, 0.25)
      this.sleepTimer = window.setTimeout(() => {
        if (this.away) void ctx.suspend()
      }, 900)
    } else {
      this.away = false
      this.master.gain.setTargetAtTime(this.mode === 'playing' ? LEVEL : 0, ctx.currentTime, 1.2)
      this.wake()
      if (ctx.state === 'running' && !this.timer && this.mode === 'playing') this.loop()
    }
  }

  private loop = () => {
    if (this.mode !== 'playing') return
    if (!this.away) this.chime(CHIMES[Math.floor(Math.random() * CHIMES.length)])
    this.timer = window.setTimeout(this.loop, 2500 + Math.random() * 4500)
  }

  chime(freq: number, volume = 0.07) {
    if (!this.ctx || this.mode !== 'playing') return
    const t = this.ctx.currentTime
    const osc = this.ctx.createOscillator()
    osc.type = 'triangle'
    osc.frequency.value = freq
    const g = this.ctx.createGain()
    g.gain.setValueAtTime(0, t)
    g.gain.linearRampToValueAtTime(volume, t + 0.02)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 3)
    osc.connect(g)
    g.connect(this.bus)
    osc.start(t)
    osc.stop(t + 3.2)
  }

  /** A soft rising rush of air: goes with the intro's flight through the stars. Silent unless the music is playing. */
  whoosh() {
    const ctx = this.ctx
    if (!ctx || this.mode !== 'playing') return
    const t = ctx.currentTime
    const length = Math.floor(ctx.sampleRate * 2.4)
    const noise = ctx.createBuffer(1, length, ctx.sampleRate)
    const data = noise.getChannelData(0)
    for (let i = 0; i < length; i++) data[i] = Math.random() * 2 - 1
    const source = ctx.createBufferSource()
    source.buffer = noise
    const band = ctx.createBiquadFilter()
    band.type = 'bandpass'
    band.Q.value = 0.8
    band.frequency.setValueAtTime(240, t)
    band.frequency.exponentialRampToValueAtTime(4800, t + 1.6)
    const air = ctx.createGain()
    air.gain.setValueAtTime(0.0001, t)
    air.gain.exponentialRampToValueAtTime(0.2, t + 1.2)
    air.gain.exponentialRampToValueAtTime(0.0001, t + 2.3)
    source.connect(band)
    band.connect(air)
    air.connect(this.master)
    source.start(t)
    source.stop(t + 2.4)

    // a clear tone climbing with it
    const tone = ctx.createOscillator()
    tone.type = 'sine'
    tone.frequency.setValueAtTime(261.63, t)
    tone.frequency.exponentialRampToValueAtTime(1046.5, t + 1.5)
    const toneGain = ctx.createGain()
    toneGain.gain.setValueAtTime(0.0001, t)
    toneGain.gain.exponentialRampToValueAtTime(0.06, t + 1.2)
    toneGain.gain.exponentialRampToValueAtTime(0.0001, t + 2.2)
    tone.connect(toneGain)
    toneGain.connect(this.bus)
    tone.start(t)
    tone.stop(t + 2.3)
  }

  /** Three bright notes as the landing page opens. Silent unless the music is playing. */
  arrive() {
    this.chime(523.25, 0.1)
    window.setTimeout(() => this.chime(783.99, 0.08), 140)
    window.setTimeout(() => this.chime(1046.5, 0.06), 290)
  }
}

export const ambient = new Ambient()
