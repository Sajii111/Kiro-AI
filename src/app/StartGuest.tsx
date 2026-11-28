import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useHoldVeil } from '../lib/veil'
import { useSession } from '../state/session'
import Splash from './Splash'
import { t } from '../i18n'

/** /start: begins a guest session straight away and goes to the new-reading screen. */
export default function StartGuest() {
  const { status, session, startGuest } = useSession()
  const navigate = useNavigate()
  // this page is only a stop on the way: the page-change veil stays closed until we have moved on, so nobody sees the stop
  useHoldVeil()

  useEffect(() => {
    if (status !== 'ready') return
    let live = true
    const go = async () => {
      if (!session) await startGuest()
      if (live) navigate('/app/new', { replace: true })
    }
    void go()
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  return <Splash label={t("Setting up your guest session…")} />
}
