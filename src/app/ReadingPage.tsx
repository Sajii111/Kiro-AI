import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { FeatureId, Reading } from '../api/types'
import StatusDot from '../components/StatusDot'
import Icon from '../components/ui/icons'
import { useToast } from '../components/ui/Toast'
import { formatDate } from '../lib/format'
import { FEATURE_ORDER } from '../lib/features'
import { countStatuses, readingLabel } from '../lib/readings'
import { useResource } from '../lib/useResource'
import { useData } from '../state/data'
import NotFound from './NotFound'
import Chat from './reading/Chat'
import LinesSection from './reading/LinesSection'
import ReportSection, { type ReportView } from './reading/ReportSection'
import { DeleteReadingModal, RenameReadingModal } from './ReadingModals'
import { t } from '../i18n'

// One reading: the annotated lines, the written report and the chat.
// Wide screens show all three (the chat stays in view on the right); narrower ones show one at a time.

type Tab = 'lines' | 'report' | 'chat'
const TABS: { id: Tab; label: string }[] = [
  { id: 'lines', label: t("Lines") },
  { id: 'report', label: t("Report") },
  { id: 'chat', label: t("Chat") },
]

type Section = 'summary' | 'comparison' | 'uncertainty' | 'themes' | 'shape'

/** The element of the page a chat answer's "Based on" button should scroll to. */
const targetOf = (section: string): string =>
  section === 'uncertainty' ? 'report-uncertainty' : section === 'comparison' ? 'report-lines' : section === 'themes' ? 'report-themes' : section === 'shape' ? 'report-shape' : 'report'

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches
const scrollToId = (id: string) =>
  requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' }))

export default function ReadingPage() {
  const { id = '' } = useParams()
  const reading = useResource(() => api.getReading(id), [id])

  if (reading.error) return <NotFound title={t("That reading is not here")} note={t("It may have been deleted, or the link may be wrong.")} />
  if (reading.data === undefined) {
    return (
      <div aria-busy="true" className="space-y-6">
        <div className="h-5 w-24 animate-pulse rounded-full bg-ink/5" />
        <div className="h-14 w-2/3 animate-pulse rounded-2xl bg-ink/5" />
        <div className="grid gap-6 sm:grid-cols-2">
          <div className="aspect-[4/5] animate-pulse rounded-3xl bg-ink/5" />
          <div className="aspect-[4/5] animate-pulse rounded-3xl bg-ink/5" />
        </div>
      </div>
    )
  }
  // keyed by reading, so the selection, tab and chat all start fresh for every reading
  // (renaming loads the reading again; the old one stays on screen until the new one arrives)
  return <ReadingView key={reading.data.id} reading={reading.data} onRenamed={reading.reload} />
}

