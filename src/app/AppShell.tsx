import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { BRAND } from '../brand'
import Logo from '../components/Logo'
import SoundToggle from '../components/SoundToggle'
import ThemeToggle from '../components/ThemeToggle'
import Avatar from '../components/ui/Avatar'
import PlanetAvatar from '../components/ui/PlanetAvatar'
import Icon, { type IconName } from '../components/ui/icons'
import Menu from '../components/ui/Menu'
import { useData } from '../state/data'
import { useSession } from '../state/session'
import { useUi } from '../state/ui'
import { DISCLAIMER_SHORT } from './copy'
import GuestBanner from './GuestBanner'
import ImportOffer from './ImportOffer'

type NavItem = { to: string; label: string; /** shorter, for the phone's bottom bar */ short: string; icon: IconName; end?: boolean }

function ProfileSwitcher() {
  const { profiles, activeProfile, setActiveProfileId } = useData()
  const navigate = useNavigate()
  const location = useLocation()
  if (!profiles || profiles.length === 0) return null

  return (
    <Menu
      ariaLabel={`Hand profile: ${activeProfile?.name ?? 'none'}. Change profile`}
      button={
        <span className="flex h-10 items-center gap-1.5 rounded-full border border-ink/20 bg-surface/70 pl-1 pr-2.5 text-sm backdrop-blur transition-colors hover:border-accent">
          <PlanetAvatar seed={activeProfile?.id ?? '?'} size={32} />
          <span className="max-w-[5.5rem] truncate sm:max-w-28">{activeProfile?.name}</span>
          <Icon name="chevron-down" size={14} className="text-muted" />
        </span>
      }
    >
      {(close) => (
        <>
          <p className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wider text-muted">Hand profile</p>
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
                    <span className="block text-xs text-muted">{p.owner === 'self' ? 'My hands' : 'Shared with permission'}</span>
                  </span>
                  {p.id === activeProfile?.id && <Icon name="check" size={16} className="text-accent-ink" />}
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-1 border-t border-ink/10 pt-1">
            <Link to="/app" onClick={close} className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm hover:bg-ink/5">
              <Icon name="user" size={16} /> Manage profiles
            </Link>
          </div>
        </>
      )}
    </Menu>
  )
}

function AccountMenu() {
  const { session, signOut } = useSession()
  const navigate = useNavigate()
  if (!session) return null
  const guest = session.kind === 'guest'

  return (
    <Menu
      ariaLabel="Account menu"
      button={<Avatar size={40} />}
    >
      {(close) => (
        <>
          <div className="px-3 pb-2 pt-2">
            <p className="text-sm font-medium">{guest ? 'Guest session' : session.user.displayName}</p>
            <p className="text-xs text-muted">{guest ? 'Temporary. Nothing is saved.' : session.user.email}</p>
          </div>
          <Link to="/app/settings" onClick={close} className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm hover:bg-ink/5">
            <Icon name="sliders" size={16} /> Settings
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
            <Icon name="logout" size={16} /> {guest ? 'End guest session' : 'Sign out'}
          </button>
          {guest && <p className="px-3 pb-2 pt-1 text-xs text-muted">Ending it deletes everything from this session.</p>}
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

  const nav: NavItem[] = [
    { to: '/app', label: 'Dashboard', short: 'Dashboard', icon: 'dashboard', end: true },
    { to: '/app/new', label: 'New reading', short: 'New', icon: 'plus' },
    { to: '/app/chat', label: 'Chat', short: 'Chat', icon: 'chat' },
    { to: '/app/history', label: guest ? 'This session' : 'History', short: guest ? 'Session' : 'History', icon: 'clock' },
    { to: '/app/settings', label: 'Settings', short: 'Settings', icon: 'sliders' },
  ]

  return (
    <div className="app-bg flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-paper">
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-ink/10 bg-paper/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-3 px-5 md:px-8">
          {/* the logo leads back to the front page; the Dashboard link next to it leads home inside the app */}
          <Link to="/" aria-label={`${BRAND.name} home page`} title="Back to the front page">
            <Logo />
          </Link>
          <nav className="ml-3 hidden items-center gap-1 lg:flex" aria-label="App">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => `inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm transition-colors ${isActive ? 'bg-ink text-paper' : 'text-ink/75 hover:bg-ink/5 hover:text-ink'}`}
              >
                <Icon name={item.icon} size={16} className="hidden xl:block" />
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ProfileSwitcher />
            <div className="hidden xl:block">
              <SoundToggle variant="inline" />
            </div>
            <ThemeToggle theme={theme} onToggle={toggleTheme} compact />
            <AccountMenu />
          </div>
        </div>
      </header>
      <GuestBanner />

      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-5 pb-28 pt-8 md:px-8 md:pt-12 lg:pb-16">
        <div key={location.pathname} className="page-in">
          <Outlet />
        </div>
      </main>

      <footer className="mx-auto hidden w-full max-w-7xl px-8 pb-24 text-xs text-muted md:block lg:pb-8">{DISCLAIMER_SHORT}</footer>

      <nav aria-label="App" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-ink/10 bg-paper/90 backdrop-blur-md lg:hidden">
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
