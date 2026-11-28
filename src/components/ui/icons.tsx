// A small set of line icons, all drawn the same way (24 px grid, round ends), so the app looks consistent.

const PATHS = {
  plus: 'M12 5v14M5 12h14',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3.6 9h16.8M3.6 15h16.8M12 3c2.4 2.5 3.6 5.5 3.6 9s-1.2 6.5-3.6 9c-2.4-2.5-3.6-5.5-3.6-9S9.6 5.5 12 3z',
  x: 'M6 6l12 12M18 6 6 18',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  pencil: 'M4 20l1-4L16 5a2.1 2.1 0 0 1 3 3L8 19l-4 1z',
  trash: 'M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12M10 11v5M14 11v5',
  'arrow-right': 'M5 12h14M13 6l6 6-6 6',
  'arrow-left': 'M19 12H5M11 6l-6 6 6 6',
  'chevron-down': 'M6 9l6 6 6-6',
  alert: 'M12 4l9 16H3L12 4zM12 10v4M12 17.2v.1',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8v.1',
  upload: 'M12 16V5M7 10l5-5 5 5M5 19h14',
  download: 'M12 4v11M7 11l5 5 5-5M5 20h14',
  chat: 'M5 6h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-7l-4 3v-3H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20a7.5 7.5 0 0 1 15 0',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  sliders: 'M4 8h8M16 8h4M4 16h2M10 16h10M12 8a2 2 0 1 0 4 0 2 2 0 1 0-4 0M6 16a2 2 0 1 0 4 0 2 2 0 1 0-4 0',
  logout: 'M10 5H6a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h4M15 8l4 4-4 4M19 12H9',
  shield: 'M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3z',
  spark: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z',
  swap: 'M7 7h11M15 4l3 3-3 3M17 17H6M9 14l-3 3 3 3',
  image: 'M4 6h16v12H4zM4 16l4.5-4.5L12 15l3-3 5 5',
  camera: 'M4 8h3.2l1.6-2.2h6.4L16.8 8H20v11H4zM12 16.8a3.6 3.6 0 1 0 0-7.2 3.6 3.6 0 0 0 0 7.2z',
  send: 'M5 12l14-7-5 14-2.5-5.5L5 12z',
  eye: 'M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12zM12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  // four panels: the dashboard
  dashboard: 'M4 4h7v9H4zM13 4h7v5h-7zM13 12h7v8h-7zM4 16h7v4H4z',
  moon: 'M20 14.2A8 8 0 0 1 9.8 4a8 8 0 1 0 10.2 10.2z',
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6',
  volume: 'M4 10v4h3.5L12 18V6L7.5 10H4zM15.5 9.2a4 4 0 0 1 0 5.6M18.3 6.6a8 8 0 0 1 0 10.8',
  'volume-off': 'M4 10v4h3.5L12 18V6L7.5 10H4zM16 9.5l5 5M21 9.5l-5 5',
  book: 'M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4zM5 17a3 3 0 0 1 3-3h11',
  // an open palm: four fingers and a thumb
  hand: 'M9.5 12.5V6.2a1.3 1.3 0 0 1 2.6 0V11M12.1 11V4.7a1.3 1.3 0 0 1 2.6 0V11M14.7 11V6.2a1.3 1.3 0 0 1 2.6 0V12M17.3 12V9.2a1.3 1.3 0 0 1 2.6 0v6.3c0 3.2-2.2 5.5-5.4 5.5h-2.2c-2 0-3.2-.8-4.4-2.3L5.3 14.8a1.5 1.5 0 0 1 2.2-2l2 2.2',
} as const

export type IconName = keyof typeof PATHS

export default function Icon({ name, size = 18, className = '' }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`shrink-0 ${className}`}
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
