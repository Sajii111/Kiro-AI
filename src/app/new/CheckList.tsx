import type { CheckStatus, PhotoCheck } from '../../api/types'
import Icon from '../../components/ui/icons'
import Spinner from '../../components/ui/Spinner'
import { t, tServer } from '../../i18n'

const ORDER = [t("File type"), t("File opens"), t("Size"), t("Focus"), t("Lighting"), t("Palm in view")]

function StatusIcon({ status }: { status: CheckStatus | 'pending' }) {
  if (status === 'pending') return <Spinner size={14} className="text-muted" />
  const tone = status === 'pass' ? 'bg-detected/15 text-detected' : status === 'warn' ? 'bg-uncertain/20 text-uncertain' : 'bg-danger/15 text-danger'
  return (
    <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full ${tone}`}>
      <Icon name={status === 'pass' ? 'check' : status === 'warn' ? 'alert' : 'x'} size={12} />
    </span>
  )
}

/** The photo checks, one per row. While the photo is being checked the rows show a spinner; then each gets its result. */
export default function CheckList({ checks }: { checks: PhotoCheck[] | null }) {
  const rows = checks ?? ORDER.map((label) => ({ id: label, label, status: 'pending' as const, message: '' }))
  return (
    <ul className="divide-y divide-ink/10 text-sm" aria-busy={checks === null}>
      {rows.map((row, i) => (
        <li
          key={row.id}
          className={`flex items-start gap-3 py-2.5 ${checks ? 'page-in' : ''}`}
          style={checks ? { animationDelay: `${i * 70}ms` } : undefined}
        >
          <span className="mt-0.5">
            <StatusIcon status={row.status} />
          </span>
          <span className="min-w-0 flex-1">
            <span className={`font-medium ${row.status === 'pending' ? 'text-muted' : ''}`}>{t(row.label)}</span>
            {row.message && (
              <span className={`mt-0.5 block ${row.status === 'pass' ? 'text-muted' : row.status === 'warn' ? 'text-ink' : 'text-danger'}`}>
                <span className="sr-only">{row.status === 'pass' ? t("Passed. ") : row.status === 'warn' ? t("Warning. ") : t("Failed. ")}</span>
                {tServer(row.message)}
              </span>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}
