/**
 * The little mark shown while pages change: a star with three tiny stars circling it. Only the stars move (no ring is
 * drawn), so it stays light and fits the night sky. See .veil-mark in index.css.
 */
export default function TransitionMark({ size = 56, className = '' }: { size?: number; className?: string }) {
  return (
    <span aria-hidden="true" className={`veil-mark ${className}`} style={{ width: size, height: size }}>
      <svg className="veil-star" viewBox="0 0 24 24">
        <path d="M12 0l2.6 9.4L24 12l-9.4 2.6L12 24l-2.6-9.4L0 12l9.4-2.6z" fill="currentColor" />
      </svg>
      <span className="veil-orbit veil-orbit-a">
        <i />
      </span>
      <span className="veil-orbit veil-orbit-b">
        <i />
      </span>
      <span className="veil-orbit veil-orbit-c">
        <i />
      </span>
    </span>
  )
}
