import { Link } from 'react-router-dom'
import { BRAND } from '../brand'
import Logo from '../components/Logo'
import ThemeToggle from '../components/ThemeToggle'
import Icon from '../components/ui/icons'
import { useSession } from '../state/session'
import { useUi } from '../state/ui'
import { goTo } from './goTo'
import { t } from '../i18n'
import LanguagePicker from '../components/LanguagePicker'

export default function LandingHeader({ inert }: { inert: boolean }) {
  const { theme, toggleTheme } = useUi()
  const { status, session } = useSession()
  return (
    <header
      inert={inert}
      className="header-band fixed inset-x-0 top-0 z-40 flex items-center justify-between px-5 py-4 md:px-10 md:py-5"
    >
      <Link to="/" aria-label={t('{name} home page', { name: BRAND.name })}>
        <Logo />
      </Link>
      <nav className="hidden items-center gap-8 text-sm md:flex" aria-label={t("Page sections")}>
        <a href="#how" onClick={goTo('how')} className="text-ink/85 underline-offset-4 transition-colors hover:text-ink hover:underline">{t("How it works")}</a>
        <a href="#privacy" onClick={goTo('privacy')} className="text-ink/85 underline-offset-4 transition-colors hover:text-ink hover:underline">{t("Privacy")}</a>
        <a href="#faq" onClick={goTo('faq')} className="text-ink/85 underline-offset-4 transition-colors hover:text-ink hover:underline">{t("FAQ")}</a>
      </nav>
      <div className="flex items-center gap-2 md:gap-3">
        {status === 'ready' && session ? (
          // already inside (signed in or a guest): the way back to the app is one click away
          <Link to="/app" className="btn btn-primary !px-4 !py-2.5 text-sm">
            <Icon name="dashboard" size={16} /> {t("Dashboard")}
          </Link>
        ) : (
          <Link to="/signin" className="btn btn-ghost !px-4 !py-2.5 text-sm">
            {t("Sign in")}
          </Link>
        )}
        <LanguagePicker compact />
        <ThemeToggle theme={theme} onToggle={toggleTheme} />
      </div>
    </header>
  )
}
