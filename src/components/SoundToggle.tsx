import { useUi } from '../state/ui'
import Icon from './ui/icons'
import { t } from '../i18n'

/**
 * The ambient-sound button. "floating" sits in the corner of the landing page (moving bars while it plays);
 * "inline" fits into a header and is a plain speaker, so it can never be mistaken for a chart or a menu.
 *
 * The music is on by default. While the browser is holding it back (it waits for a first click, key press or tap) the
 * button shows the bars softly breathing, and pressing it starts the music at once.
 */
export default function SoundToggle({ variant = 'floating' }: { variant?: 'floating' | 'inline' }) {
  const { soundOn: on, soundWaiting: waiting, toggleSound } = useUi()
  const label = on ? t("Mute sound") : t("Play sound")
  const title = on ? t("Mute sound") : waiting ? t("The music starts with your first click or key press") : t("Play ambient sound")
  const state = on ? 'playing' : waiting ? 'waiting' : 'off'

  if (variant === 'inline') {
    return (
      <button
        type="button"
        onClick={toggleSound}
        aria-pressed={on}
        aria-label={label}
        title={title}
        data-sound={state}
        className="grid h-10 w-10 place-items-center rounded-full border border-ink/20 bg-surface/70 transition-colors hover:border-accent"
      >
        <Icon name={on ? 'volume' : 'volume-off'} size={19} className={waiting ? 'eq-wait' : ''} />
      </button>
    )
  }

  return (
    <button
      onClick={toggleSound}
      aria-pressed={on}
      aria-label={label}
      title={title}
      data-sound={state}
      className="fixed bottom-5 left-5 z-50 flex h-11 items-end gap-[3px] rounded-full border border-ink/20 bg-surface/70 px-4 pb-3 backdrop-blur md:bottom-6 md:left-6"
    >
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className={`w-[3px] rounded bg-ink ${on ? 'eq-bar' : waiting ? 'eq-wait' : ''}`}
          style={{ height: 4, animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </button>
  )
}
