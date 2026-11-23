import { Link } from 'react-router-dom'
import { BRAND } from '../brand'

/** A calm placeholder for screens that are still being built. */
export default function NotBuilt({ title, note }: { title: string; note: string }) {
  return (
    <main className="grid min-h-screen place-items-center px-6 text-center">
      <div>
        <p className="kicker">{BRAND.name}</p>
        <h1 className="mt-4 font-display text-5xl font-light tracking-tight md:text-7xl">{title}</h1>
        <p className="mx-auto mt-5 max-w-md text-muted">{note}</p>
        <Link to="/" className="btn btn-ghost mt-8">
          ← Back to the landing page
        </Link>
      </div>
    </main>
  )
}
