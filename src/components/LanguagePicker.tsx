import { lang, LANGUAGES, setLanguage, t } from '../i18n'
import Icon from './ui/icons'
import Menu from './ui/Menu'

/**
 * The language switch in the headers: English, Sinhala or Tamil. Choosing one reloads the page in that language, and
 * new readings and chat answers are written in it too.
 */
export default function LanguagePicker({ compact = false }: { compact?: boolean }) {
  const current = LANGUAGES.find((l) => l.code === lang) ?? LANGUAGES[0]
  return (
    <Menu
      ariaLabel={t('Language: {name}. Change language', { name: current.native })}
      panelClassName="!min-w-48"
      button={
        <span
          className={`inline-flex h-10 items-center gap-2 rounded-full border border-ink/20 bg-surface/70 text-sm backdrop-blur transition-colors hover:border-accent ${compact ? 'px-3' : 'px-4'}`}
        >
          <Icon name="globe" size={18} />
          <span className={compact ? 'hidden sm:inline' : ''}>{compact ? current.short : current.native}</span>
        </span>
      }
    >
      {(close) => (
        <div role="group" aria-label={t('Language')}>
          <p className="px-3 pb-1 pt-2 text-xs text-muted">{t('Language')}</p>
          {LANGUAGES.map((l) => (
            <button
              key={l.code}
              type="button"
              lang={l.code}
              aria-current={l.code === lang ? 'true' : undefined}
              onClick={() => {
                close()
                setLanguage(l.code)
              }}
              className={`flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left text-sm hover:bg-ink/5 ${l.code === lang ? 'font-medium text-accent-ink' : ''}`}
            >
              <span>{l.native}</span>
              {l.code === lang ? <Icon name="check" size={16} /> : <span className="text-xs text-muted">{l.name}</span>}
            </button>
          ))}
        </div>
      )}
    </Menu>
  )
}
