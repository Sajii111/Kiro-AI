import { Component, useEffect, useRef, type ReactNode } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import CameraRig from './CameraRig'
import SceneTip from './SceneTip'
import { settleScene } from './pick'
import World from './World'
import { world } from './state'
import { setLoad } from '../../lib/loading'

/** Tells the intro gate the 3D scene has drawn its first frames (and keeps still frames fresh when motion is reduced). */
function SceneReady() {
  const invalidate = useThree((s) => s.invalidate)
  const get = useThree((s) => s.get)
  const frames = useRef(0)

  // development only: lets test scripts look inside the scene (window.__three())
  useEffect(() => {
    if (import.meta.env.DEV) Object.assign(window, { __three: get })
  }, [get])

  useFrame(() => {
    frames.current++
    if (frames.current === 2) setLoad('scene', 0.9)
    if (frames.current === 6) setLoad('scene', 1)
  })

  // With reduced motion the canvas only redraws when something changes
  useEffect(() => {
    if (!world.reduced) return
    const redraw = () => invalidate()
    window.addEventListener('scroll', redraw, { passive: true })
    window.addEventListener('resize', redraw)
    const observer = new MutationObserver(() => {
      invalidate()
      window.setTimeout(invalidate, 80)
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const timer = window.setInterval(invalidate, 400)
    return () => {
      window.removeEventListener('scroll', redraw)
      window.removeEventListener('resize', redraw)
      observer.disconnect()
      window.clearInterval(timer)
    }
  }, [invalidate])

  return null
}

/** If WebGL is unavailable the page still works: it just loses the 3D backdrop. */
class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch() {
    setLoad('scene', 1)
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}

export default function Scene({ paused }: { paused: boolean }) {
  const narrow = world.narrow
  // once the scene stops drawing, nothing that was waiting for its next frame (a label, a grab cursor) may stay behind
  useEffect(() => {
    if (paused) settleScene()
  }, [paused])
  return (
    <>
      <div className="scene-layer pointer-events-none fixed inset-0 z-0" aria-hidden="true">
        <SceneBoundary>
          <Canvas
            dpr={[1, narrow ? 1.25 : 1.75]}
            camera={{ fov: narrow ? 52 : 38, near: 0.1, far: 220, position: [0, 0.2, 8.6] }}
            gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
            frameloop={paused ? 'never' : world.reduced ? 'demand' : 'always'}
          >
            <CameraRig />
            <World narrow={narrow} />
            <SceneReady />
          </Canvas>
        </SceneBoundary>
      </div>
      <SceneTip />
    </>
  )
}
