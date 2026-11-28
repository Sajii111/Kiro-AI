import { originOf, type Origin } from '../lib/themeTransition'
import type { Theme } from '../lib/theme'
import Icon from './ui/icons'
import { t } from '../i18n'

type Props = { theme: Theme; onToggle: (origin?: Origin) => void; compact?: boolean }

/**
 * The dark / light switch. The sun and the moon turn into each other, and the page changes with a circle that grows
 * out of this button (see lib/themeTransition.ts).
 */
export default function ThemeToggle({ theme, onToggle, compact = false }: Props) {
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={(e) => onToggle(originOf(e.currentTarget))}
      aria-label={t("Switch to {0} theme", { "0": dark ? 'light' : 'dark' })}
      title={dark ? t("Golden hour theme") : t("Night sky theme")}
      className={`theme-toggle inline-flex items-center gap-2 rounded-full border border-ink/20 bg-surface/70 text-sm backdrop-blur transition-colors hover:border-accent ${compact ? 'h-10 w-10 justify-center' : 'h-10 w-10 justify-center sm:w-auto sm:px-4'}`}
    >
      <span className="relative grid h-[18px] w-[18px] place-items-center" aria-hidden="true">
        <Icon name="sun" size={18} className={`absolute transition-all duration-500 ${dark ? 'rotate-0 scale-100 opacity-100' : 'rotate-90 scale-50 opacity-0'}`} />
        <Icon name="moon" size={18} className={`absolute transition-all duration-500 ${dark ? '-rotate-90 scale-50 opacity-0' : 'rotate-0 scale-100 opacity-100'}`} />
      </span>
      {/* on a phone the header is full (sign-in, language, theme): the sun or moon alone says it */}
      {!compact && <span className="hidden sm:inline">{dark ? t("Golden hour") : t("Night sky")}</span>}
    </button>
  )
}
