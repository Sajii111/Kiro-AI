import { BRAND } from '../brand'
import TransitionMark from '../components/TransitionMark'
import { t } from '../i18n'

/** A still, quiet screen for the moment while something loads (the first visit to a page whose code is still arriving). */
export default function Splash({ label }: { label?: string }) {
  return (
    <main data-splash className="app-bg grid min-h-screen place-items-center px-6 text-center">
      <div className="flex flex-col items-center">
        <TransitionMark size={56} />
        <p className="mt-6 font-display text-4xl tracking-tight">
          {BRAND.short}
          <span className="text-accent-ink">.</span>
        </p>
        <p role="status" className="mt-3 text-sm text-muted">
          {label ?? t("Just a moment…")}
        </p>
      </div>
    </main>
  )
}
