import { useEffect, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { shared } from './materials'
import { world } from './state'

// Pointer plumbing for the 3D scene.
//
// The canvas sits *behind* the page and ignores the pointer, so the scene hears about the mouse (and taps)
// from the window instead, and first asks "is this open sky?". Text, buttons, cards and the header always win
// over a planet drifting behind them, so nothing in the scene can ever get in the way of the page.
//
// Objects (the planet, the zodiac wheel) read `pick` in their own frame loop and ask for things back:
//  - setTip()      a few words that follow the pointer while it is over them (clearTip() when it leaves)
//  - pick.wantGrab "I can be dragged": the next mouse press is then kept for the scene instead of selecting text

/** Anything matching this sits in front of the sky and keeps the pointer for itself. */
const BLOCKERS = 'a,button,input,textarea,select,summary,label,header,footer,nav,[data-ui],p,h1,h2,h3,h4,h5,h6,li,img,figure'

export const pick = {
  /** pointer position in client px, and the same as -1..1 (y up); only meaningful while `inside` */
  x: 0,
  y: 0,
  nx: 9,
  ny: 9,
  inside: false,
  /** a finger, not a mouse: no hovering, taps only */
  touch: false,
  /** the pointer is over open sky (checked a few times a second, and exactly on every press) */
  open: false,
  down: false,
  downX: 0,
  downY: 0,
  downAt: 0,
  /** pixels moved while the button is held: gathered by the listeners, handed over once per frame as fdx / fdy */
  dx: 0,
  dy: 0,
  fdx: 0,
  fdy: 0,
  /** a quick press-and-release on open sky (client px); `tapNow` is this frame's copy */
  tap: null as { x: number; y: number } | null,
  tapNow: null as { x: number; y: number } | null,
  /** something in the scene has answered this frame's tap (the planet, a zodiac sign, a palm line): nothing else should */
  tapUsed: false,
  /** who asked to be dragged last frame / this frame, and who got the press ('' = nobody) */
  grab: '',
  wantGrab: '',
  dragging: '',
}

/** Registered by <SceneTip />. */
export const tipEl = { current: null as HTMLElement | null }

// The small label that follows the pointer ("Drag to spin"). Whatever is under the pointer sets it with setTip()
// each frame it applies, and clears it with clearTip(); the label is placed straight from the pointer events.
const tip = { owner: '', text: '', visible: false, width: 0 }

function placeTip() {
  const el = tipEl.current
  if (!el || !tip.visible) return
  const flip = pick.x + 22 + tip.width > window.innerWidth - 12
  const x = flip ? pick.x - 20 - tip.width : pick.x + 20
  el.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(pick.y + 18)}px, 0)`
}
function paintTip() {
  const el = tipEl.current
  if (el) el.style.opacity = tip.visible ? '1' : '0'
}
export function setTip(owner: string, text: string) {
  const el = tipEl.current
  if (!el || (tip.owner === owner && tip.text === text && tip.visible)) return
  tip.owner = owner
  if (tip.text !== text) {
    tip.text = text
    el.textContent = text
    tip.width = el.offsetWidth
  }
  tip.visible = true
  placeTip()
  paintTip()
}
export function clearTip(owner: string) {
  if (tip.owner !== owner || !tip.visible) return
  tip.visible = false
  paintTip()
}

/** The scene has stopped drawing (scrolled out of sight): drop whatever was waiting on its next frame. */
export function settleScene() {
  document.documentElement.classList.remove('scene-over', 'scene-grab')
  pick.dragging = ''
  pick.grab = ''
  pick.wantGrab = ''
  pick.tap = null
  pick.tapNow = null
  tip.visible = false
  paintTip()
  world.hit = ''
  shared.lamp.value.w = 0
}

function openAt(x: number, y: number): boolean {
  const el = document.elementFromPoint(x, y)
  return !!el && !el.closest(BLOCKERS)
}

/** A ray from the camera through the pointer (or through a given client position). */
const ray = new THREE.Raycaster()
const ndc = new THREE.Vector2()
export function rayAt(camera: THREE.Camera, clientX: number, clientY: number): THREE.Raycaster {
  ndc.set((clientX / window.innerWidth) * 2 - 1, -((clientY / window.innerHeight) * 2 - 1))
  camera.updateMatrixWorld()
  ray.setFromCamera(ndc, camera)
  return ray
}

/**
 * Mount once inside the Canvas. Listens to the window, keeps `pick` up to date, shows the tip,
 * and drives the "lamp" that makes every line in the scene glow a little near the cursor.
 * With reduced motion nothing here runs: the scene is a still picture.
 */
export function PickDriver() {
  const gl = useThree((s) => s.gl)

  useEffect(() => {
    // development only: lets test scripts look at the pointer state (window.__pick)
    if (import.meta.env.DEV) Object.assign(window, { __pick: pick })
    if (world.reduced) return
    const root = document.documentElement
    let captured = -1

    const set = (e: PointerEvent) => {
      pick.x = e.clientX
      pick.y = e.clientY
      pick.nx = (e.clientX / window.innerWidth) * 2 - 1
      pick.ny = -((e.clientY / window.innerHeight) * 2 - 1)
      pick.touch = e.pointerType === 'touch'
      pick.inside = true
    }
    const onMove = (e: PointerEvent) => {
      const px = pick.x
      const py = pick.y
      set(e)
      if (pick.down) {
        pick.dx += e.clientX - px
        pick.dy += e.clientY - py
      }
      placeTip()
    }
    const onDown = (e: PointerEvent) => {
      if (e.pointerType === 'mouse' && e.button !== 0) return
      set(e)
      pick.open = world.entered && openAt(e.clientX, e.clientY)
      pick.down = true
      pick.downX = e.clientX
      pick.downY = e.clientY
      pick.downAt = performance.now()
      pick.dx = 0
      pick.dy = 0
      // something draggable is under the mouse: the press belongs to the scene (no text selection, keeps working off-window)
      if (pick.grab && pick.open && !pick.touch) {
        pick.dragging = pick.grab
        root.classList.add('scene-grab')
        e.preventDefault()
        try {
          root.setPointerCapture(e.pointerId)
          captured = e.pointerId
        } catch {
          captured = -1
        }
      }
    }
    const release = (e: PointerEvent, cancelled: boolean) => {
      const quick = performance.now() - pick.downAt < 450 && Math.hypot(e.clientX - pick.downX, e.clientY - pick.downY) < 8
      if (pick.down && quick && !cancelled && world.entered && openAt(e.clientX, e.clientY)) pick.tap = { x: e.clientX, y: e.clientY }
      pick.down = false
      pick.dragging = ''
      root.classList.remove('scene-grab')
      if (captured >= 0) {
        try {
          root.releasePointerCapture(captured)
        } catch {
          /* already released */
        }
        captured = -1
      }
    }
    const onUp = (e: PointerEvent) => release(e, false)
    const onCancel = (e: PointerEvent) => release(e, true)
    const onLeave = () => {
      pick.inside = false
      pick.open = false
    }
    const onSelect = (e: Event) => {
      if (pick.dragging) e.preventDefault()
    }

    window.addEventListener('pointermove', onMove, { passive: true })
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('pointerup', onUp, { passive: true })
    window.addEventListener('pointercancel', onCancel, { passive: true })
    document.documentElement.addEventListener('mouseleave', onLeave)
    document.addEventListener('selectstart', onSelect)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      document.documentElement.removeEventListener('mouseleave', onLeave)
      document.removeEventListener('selectstart', onSelect)
      root.classList.remove('scene-grab', 'scene-over')
      pick.inside = false
      pick.open = false
      pick.down = false
      pick.dragging = ''
      pick.grab = ''
      pick.wantGrab = ''
      tip.visible = false
      paintTip()
      world.hit = ''
      shared.lamp.value.w = 0
    }
  }, [])

  // Runs before the objects each frame (negative priority), so what they ask for in frame N is applied in frame N+1.
  const lastCheck = useMemo(() => ({ t: 0 }), [])
  useFrame((_, dtRaw) => {
    if (world.reduced) return
    const dt = Math.min(dtRaw, 0.1)
    const now = performance.now()

    // hand this frame's movement and tap to the objects
    pick.fdx = pick.dx
    pick.fdy = pick.dy
    pick.dx = 0
    pick.dy = 0
    pick.tapNow = pick.tap
    pick.tap = null
    pick.tapUsed = false

    // is the pointer over open sky? (a hit-test, so only a few times a second while it is just hovering)
    if (pick.inside && now - lastCheck.t > 70) {
      lastCheck.t = now
      pick.open = world.entered && openAt(pick.x, pick.y)
    }

    // "draggable" requests from last frame
    pick.grab = pick.wantGrab
    pick.wantGrab = ''
    document.documentElement.classList.toggle('scene-over', !!pick.grab && !pick.dragging)

    // the label hides the moment the pointer leaves open sky or starts a drag (the object sets it again when it applies)
    if (tip.visible && (!pick.inside || !pick.open || pick.dragging)) {
      tip.visible = false
      paintTip()
    }

    // the lamp: lines glow where the mouse is (drawing-buffer pixels, origin at the bottom left like gl_FragCoord)
    const lamp = shared.lamp.value
    const want = pick.inside && pick.open && !pick.touch && !pick.dragging ? 1 : 0
    lamp.w += (want - lamp.w) * (1 - Math.exp(-7 * dt))
    const w = gl.domElement.width
    const h = gl.domElement.height
    lamp.x = (pick.x / window.innerWidth) * w
    lamp.y = (1 - pick.y / window.innerHeight) * h
    lamp.z = h * 0.2
  }, -1)

  return null
}
