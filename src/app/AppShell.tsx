import { useEffect } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { PROFILE_LOCKED_EVENT } from '../api/errors'
import { BRAND } from '../brand'
import Logo from '../components/Logo'
import SoundToggle from '../components/SoundToggle'
import ThemeToggle from '../components/ThemeToggle'
import Avatar from '../components/ui/Avatar'
import PlanetAvatar from '../components/ui/PlanetAvatar'
import Icon, { type IconName } from '../components/ui/icons'
import Menu from '../components/ui/Menu'
import { UNLOCK_NEEDED_EVENT, useData } from '../state/data'
import { useSession } from '../state/session'
import { useUi } from '../state/ui'
import { DISCLAIMER_SHORT } from './copy'
import GuestBanner from './GuestBanner'
import ImportOffer from './ImportOffer'
import { lang, t } from '../i18n'
import LanguagePicker from '../components/LanguagePicker'

type NavItem = { to: string; label: string; /** shorter, for the phone's bottom bar */ short: string; icon: IconName; end?: boolean; /** shown in the top bar only on extra-wide screens */ xlOnly?: boolean; /** shorter top-menu label for Sinhala/Tamil, where the full one is long */ menu?: string }

/** Takes the person to a profile's unlock screen when a locked profile is chosen, or when the open one locked itself again. */
function UnlockRouter() {
  const navigate = useNavigate()
  const location = useLocation()
  useEffect(() => {
    const go = (e: Event) => {
      const id = (e as CustomEvent<string | null>).detail
      if (!id || location.pathname.startsWith('/app/unlock/')) return
      // after unlocking, come back here, unless "here" belongs to another profile (a reading, a chat)
      const back = location.pathname.startsWith('/app/readings/') || location.pathname === '/app/chat' ? '/app' : `${location.pathname}${location.search}`
      navigate(`/app/unlock/${encodeURIComponent(id)}?next=${encodeURIComponent(back)}`)
    }
    window.addEventListener(UNLOCK_NEEDED_EVENT, go)
    window.addEventListener(PROFILE_LOCKED_EVENT, go)
    return () => {
      window.removeEventListener(UNLOCK_NEEDED_EVENT, go)
      window.removeEventListener(PROFILE_LOCKED_EVENT, go)
    }
  }, [navigate, location.pathname, location.search])
  return null
}

function ProfileSwitcher() {
  const { profiles, activeProfile, setActiveProfileId, leaveProfile } = useData()
  const navigate = useNavigate()
  const location = useLocation()
  // the chip shows which profile the app is inside; on the picker there is none yet
  if (!profiles || profiles.length === 0 || !activeProfile) return null
  const leave = async (close: () => void) => {
    close()
    if (await leaveProfile()) navigate('/app')
  }

  return (
    <Menu
      ariaLabel={t("Hand profile: {0}. Change profile", { "0": activeProfile?.name ?? 'none' })}
      button={
        <span className="flex h-10 items-center gap-1.5 rounded-full border border-ink/20 bg-surface/70 pl-1 pr-2.5 text-sm backdrop-blur transition-colors hover:border-accent">
          <PlanetAvatar seed={activeProfile?.id ?? '?'} size={32} />
          <span className="max-w-[5.5rem] truncate sm:max-w-28">{activeProfile?.name ?? t("Choose a profile")}</span>
          {activeProfile?.lock && <Icon name="shield" size={13} className="text-detected" />}
          <Icon name="chevron-down" size={14} className="text-muted" />
        </span>
      }
    >
      {(close) => (
        <>
          <p className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wider text-muted">{t("Hand profile")}</p>
          <ul>
            {profiles.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => {
                    setActiveProfileId(p.id)
                    close()
                    // a reading belongs to one profile, so leave it rather than show it under another name
                    if (p.id !== activeProfile?.id) {
                      if (location.pathname.startsWith('/app/readings/')) navigate('/app')
                      // the chat page drops its ?reading=… so it opens on this profile's newest reading
                      else if (location.pathname === '/app/chat') navigate('/app/chat')
                    }
                  }}
                  className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5"
                  aria-current={p.id === activeProfile?.id}
                >
                  <PlanetAvatar seed={p.id} size={34} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{p.name}</span>
                    <span className="block text-xs text-muted">{p.locked ? t("Locked: unlock with the palm") : p.owner === 'self' ? t("My hands") : t("Shared with permission")}</span>
                  </span>
                  {p.locked && <Icon name="shield" size={16} className="text-muted" />}
                  {p.id === activeProfile?.id && <Icon name="check" size={16} className="text-accent-ink" />}
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-1 border-t border-ink/10 pt-1">
            {activeProfile.lock && (
              <button type="button" onClick={() => leave(close)} className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5">
                <Icon name="shield" size={16} /> {t('Lock {name} now', { name: activeProfile.name })}
              </button>
            )}
            <button type="button" onClick={() => leave(close)} className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5">
              <Icon name="user" size={16} /> {t("All profiles")}
            </button>
          </div>
        </>
      )}
    </Menu>
  )
}

