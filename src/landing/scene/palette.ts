import { useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// The scene reads its colours from the same CSS variables as the page, so a theme switch
// re-colours the 3D world too. The colour objects below are shared with the shaders and are
// eased towards their targets every frame, which gives a soft cross-fade between themes.

const make = () => new THREE.Color()

export const palette = {
  paper: make(),
  ink: make(),
  muted: make(),
  accent: make(),
  accent2: make(),
  soft: make(),
  /** line colours that stay visible on both a light and a dark background */
  lineA: make(),
  lineB: make(),
  hot: make(),
  detected: make(),
  uncertain: make(),
  missing: make(),
  /** 0 = Golden Hour, 1 = Night Sky (eased) */
  dark: 0,
}

type ColourKey = Exclude<keyof typeof palette, 'dark'>
const COLOUR_KEYS = Object.keys(palette).filter((k) => k !== 'dark') as ColourKey[]
type Target = Record<ColourKey, THREE.Color> & { dark: number }

// Hex numbers are used as-is (no sRGB conversion) so on-screen colours match the CSS exactly.
const hex = (value: string) => new THREE.Color().setStyle(value.trim(), THREE.LinearSRGBColorSpace)

function readTarget(): Target {
  const root = document.documentElement
  const css = getComputedStyle(root)
  const v = (name: string) => css.getPropertyValue(name)
  const dark = root.dataset.theme === 'dark'
  const ink = hex(v('--ink'))
  const accent = hex(v('--accent'))
  const accent2 = hex(v('--accent2'))
  return {
    paper: hex(v('--paper')),
    ink,
    muted: hex(v('--muted')),
    accent,
    accent2,
    soft: hex(v('--soft')),
    // Light theme: deeper apricot and amber so the lines read on cream. Dark theme: brighter, glowing tones.
    lineA: dark ? accent.clone().lerp(ink, 0.25) : accent.clone().lerp(hex('#C8501E'), 0.45),
    lineB: dark ? accent2.clone().lerp(ink, 0.15) : accent2.clone().lerp(hex('#B07400'), 0.4),
    hot: dark ? accent2.clone().lerp(new THREE.Color(1, 1, 1), 0.3) : hex('#E8702A'),
    detected: hex(dark ? '#7EE0A4' : '#4E9A68'),
    uncertain: dark ? accent2.clone() : hex('#E3A008'),
    missing: hex(v('--muted')),
    dark: dark ? 1 : 0,
  }
}

let target = readTarget()
for (const k of COLOUR_KEYS) palette[k].copy(target[k])
palette.dark = target.dark

/** Mount once inside the Canvas. */
export function PaletteDriver() {
  useEffect(() => {
    const observer = new MutationObserver(() => {
      target = readTarget()
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    target = readTarget()
    return () => observer.disconnect()
  }, [])

  useFrame((_, dt) => {
    const k = 1 - Math.exp(-6 * Math.min(dt, 0.1))
    for (const key of COLOUR_KEYS) palette[key].lerp(target[key], k)
    palette.dark += (target.dark - palette.dark) * k
  })
  return null
}