function ReadingView({ reading, onRenamed }: { reading: Reading; onRenamed: () => void }) {
  const navigate = useNavigate()
  const toast = useToast()
  const [params] = useSearchParams()
  const { profiles, activeProfile, setActiveProfileId } = useData()
  const profile = profiles?.find((p) => p.id === reading.profileId) ?? null

  // the chat page links here with ?line=heart or ?section=comparison, to show what an answer was based on
  const lineParam = params.get('line') as FeatureId | null
  const sectionParam = params.get('section')
  const startLine = lineParam && FEATURE_ORDER.includes(lineParam) ? lineParam : null
  const [tab, setTab] = useState<Tab>(sectionParam ? 'report' : 'lines')
  const [selected, setSelected] = useState<FeatureId | null>(startLine)
  const [deleting, setDeleting] = useState(false)
  const [renaming, setRenaming] = useState(false)
  // the report opens by theme; the person can switch to one card per line
  const [reportView, setReportView] = useState<ReportView>(sectionParam === 'comparison' ? 'line' : 'theme')

  useEffect(() => {
    if (sectionParam) scrollToId(targetOf(sectionParam))
    else if (startLine) scrollToId('lines')
    // only when the page opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // A reading belongs to one profile: make that profile the active one when the page opens. This only runs when
  // the profile becomes known, so choosing another profile from the header afterwards is never undone.
  const activeId = useRef(activeProfile?.id)
  useEffect(() => {
    activeId.current = activeProfile?.id
  })
  const profileId = profile?.id
  useEffect(() => {
    if (profileId && activeId.current !== profileId) setActiveProfileId(profileId)
  }, [profileId, setActiveProfileId])

  const counts = countStatuses(reading)
  const name = profile?.name ?? t("This reading")
  // a reading the person named goes by that name; otherwise it is "<profile>’s palms", as before
  const title = reading.name ?? t("{name}’s palms", { name: name })

  const focusLine = (id: FeatureId) => {
    setSelected(id)
    setTab('lines')
    scrollToId('lines')
  }
  const showSection = (section: Section) => {
    setTab('report')
    if (section === 'comparison') setReportView('line')
    if (section === 'themes') setReportView('theme')
    scrollToId(targetOf(section))
  }
  const switchTo = async (profileId: string) => {
    const target = profiles?.find((p) => p.id === profileId)
    setActiveProfileId(profileId)
    toast(t("Switched to {0}. Their chat starts fresh.", { "0": target?.name ?? 'that profile' }))
    try {
      const mine = await api.listReadings(profileId)
      navigate(mine[0] ? `/app/readings/${mine[0].id}` : '/app/new')
    } catch {
      navigate('/app')
    }
  }

  return (
    <div>
      <header>
        <div className="flex items-center justify-between gap-3">
          <Link to="/app" className="inline-flex items-center gap-2 text-sm text-muted transition-colors hover:text-ink">
            <Icon name="arrow-left" size={16} /> {t("All readings")}
          </Link>
          <div className="flex gap-2">
            <Link to="/app/new" aria-label={t("New reading")} title={t("New reading")} className="btn btn-ghost btn-sm">
              <Icon name="plus" size={15} />
              <span className="hidden sm:inline">{t("New reading")}</span>
            </Link>
            <button
              type="button"
              onClick={() => setRenaming(true)}
              aria-label={reading.name ? t("Rename this reading") : t("Name this reading")}
              title={reading.name ? t("Rename this reading") : t("Name this reading")}
              className="btn btn-ghost btn-sm"
            >
              <Icon name="pencil" size={15} />
              <span className="hidden sm:inline">{reading.name ? t("Rename") : t("Add name")}</span>
            </button>
            <button
              type="button"
              onClick={() => setDeleting(true)}
              aria-label={t("Delete this reading")}
              title={t("Delete this reading")}
              className="btn btn-ghost btn-sm hover:!border-danger hover:!bg-danger/10 hover:!text-danger"
            >
              <Icon name="trash" size={15} />
              <span className="hidden sm:inline">{t("Delete")}</span>
            </button>
          </div>
        </div>

        <p className="kicker mt-5 flex flex-wrap items-center gap-x-3 gap-y-2">
          {reading.name ? t("{name}’s palms", { name: name }) : t("Reading")} · {formatDate(reading.createdAt)}
          {reading.meta.mock && <span className="rounded-full bg-uncertain/25 px-3 py-0.5 text-xs font-medium normal-case tracking-normal text-ink">{t("Sample reading")}</span>}
        </p>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-8 gap-y-3">
          <h1 className="text-balance font-display text-4xl font-light tracking-tight [overflow-wrap:anywhere] md:text-5xl">{title}</h1>
          <p className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
            <span className="flex items-center gap-1.5">
              <StatusDot status="detected" /> {counts.detected} {t("detected")}
            </span>
            <span className="flex items-center gap-1.5">
              <StatusDot status="uncertain" /> {counts.uncertain} {t("uncertain")}
            </span>
            <span className="flex items-center gap-1.5">
              <StatusDot status="not_visible" /> {counts.not_visible} {t("not visible")}
            </span>
          </p>
        </div>
      </header>

      <div role="tablist" aria-label={t("Parts of this reading")} className="mt-6 flex gap-1 rounded-full border border-ink/15 bg-surface/80 p-1 text-sm xl:hidden">
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => {
              setTab(t.id)
              if (t.id === 'chat') scrollToId('panel-chat')
            }}
            className={`flex-1 rounded-full px-4 py-2.5 transition-colors ${tab === t.id ? 'bg-ink text-paper' : 'text-ink/75 hover:text-ink'}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-10 xl:grid-cols-[minmax(0,1fr)_27rem] xl:gap-12">
        <div id="panel-lines" role="tabpanel" aria-labelledby="tab-lines" className={`xl:col-start-1 xl:block ${tab === 'lines' ? '' : 'hidden'}`}>
          <section id="lines" className="scroll-mt-28">
            <LinesSection reading={reading} selected={selected} onSelect={setSelected} />
          </section>
        </div>

        <div id="panel-report" role="tabpanel" aria-labelledby="tab-report" className={`xl:col-start-1 xl:block ${tab === 'report' ? '' : 'hidden'}`}>
          <section id="report" className="scroll-mt-28">
            <ReportSection reading={reading} selected={selected} onShowLine={focusLine} view={reportView} onViewChange={setReportView} />
          </section>
        </div>

        <div id="panel-chat" role="tabpanel" aria-labelledby="tab-chat" className={`scroll-mt-28 xl:col-start-2 xl:row-span-2 xl:row-start-1 xl:block ${tab === 'chat' ? '' : 'hidden'}`}>
          {profile ? (
            <div className="xl:sticky xl:top-[7.5rem]">
              <Chat
                reading={reading}
                profile={profile}
                openChat={params.get('chat')}
                className="h-[calc(100dvh-13rem)] min-h-[28rem] md:h-[calc(100dvh-9rem)] md:min-h-[32rem] xl:min-h-[34rem]"
                onFocusLine={focusLine}
                onShowSection={showSection}
                onSwitchProfile={(id) => void switchTo(id)}
              />
            </div>
          ) : (
            <div className="h-[30rem] animate-pulse rounded-3xl bg-ink/5" aria-busy="true" />
          )}
        </div>
      </div>

      <RenameReadingModal reading={renaming ? { id: reading.id, name: reading.name } : null} onClose={() => setRenaming(false)} onRenamed={onRenamed} />
      <DeleteReadingModal
        reading={deleting ? { id: reading.id, label: readingLabel(reading, name) } : null}
        onClose={() => setDeleting(false)}
        onDeleted={() => navigate('/app', { replace: true })}
      />
    </div>
  )
}
