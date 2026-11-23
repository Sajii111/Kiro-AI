import { useMemo, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useLeaving } from '../lib/veil'
import { useSession } from '../state/session'
import Splash from './Splash'

/** Only lets someone in once they are signed in or have started a guest session. */
export default function RequireSession({ children }: { children: ReactNode }) {
  const { status, session } = useSession()
  const location = useLocation()
  // a page on its way out (the address has already moved on) must not send the person anywhere: they just chose where to go
  const leaving = useLeaving()
  const from = location.pathname + location.search
  // one object per address, not a new one at every render: <Navigate> starts over whenever it changes, and a page that
  // is on its way out is rendered over and over while the page-change veil closes
  const state = useMemo(() => ({ from }), [from])
  if (status === 'loading') return <Splash />
  if (!session) return leaving ? null : <Navigate to="/signin" replace state={state} />
  return children
}
