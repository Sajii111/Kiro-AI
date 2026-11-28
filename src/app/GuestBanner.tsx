import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Icon from '../components/ui/icons'
import { formatCountdown } from '../lib/format'
import { useSession } from '../state/session'
import { t } from '../i18n'

/** Always visible in a guest session: it is temporary, nothing is saved, and it will end. */
export default function GuestBanner() {
  const { session } = useSession()
  const [now, setNow] = useState(() => Date.now())
  const isGuest = session?.kind === 'guest'

  useEffect(() => {
    if (!isGuest) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [isGuest])

  if (session?.kind !== 'guest') return null
  return (
    // opaque, because from tablet width up it stays in view under the top bar while the page scrolls beneath it;
    // a labelled region, so it is a landmark that screen-reader users can jump to
    <section aria-label={t("Guest session notice")} className="z-30 border-b border-ink/10 bg-[color-mix(in_srgb,var(--accent2)_25%,var(--paper))] text-xs sm:text-sm md:sticky md:top-16">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-x-4 gap-y-0.5 px-5 py-2 md:px-8">
        <p className="min-w-0 flex-1 basis-72">
          <Icon name="clock" size={15} className="-mt-0.5 mr-2 inline" />
          <strong className="font-medium">{t("Guest session.")}</strong>{' '}
          <span className="text-ink/80">{t('Nothing here is saved. It ends in {time}.', { time: formatCountdown(session.expiresAt - now) })}</span>
        </p>
        {/* the padding makes a finger-sized target; the negative margin keeps the banner as slim as before */}
        <Link to="/signin" state={{ mode: 'signup', from: '/app' }} className="-my-2 py-2 font-medium underline underline-offset-4 hover:text-accent-ink md:ml-auto">
          <span className="sm:hidden">{t("Create an account")}</span>
          <span className="hidden sm:inline">{t('Create an account to keep your readings')}</span>
        </Link>
      </div>
    </section>
  )
}
