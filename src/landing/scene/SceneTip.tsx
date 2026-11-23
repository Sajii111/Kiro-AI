import { useEffect, useRef } from 'react'
import { tipEl } from './pick'

/** The little label that rides next to the pointer while it is over something in the 3D scene ("Drag to spin"). */
export default function SceneTip() {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    tipEl.current = ref.current
    return () => {
      tipEl.current = null
    }
  }, [])
  return <div ref={ref} className="scene-tip" aria-hidden="true" />
}
