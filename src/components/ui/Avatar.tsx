import Icon from './icons'

/**
 * The ACCOUNT badge: an outlined ring with a person in it. Hand profiles are planets instead (PlanetAvatar), so the
 * two can never be mistaken for each other at a glance.
 */
export default function Avatar({ size = 40, className = '' }: { size?: number; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center rounded-full border border-ink/30 bg-ink/5 text-ink ${className}`}
      style={{ width: size, height: size }}
    >
      <Icon name="user" size={Math.round(size * 0.5)} />
    </span>
  )
}
