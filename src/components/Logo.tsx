import { BRAND } from '../brand'

/** The wordmark: the short product name and a small star that breathes (see .logo-star in index.css). */
export default function Logo({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-start font-display text-2xl leading-none tracking-tight ${className}`}>
      {BRAND.short}
      <svg className="logo-star ml-[3px] mt-[1px]" width="11" height="11" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 0l2.6 9.4L24 12l-9.4 2.6L12 24l-2.6-9.4L0 12l9.4-2.6z" fill="currentColor" />
      </svg>
    </span>
  )
}
