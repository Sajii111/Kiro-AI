import { Link } from 'react-router-dom'

/** A friendly dead end inside the app. */
export default function NotFound({ title = 'We could not find that', note = 'It may have been deleted, or the link may be wrong.' }: { title?: string; note?: string }) {
  return (
    <div className="mx-auto max-w-lg py-16 text-center">
      <p className="kicker">Not found</p>
      <h1 className="mt-4 font-display text-4xl font-light tracking-tight">{title}</h1>
      <p className="mt-4 text-muted">{note}</p>
      <Link to="/app" className="btn btn-ghost mt-8">
        Back to your readings
      </Link>
    </div>
  )
}
