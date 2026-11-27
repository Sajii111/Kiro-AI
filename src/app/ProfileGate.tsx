import { lazy } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import Spinner from '../components/ui/Spinner'
import { useData } from '../state/data'
import ProfilePicker from './ProfilePicker'

const Dashboard = lazy(() => import('./Dashboard'))

/** /app: the profile picker until a profile is chosen, then that profile's home. */
export default function ProfileGate() {
  const { profiles, activeProfile } = useData()
  if (profiles === null) {
    return (
      <p className="flex items-center gap-2 text-muted">
        <Spinner /> Loading your profiles…
      </p>
    )
  }
  return activeProfile ? <Dashboard /> : <ProfilePicker />
}

/** The pages that belong inside one profile (new reading, chat, history, a reading): without an open profile, choose one first. */
export function RequireProfile({ children }: { children: React.ReactNode }) {
  const { profiles, activeProfile } = useData()
  const location = useLocation()
  if (profiles === null) {
    return (
      <p className="flex items-center gap-2 text-muted">
        <Spinner /> Loading…
      </p>
    )
  }
  if (!activeProfile) return <Navigate to="/app" replace state={{ from: location.pathname }} />
  return <>{children}</>
}
