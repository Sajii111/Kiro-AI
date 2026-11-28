import { locale, plural, t } from '../i18n'
// Small helpers for showing dates, counts and sizes the same way everywhere.

const DATE = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric' })
const TIME = new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' })

export const formatDate = (iso: string) => DATE.format(new Date(iso))
export const formatTime = (iso: string) => TIME.format(new Date(iso))
export const formatDateTime = (iso: string) => `${formatDate(iso)}, ${formatTime(iso)}`

/** "Today", "Yesterday" or a date. */
export function relativeDay(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((startOf(now) - startOf(d)) / 86_400_000)
  if (days === 0) return t("Today")
  if (days === 1) return t("Yesterday")
  return formatDate(iso)
}

export { plural }

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

/** "1 h 52 min", "12 min", "45 s" */
export function formatCountdown(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000))
  if (s >= 3600) {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    return m ? t('{h} h {m} min', { h, m }) : t('{h} h', { h })
  }
  if (s >= 60) return t('{n} min', { n: Math.ceil(s / 60) })
  return t('{n} s', { n: s })
}

export function greeting(): string {
  const h = new Date().getHours()
  if (h < 5) return t("Still up")
  if (h < 12) return t("Good morning")
  if (h < 18) return t("Good afternoon")
  return t("Good evening")
}
