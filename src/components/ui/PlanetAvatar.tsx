import { useId, useMemo } from 'react'
import { assignPlanets, preferredPlanet } from '../../lib/planets'
import { hashString } from '../../lib/rand'
import { useProfilesIfAny } from '../../state/data'

// A hand profile is drawn as its own little planet. The planet comes from the profile's id and no two profiles of an
// account share one (lib/planets.ts), so it is the same world everywhere (header, dashboard, chat) and each profile
// can be told apart at a glance.

type Look = { light: string; mid: string; dark: string; band: string; glow: string }

const LOOKS: Look[] = [
  { light: '#FFE2B0', mid: '#F0A35E', dark: '#9A4B2E', band: '#7A3320', glow: '#FFB677' }, // amber gas giant
  { light: '#E4DBFF', mid: '#9985F5', dark: '#463396', band: '#352676', glow: '#B8A6FF' }, // violet
  { light: '#C4F5EA', mid: '#45BDB0', dark: '#16626B', band: '#0F4A52', glow: '#7FE6D6' }, // teal ocean
  { light: '#FFD3DE', mid: '#EC7088', dark: '#82284A', band: '#641B38', glow: '#FF9DB4' }, // rose
  { light: '#D7E8FF', mid: '#6C98F2', dark: '#233F90', band: '#1A3174', glow: '#9BBBFF' }, // blue
  { light: '#FFF0B8', mid: '#E8BC47', dark: '#8F6014', band: '#6E480C', glow: '#FFD76B' }, // gold
]

type Props = { seed: string; size?: number; className?: string }

export default function PlanetAvatar({ seed, size = 40, className = '' }: Props) {
  const uid = useId().replace(/:/g, '')
  const profiles = useProfilesIfAny()
  const planet = useMemo(() => (profiles && assignPlanets(profiles).get(seed)) ?? preferredPlanet(seed), [profiles, seed])
  const look = LOOKS[planet % LOOKS.length]
  const extra = Math.floor(planet / LOOKS.length) // 0 plain with bands, 1 ringed, 2 with a moon
  const tilt = -14 - ((hashString(seed) >>> 9) % 4) * 6
  const ringed = extra === 1
  const r = ringed ? 12.5 : 15.5
  const ring = (
    <ellipse cx="24" cy="24" rx="21" ry="6.4" transform={`rotate(${tilt} 24 24)`} fill="none" stroke={look.light} strokeWidth="2.2" />
  )

  return (
    <svg aria-hidden="true" data-planet={planet} width={size} height={size} viewBox="0 0 48 48" className={`shrink-0 overflow-visible ${className}`}>
      <defs>
        <radialGradient id={`${uid}b`} cx="35%" cy="30%" r="78%">
          <stop offset="0" stopColor={look.light} />
          <stop offset="0.5" stopColor={look.mid} />
          <stop offset="1" stopColor={look.dark} />
        </radialGradient>
        <radialGradient id={`${uid}s`} cx="32%" cy="28%" r="85%">
          <stop offset="0.55" stopColor="#05061a" stopOpacity="0" />
          <stop offset="1" stopColor="#05061a" stopOpacity="0.5" />
        </radialGradient>
        <radialGradient id={`${uid}g`}>
          <stop offset="0.55" stopColor={look.glow} stopOpacity="0.32" />
          <stop offset="1" stopColor={look.glow} stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${uid}m`} cx="35%" cy="30%" r="80%">
          <stop offset="0" stopColor={look.light} />
          <stop offset="1" stopColor={look.mid} />
        </radialGradient>
        <clipPath id={`${uid}c`}>
          <circle cx="24" cy="24" r={r} />
        </clipPath>
      </defs>

      <circle cx="24" cy="24" r="23" fill={`url(#${uid}g)`} />
      {ringed && <g opacity="0.55">{ring}</g>}
      <circle cx="24" cy="24" r={r} fill={`url(#${uid}b)`} />
      <g clipPath={`url(#${uid}c)`} fill="none" stroke={look.band} strokeLinecap="round">
        <path d="M6 19.5q18-5 36 1.5" strokeWidth="2" opacity="0.28" />
        <path d="M6 25.5q18-4 36 1" strokeWidth="2.6" opacity="0.22" />
        <path d="M6 31q18-3 36 1.2" strokeWidth="1.6" opacity="0.3" />
      </g>
      <circle cx="24" cy="24" r={r} fill={`url(#${uid}s)`} />
      {ringed && (
        <g transform={`rotate(${tilt} 24 24)`}>
          <path d="M3 24a21 6.4 0 0 0 42 0" fill="none" stroke={look.light} strokeWidth="2.2" strokeLinecap="round" />
        </g>
      )}
      {extra === 2 && <circle cx="39.5" cy="10.5" r="3.6" fill={`url(#${uid}m)`} />}
      <ellipse cx="19" cy="18.5" rx="4.2" ry="2.4" transform="rotate(-30 19 18.5)" fill="#fff" opacity="0.32" />
    </svg>
  )
}