function AccountMenu() {
  const { session, signOut } = useSession()
  const navigate = useNavigate()
  const { activeProfile } = useData()
  if (!session) return null
  const guest = session.kind === 'guest'

  return (
    <Menu
      ariaLabel={t("Account menu")}
      button={<Avatar size={40} />}
    >
      {(close) => (
        <>
          <div className="px-3 pb-2 pt-2">
            <p className="text-sm font-medium">{guest ? t("Guest session") : session.user.displayName}</p>
            <p className="text-xs text-muted">{guest ? t("Temporary. Nothing is saved.") : session.user.email}</p>
          </div>
          <Link to="/app/settings" onClick={close} className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm hover:bg-ink/5">
            <Icon name="sliders" size={16} /> {t("Settings")}
          </Link>
          {activeProfile && (
            <Link to="/app/security" onClick={close} className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm hover:bg-ink/5">
              <Icon name="shield" size={16} /> {t('Security of {name}', { name: activeProfile.name })}
            </Link>
          )}
          <Link to="/app/palm-lab" onClick={close} className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm hover:bg-ink/5">
            <Icon name="hand" size={16} /> {t("Palm lab")}
          </Link>
          <button
            type="button"
            onClick={async () => {
              close()
              await signOut()
              navigate('/', { replace: true })
            }}
            className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5"
          >
            <Icon name="logout" size={16} /> {guest ? t("End guest session") : t("Sign out")}
          </button>
          {guest && <p className="px-3 pb-2 pt-1 text-xs text-muted">{t("Ending it deletes everything from this session.")}</p>}
        </>
      )}
    </Menu>
  )
}

export default function AppShell() {
  const { theme, toggleTheme } = useUi()
  const { session } = useSession()
  const location = useLocation()
  const guest = session?.kind === 'guest'

  const { activeProfile } = useData()
  const settings: NavItem = { to: '/app/settings', label: t("Settings"), short: t("Settings"), icon: 'sliders' }
  const security: NavItem = { to: '/app/security', label: t("Security"), short: t("Security"), icon: 'shield' }
  const lab: NavItem = { to: '/app/palm-lab', label: t("Palm lab"), short: t("Lab"), menu: t("Lab"), icon: 'hand' }
  // Inside a profile: that profile's pages. Before one is chosen: the profile picker and the account's own pages.
  const nav: NavItem[] = activeProfile
    ? [
        { to: '/app', label: t('Home'), short: t('Home'), icon: 'dashboard', end: true },
        { to: '/app/new', label: t("New reading"), short: t("New"), icon: 'plus' },
        { to: '/app/chat', label: t("Chat"), short: t("Chat"), icon: 'chat' },
        { to: '/app/history', label: guest ? t("This session") : t("History"), short: guest ? t("Session") : t("History"), icon: 'clock' },
        settings,
      ]
    : [{ to: '/app', label: t("Profiles"), short: t("Profiles"), icon: 'user', end: true }, lab, settings]
  // on wide screens the palm lock's two pages sit in the bar too (on phones they are in the account menu)
  const wide: NavItem[] = activeProfile ? [...nav.slice(0, 4), { ...security, xlOnly: true }, { ...lab, xlOnly: true }, settings] : nav

  return (
    <div className="app-bg flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-paper">
        {t("Skip to content")}
      </a>
      <header className="sticky top-0 z-40 border-b border-ink/10 bg-paper/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-3 px-5 md:px-8">
          {/* the logo leads back to the front page; the Dashboard link next to it leads home inside the app */}
          <Link to="/" aria-label={t("{name} home page", { name: BRAND.name })} title={t("Back to the front page")}>
            <Logo />
          </Link>
          <nav className="ml-3 hidden min-w-0 items-center gap-1 lg:flex" aria-label={t("App")}>
            {wide.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `${item.xlOnly ? 'hidden xl:inline-flex' : 'inline-flex'} items-center gap-2 whitespace-nowrap rounded-full ${lang === 'en' ? 'px-4' : 'px-3'} py-2 text-sm transition-colors ${isActive ? 'bg-ink text-paper' : 'text-ink/75 hover:bg-ink/5 hover:text-ink'}`
                }
              >
                {/* Sinhala and Tamil labels are longer, so the menu drops its icons there to stay on one line */}
                {lang === 'en' && <Icon name={item.icon} size={16} className="hidden 2xl:block" />}
                {lang === 'en' ? item.label : item.menu ?? item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ProfileSwitcher />
            <div className="hidden xl:block">
              <SoundToggle variant="inline" />
            </div>
            <LanguagePicker compact />
            <ThemeToggle theme={theme} onToggle={toggleTheme} compact />
            <AccountMenu />
          </div>
        </div>
      </header>
      <GuestBanner />
      <UnlockRouter />

      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-5 pb-28 pt-8 md:px-8 md:pt-12 lg:pb-16">
        <div key={location.pathname} className="page-in">
          <Outlet />
        </div>
      </main>

      <footer className="mx-auto hidden w-full max-w-7xl px-8 pb-24 text-xs text-muted md:block lg:pb-8">{DISCLAIMER_SHORT}</footer>

      <nav aria-label={t("App")} className="fixed inset-x-0 bottom-0 z-40 grid border-t border-ink/10 bg-paper/90 backdrop-blur-md lg:hidden" style={{ gridTemplateColumns: `repeat(${nav.length}, minmax(0, 1fr))` }}>
        {nav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `flex flex-col items-center gap-1 py-2.5 text-[11px] ${isActive ? 'font-medium text-accent-ink' : 'text-ink/70'}`}
          >
            <Icon name={item.icon} size={20} />
            <span className="sr-only">{item.label}</span>
            <span aria-hidden="true">{item.short}</span>
          </NavLink>
        ))}
      </nav>

      <ImportOffer />
    </div>
  )
}
