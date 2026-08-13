import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorBanner, ErrorState } from '@/components/ui/error-state'
import { Input } from '@/components/ui/input'
import { Loader } from '@/components/ui/loader'
import { SearchField } from '@/components/ui/search-field'
import { ExternalLink, RefreshCw, Settings } from '@/lib/icons'
import { cn } from '@/lib/utils'

import {
  createProfileFact,
  decideCandidate,
  exportApplications,
  generateResume,
  getBioJobDashboard,
  importCandidate,
  importProfileDocument,
  listCandidates,
  listJobs,
  listProfileFacts,
  listSources,
  patchJob,
  runJobMatch,
  runEnabledSources,
  runSource,
  setProfileFactStatus,
  updateSource
} from './api'
import { useBioJobCopy } from './copy'
import type {
  ApplicationStatus,
  BioJobCandidate,
  BioJobBatchRun,
  BioJobDashboard,
  BioJobMatchReport,
  BioJobRecord,
  BioJobSource,
  ProfileFact
} from './types'

type View = 'applications' | 'candidates' | 'facts' | 'overview' | 'sources'

interface WorkspaceData {
  candidates: BioJobCandidate[]
  dashboard: BioJobDashboard
  facts: ProfileFact[]
  jobs: BioJobRecord[]
  sources: BioJobSource[]
}

const NEXT_STATUS: Partial<Record<ApplicationStatus, ApplicationStatus[]>> = {
  considering: ['preparing', 'withdrawn', 'expired'],
  preparing: ['applied', 'rejected', 'withdrawn', 'expired'],
  applied: ['assessment', 'interview', 'offer', 'rejected', 'expired'],
  assessment: ['interview', 'offer', 'rejected', 'expired'],
  interview: ['offer', 'rejected', 'expired']
}

function count(record: Record<string, number> | undefined, key: string): number {
  return record?.[key] ?? 0
}

function displayFact(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }

  if (Array.isArray(value)) {
    return value.map(displayFact).join('、')
  }

  if (value && typeof value === 'object') {
    return Object.values(value).map(displayFact).join('、')
  }

  return ''
}

export function BioJobWorkbench() {
  const c = useBioJobCopy()
  const navigate = useNavigate()
  const [view, setView] = useState<View>('overview')
  const [data, setData] = useState<WorkspaceData | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setError(null)

    try {
      const [dashboard, candidates, jobs, facts, sources] = await Promise.all([
        getBioJobDashboard(),
        listCandidates(),
        listJobs(),
        listProfileFacts(),
        listSources()
      ])

      setData({ candidates, dashboard, facts, jobs, sources })
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error(String(nextError)))
    }
  }, [])

  useEffect(() => void refresh(), [refresh])

  const perform = useCallback(
    async (key: string, operation: () => Promise<unknown>, after?: () => Promise<void>) => {
      setBusy(key)
      setActionError(null)

      try {
        await operation()
        await (after?.() ?? refresh())
      } catch {
        setActionError(c.requestFailed)
      } finally {
        setBusy(null)
      }
    },
    [c.requestFailed, refresh]
  )

  if (error) {
    return (
      <div className="grid h-full place-items-center bg-(--ui-bg-primary) p-8">
        <ErrorState className="max-w-md" description={c.errorDesc} title={c.errorTitle}>
          <Button onClick={() => void refresh()} variant="secondary">
            {c.retry}
          </Button>
        </ErrorState>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="grid h-full place-items-center bg-(--ui-bg-primary)">
        <Loader label={c.loading} type="lemniscate-bloom" />
      </div>
    )
  }

  const navItems: Array<{ icon: string; id: View; label: string }> = [
    { icon: 'home', id: 'overview', label: c.nav.overview },
    { icon: 'search', id: 'candidates', label: c.nav.candidates },
    { icon: 'checklist', id: 'applications', label: c.nav.applications },
    { icon: 'beaker', id: 'facts', label: c.nav.facts },
    { icon: 'radio-tower', id: 'sources', label: c.nav.sources }
  ]

  return (
    <main className="relative flex h-full min-h-0 overflow-hidden bg-(--ui-bg-primary) text-(--ui-text-primary)">
      <aside className="flex w-48 shrink-0 flex-col border-r border-(--ui-stroke-tertiary) bg-(--ui-sidebar-surface-background) px-3 py-5 max-md:w-14 max-md:px-1.5">
        <div className="mb-7 px-2 max-md:hidden">
          <div className="font-mono text-[0.625rem] tracking-[0.2em] text-(--theme-primary)">{c.eyebrow}</div>
          <div className="mt-2 font-serif text-xl font-semibold tracking-tight">BioJob</div>
        </div>
        <nav aria-label="BioJob" className="grid gap-1">
          {navItems.map(item => (
            <button
              aria-label={item.label}
              className={cn(
                'group flex cursor-pointer items-center gap-2.5 rounded-[4px] px-2.5 py-2 text-left text-xs transition-[background,color] duration-100 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none',
                view === item.id
                  ? 'bg-(--ui-bg-quaternary) font-medium text-(--ui-text-primary)'
                  : 'text-(--ui-text-secondary) hover:bg-(--chrome-action-hover) hover:text-(--ui-text-primary)'
              )}
              key={item.id}
              onClick={() => setView(item.id)}
              type="button"
            >
              <Codicon className="shrink-0" name={item.icon} size="0.9rem" />
              <span className="max-md:hidden">{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="mt-auto grid gap-1">
          <Button
            aria-label={c.aiSettings}
            onClick={() => navigate('/settings?tab=providers')}
            size="sm"
            variant="ghost"
          >
            <Settings />
            <span className="max-md:hidden">{c.aiSettings}</span>
          </Button>
        </div>
      </aside>

      <section className="min-w-0 flex-1 overflow-y-auto">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-(--ui-stroke-tertiary) bg-(--ui-bg-primary)/95 px-[var(--page-inset-x)] py-4 backdrop-blur-sm">
          <div>
            <h1 className="font-serif text-2xl font-semibold tracking-tight">{c.title}</h1>
            <p className="mt-0.5 max-w-2xl text-xs text-(--ui-text-secondary)">{c.subtitle}</p>
          </div>
          <Button
            aria-label={c.refresh}
            disabled={busy === 'refresh'}
            onClick={() => void perform('refresh', refresh)}
            size="icon-sm"
            variant="ghost"
          >
            <RefreshCw />
          </Button>
        </header>

        <div className="mx-auto w-full max-w-[1100px] px-[var(--page-inset-x)] py-6 motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1">
          {actionError && <ErrorBanner className="mb-5">{actionError}</ErrorBanner>}
          {view === 'overview' && <Overview data={data} onView={setView} />}
          {view === 'candidates' && <CandidatesView busy={busy} candidates={data.candidates} perform={perform} />}
          {view === 'applications' && <ApplicationsView busy={busy} jobs={data.jobs} perform={perform} />}
          {view === 'facts' && <FactsView busy={busy} facts={data.facts} perform={perform} />}
          {view === 'sources' && <SourcesView busy={busy} perform={perform} sources={data.sources} />}
        </div>
      </section>
    </main>
  )
}

function Overview({ data, onView }: { data: WorkspaceData; onView: (view: View) => void }) {
  const c = useBioJobCopy()
  const confirmedFacts = data.facts.filter(fact => fact.status === 'confirmed').length

  const metrics = [
    [c.metrics.pending, count(data.dashboard.candidate_counts, 'pending'), 'search'],
    [c.metrics.preparing, count(data.dashboard.application_counts, 'preparing'), 'edit'],
    [c.metrics.sources, data.dashboard.source_counts.enabled, 'radio-tower'],
    [c.metrics.facts, confirmedFacts, 'beaker']
  ] as const

  return (
    <div className="grid gap-8">
      <section className="grid grid-cols-4 border-y border-(--ui-stroke-tertiary) max-lg:grid-cols-2 max-sm:grid-cols-1">
        {metrics.map(([label, value, icon], index) => (
          <div
            className={cn(
              'flex items-center gap-4 px-5 py-6',
              index > 0 && 'border-l border-(--ui-stroke-tertiary) max-lg:odd:border-l-0 max-sm:border-l-0'
            )}
            key={label}
          >
            <Codicon className="text-(--theme-primary)" name={icon} size="1rem" />
            <div>
              <div className="font-mono text-3xl tabular-nums">{value}</div>
              <div className="mt-1 text-[0.6875rem] uppercase tracking-[0.12em] text-(--ui-text-tertiary)">{label}</div>
            </div>
          </div>
        ))}
      </section>
      <section>
        <h2 className="font-serif text-lg font-semibold">{c.nextTitle}</h2>
        <div className="mt-3 grid gap-0 border-y border-(--ui-stroke-tertiary)">
          <ActionRow index="01" text={c.nextCandidate}>
            <Button onClick={() => onView('candidates')} size="xs" variant="secondary">
              {c.openCandidates}
            </Button>
          </ActionRow>
          <ActionRow index="02" text={c.nextFacts}>
            <Button onClick={() => onView('facts')} size="xs" variant="secondary">
              {c.openFacts}
            </Button>
          </ActionRow>
          <ActionRow index="03" text={c.nextApply} />
        </div>
      </section>
    </div>
  )
}

function ActionRow({ children, index, text }: { children?: React.ReactNode; index: string; text: string }) {
  return (
    <div className="flex min-h-14 items-center gap-4 border-b border-(--ui-stroke-tertiary) px-2 last:border-b-0">
      <span className="font-mono text-[0.625rem] text-(--theme-primary)">{index}</span>
      <span className="min-w-0 flex-1 text-sm">{text}</span>
      {children}
    </div>
  )
}

type Performer = (key: string, operation: () => Promise<unknown>, after?: () => Promise<void>) => Promise<void>

function CandidatesView({
  busy,
  candidates,
  perform
}: {
  busy: string | null
  candidates: BioJobCandidate[]
  perform: Performer
}) {
  const c = useBioJobCopy()
  const [query, setQuery] = useState('')
  const [showImport, setShowImport] = useState(false)

  const visible = useMemo(
    () =>
      candidates.filter(item =>
        `${item.company.name} ${item.title} ${item.jd_text ?? ''}`.toLowerCase().includes(query.toLowerCase())
      ),
    [candidates, query]
  )

  return (
    <section>
      <PageHeading
        action={
          <Button onClick={() => setShowImport(value => !value)} size="sm" variant="secondary">
            {showImport ? c.closeImport : c.importJob}
          </Button>
        }
        subtitle={c.candidateSubtitle}
        title={c.candidateTitle}
      />
      {showImport && <CandidateImportForm busy={busy} perform={perform} />}
      {candidates.length > 0 && (
        <SearchField
          aria-label={c.searchJobs}
          containerClassName="my-5"
          onChange={setQuery}
          placeholder={c.searchJobs}
          value={query}
        />
      )}
      {visible.length === 0 ? (
        <EmptyState description={c.noCandidatesDesc} title={c.noCandidates} />
      ) : (
        <div className="divide-y divide-(--ui-stroke-tertiary) border-y border-(--ui-stroke-tertiary)">
          {visible.map(candidate => (
            <CandidateRow busy={busy} candidate={candidate} key={candidate.id} perform={perform} />
          ))}
        </div>
      )}
    </section>
  )
}

function CandidateRow({
  busy,
  candidate,
  perform
}: {
  busy: string | null
  candidate: BioJobCandidate
  perform: Performer
}) {
  const c = useBioJobCopy()

  return (
    <article className="grid gap-4 py-5 sm:grid-cols-[1fr_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-2">
          <h3 className="font-serif text-lg font-semibold">{candidate.title}</h3>
          <span className="font-mono text-xs text-(--theme-primary)">{candidate.match.score}</span>
          {candidate.needs_verification && (
            <span className="border border-(--ui-stroke-secondary) px-1.5 py-0.5 text-[0.625rem] text-(--ui-text-secondary)">
              {c.needsVerification}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-(--ui-text-secondary)">
          {candidate.company.name}
          {candidate.city ? ` · ${candidate.city}` : ''} · {c.matching}：{candidate.match.recommendation}
        </p>
        <p className="mt-3 line-clamp-2 text-sm leading-6 text-(--ui-text-secondary)">{candidate.jd_text}</p>
        <div className="mt-3 flex flex-wrap gap-3 text-xs">
          <JobLink href={candidate.links.detail} label={candidate.needs_verification ? c.openOriginal : c.viewJd} />
          <JobLink href={candidate.links.apply} label={c.applyNow} />
          <JobLink href={candidate.links.careers} label={c.careers} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 sm:flex-col sm:items-stretch">
        <Button
          disabled={busy === candidate.id}
          onClick={() => void perform(candidate.id, () => decideCandidate(candidate.id, 'kept'))}
          size="xs"
        >
          {c.keep}
        </Button>
        <Button
          disabled={busy === candidate.id}
          onClick={() => void perform(candidate.id, () => decideCandidate(candidate.id, 'later'))}
          size="xs"
          variant="secondary"
        >
          {c.later}
        </Button>
        <Button
          disabled={busy === candidate.id}
          onClick={() => void perform(candidate.id, () => decideCandidate(candidate.id, 'ignored'))}
          size="xs"
          variant="text"
        >
          {c.ignore}
        </Button>
      </div>
    </article>
  )
}

function CandidateImportForm({ busy, perform }: { busy: string | null; perform: Performer }) {
  const c = useBioJobCopy()

  const [form, setForm] = useState({
    company_name: '',
    title: '',
    detail_url: '',
    apply_url: '',
    city: '',
    jd_text: ''
  })

  const field = (key: keyof typeof form) => ({
    onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm(current => ({ ...current, [key]: event.target.value })),
    value: form[key]
  })

  return (
    <form
      className="my-5 grid gap-3 border-y border-(--ui-stroke-tertiary) py-4"
      onSubmit={event => {
        event.preventDefault()
        void perform('import', () =>
          importCandidate(Object.fromEntries(Object.entries(form).filter(([, value]) => value.trim())) as never)
        )
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Input aria-label={c.company} placeholder={c.company} required {...field('company_name')} />
        <Input aria-label={c.role} placeholder={c.role} required {...field('title')} />
        <Input aria-label={c.detailUrl} placeholder={c.detailUrl} required type="url" {...field('detail_url')} />
        <Input aria-label={c.applyUrl} placeholder={c.applyUrl} type="url" {...field('apply_url')} />
        <Input aria-label={c.city} placeholder={c.city} {...field('city')} />
        <Input aria-label={c.jdText} placeholder={c.jdText} {...field('jd_text')} />
      </div>
      <Button disabled={busy === 'import'} size="sm" type="submit">
        {c.createCandidate}
      </Button>
    </form>
  )
}

function ApplicationsView({ busy, jobs, perform }: { busy: string | null; jobs: BioJobRecord[]; perform: Performer }) {
  const c = useBioJobCopy()
  const [reports, setReports] = useState<Record<string, BioJobMatchReport>>({})

  return (
    <section>
      <PageHeading
        action={
          <Button
            disabled={busy === 'export-applications'}
            onClick={() =>
              void perform(
                'export-applications',
                async () => {
                  const result = await exportApplications()
                  await window.hermesDesktop?.revealPath?.(result.file_path)
                },
                async () => {}
              )
            }
            size="sm"
            variant="secondary"
          >
            {c.exportTracker}
          </Button>
        }
        subtitle={c.applicationSubtitle}
        title={c.applicationTitle}
      />
      {jobs.length === 0 ? (
        <EmptyState description={c.noApplicationsDesc} title={c.noApplications} />
      ) : (
        <div className="divide-y divide-(--ui-stroke-tertiary) border-y border-(--ui-stroke-tertiary)">
          {jobs.map(job => (
            <article className="py-5" key={job.id}>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h3 className="font-serif text-lg font-semibold">{job.title}</h3>
                  <p className="mt-1 text-xs text-(--ui-text-secondary)">
                    {job.company.name}
                    {job.city ? ` · ${job.city}` : ''}
                  </p>
                  <div className="mt-3 flex gap-3">
                    <JobLink href={job.links.detail} label={c.viewJd} />
                    <JobLink href={job.links.apply} label={c.applyNow} />
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-[0.625rem] uppercase tracking-wider text-(--ui-text-tertiary)">
                    {c.status}
                  </div>
                  <div className="mt-1 text-sm font-medium">{c.statusLabels[job.application.status]}</div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {(NEXT_STATUS[job.application.status] ?? []).map(status => (
                  <Button
                    disabled={busy === `${job.id}:${status}`}
                    key={status}
                    onClick={() =>
                      void perform(`${job.id}:${status}`, () => patchJob(job.id, { application_status: status }))
                    }
                    size="xs"
                    variant="secondary"
                  >
                    {c.statusLabels[status]}
                  </Button>
                ))}
                <Button
                  disabled={busy === `${job.id}:match`}
                  onClick={() =>
                    void perform(
                      `${job.id}:match`,
                      async () => {
                        const report = await runJobMatch(job.id)
                        setReports(current => ({ ...current, [job.id]: report }))
                      },
                      async () => {}
                    )
                  }
                  size="xs"
                  variant="outline"
                >
                  {c.runMatch}
                </Button>
                {job.application.status === 'preparing' && (
                  <Button
                    disabled={busy === `${job.id}:resume`}
                    onClick={() =>
                      void perform(
                        `${job.id}:resume`,
                        async () => {
                          const result = await generateResume(job.id)
                          await window.hermesDesktop?.revealPath?.(result.file_path)
                        },
                        async () => {}
                      )
                    }
                    size="xs"
                    variant="secondary"
                  >
                    {c.generateResume}
                  </Button>
                )}
              </div>
              {reports[job.id] && <MatchReport report={reports[job.id]} />}
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function MatchReport({ report }: { report: BioJobMatchReport }) {
  const c = useBioJobCopy()

  return (
    <div className="mt-5 border-l-2 border-(--theme-primary) pl-4">
      <div className="flex items-end gap-3">
        <span className="font-mono text-3xl tabular-nums">{report.score}</span>
        <span className="pb-1 text-xs text-(--ui-text-secondary)">
          {c.matchScore} · {report.recommendation}
        </span>
      </div>
      {report.blocked && <p className="mt-2 text-sm text-destructive">{c.blocked}</p>}
      <h4 className="mt-4 text-xs font-semibold uppercase tracking-wider text-(--ui-text-tertiary)">{c.evidence}</h4>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {report.dimensions.map(dimension => (
          <div className="flex justify-between gap-4 text-xs" key={dimension.key}>
            <span>{dimension.label}</span>
            <span className="font-mono">
              {dimension.score}/{dimension.weight}
            </span>
          </div>
        ))}
      </div>
      {report.gaps.length > 0 && (
        <p className="mt-3 text-xs text-(--ui-text-secondary)">
          <strong>{c.gaps}：</strong>
          {report.gaps.join('；')}
        </p>
      )}
      {report.risks.length > 0 && (
        <p className="mt-2 text-xs text-(--ui-text-secondary)">
          <strong>{c.risks}：</strong>
          {report.risks.join('；')}
        </p>
      )}
    </div>
  )
}

function FactsView({ busy, facts, perform }: { busy: string | null; facts: ProfileFact[]; perform: Performer }) {
  const c = useBioJobCopy()
  const [form, setForm] = useState({ category: 'skills', fact_key: '', value: '', visibility: 'both' as const })

  return (
    <section>
      <PageHeading
        action={
          <Button
            disabled={busy === 'profile-document-import'}
            onClick={() =>
              void perform('profile-document-import', async () => {
                const paths = await window.hermesDesktop?.selectPaths({
                  filters: [{ extensions: ['docx', 'pdf'], name: 'Resume documents' }],
                  multiple: false,
                  title: c.importResume
                })

                if (paths?.[0]) {
                  await importProfileDocument(paths[0])
                }
              })
            }
            size="sm"
            variant="secondary"
          >
            {c.importResume}
          </Button>
        }
        subtitle={`${c.factsSubtitle} ${c.importResumeHint}`}
        title={c.factsTitle}
      />
      <form
        className="my-5 grid gap-3 border-y border-(--ui-stroke-tertiary) py-4 sm:grid-cols-[1fr_1fr_2fr_auto]"
        onSubmit={event => {
          event.preventDefault()
          void perform('fact-add', () => createProfileFact({ ...form, source_type: 'user' }))
        }}
      >
        <Input
          aria-label={c.factCategory}
          onChange={event => setForm(current => ({ ...current, category: event.target.value }))}
          placeholder={c.factCategory}
          value={form.category}
        />
        <Input
          aria-label={c.factKey}
          onChange={event => setForm(current => ({ ...current, fact_key: event.target.value }))}
          placeholder={c.factKey}
          required
          value={form.fact_key}
        />
        <Input
          aria-label={c.factValue}
          onChange={event => setForm(current => ({ ...current, value: event.target.value }))}
          placeholder={c.factValue}
          required
          value={form.value}
        />
        <Button disabled={busy === 'fact-add'} size="sm" type="submit">
          {c.addFact}
        </Button>
      </form>
      {facts.length === 0 ? (
        <EmptyState description={c.noFactsDesc} title={c.noFacts} />
      ) : (
        <div className="divide-y divide-(--ui-stroke-tertiary) border-y border-(--ui-stroke-tertiary)">
          {facts.map(fact => (
            <div className="flex flex-wrap items-center gap-3 py-4" key={fact.id}>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{displayFact(fact.value)}</div>
                <div className="mt-1 font-mono text-[0.625rem] text-(--ui-text-tertiary)">
                  {fact.category} · {fact.fact_key} · {fact.visibility}
                </div>
              </div>
              <span className="text-xs text-(--ui-text-secondary)">
                {fact.status === 'confirmed' ? c.confirmed : fact.status === 'rejected' ? c.rejected : c.pending}
              </span>
              {fact.status === 'pending' && (
                <>
                  <Button
                    disabled={busy === fact.id}
                    onClick={() => void perform(fact.id, () => setProfileFactStatus(fact.id, 'confirmed'))}
                    size="xs"
                    variant="secondary"
                  >
                    {c.confirm}
                  </Button>
                  <Button
                    disabled={busy === fact.id}
                    onClick={() => void perform(fact.id, () => setProfileFactStatus(fact.id, 'rejected'))}
                    size="xs"
                    variant="text"
                  >
                    {c.reject}
                  </Button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function SourcesView({ busy, perform, sources }: { busy: string | null; perform: Performer; sources: BioJobSource[] }) {
  const c = useBioJobCopy()
  const [batchSummary, setBatchSummary] = useState<BioJobBatchRun['summary'] | null>(null)
  const automaticSources = sources.filter(source => source.adapter_type !== 'portal')
  const portals = sources.filter(source => source.adapter_type === 'portal')

  return (
    <section>
      <PageHeading
        action={
          <Button
            disabled={automaticSources.every(source => !source.enabled) || busy === 'sources:all'}
            onClick={() =>
              void perform('sources:all', async () => {
                const result = await runEnabledSources()
                setBatchSummary(result.summary)
              })
            }
            size="sm"
          >
            {c.runAllSources}
          </Button>
        }
        subtitle={c.sourcesSubtitle}
        title={c.sourcesTitle}
      />
      {batchSummary && (
        <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 border-y border-(--ui-stroke-tertiary) py-3 font-mono text-xs">
          <span>{c.batchNew} {batchSummary.new_candidates}</span>
          <span>{c.batchMerged} {batchSummary.merged_results}</span>
          <span>{c.batchPending} {batchSummary.pending_verification}</span>
          <span>{c.batchFailed} {batchSummary.failed_sources}</span>
        </div>
      )}
      {sources.length === 0 ? (
        <EmptyState title={c.noSources} />
      ) : (
        <div className="mt-7 grid gap-8">
          <SourceGroup title={c.automaticSources}>
          {automaticSources.map(source => (
            <div className="flex flex-wrap items-center gap-4 py-4" key={source.id}>
              <Codicon
                className={source.health_status === 'failed' ? 'text-destructive' : 'text-(--theme-primary)'}
                name="radio-tower"
                size="0.9rem"
              />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{source.name}</div>
                <div className="mt-1 text-xs text-(--ui-text-tertiary)">
                  {source.description} ·{' '}
                  {source.health_status === 'healthy'
                    ? c.healthy
                    : source.health_status === 'failed'
                      ? `${c.failed}：${c.sourceFailedHint}`
                      : c.unknown}
                </div>
              </div>
              <Button
                disabled={busy === `${source.id}:toggle`}
                onClick={() =>
                  void perform(`${source.id}:toggle`, () => updateSource(source.id, { enabled: !source.enabled }))
                }
                size="xs"
                variant="text"
              >
                {source.enabled ? c.enabled : c.disabled}
              </Button>
              <Button
                disabled={!source.enabled || busy === source.id}
                onClick={() => void perform(source.id, () => runSource(source.id))}
                size="xs"
                variant="secondary"
              >
                {c.run}
              </Button>
            </div>
          ))}
          </SourceGroup>
          <SourceGroup title={c.officialPortals}>
            {portals.map(source => {
              const portalUrl = typeof source.config.url === 'string' ? source.config.url : null
              return (
                <div className="flex flex-wrap items-center gap-4 py-4" key={source.id}>
                  <Codicon className="text-(--theme-primary)" name="link-external" size="0.9rem" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{source.name}</div>
                    <div className="mt-1 text-xs text-(--ui-text-tertiary)">{source.description}</div>
                  </div>
                  {portalUrl && (
                    <Button asChild size="xs" variant="secondary">
                      <a href={portalUrl} rel="noreferrer" target="_blank">{c.openPortal}</a>
                    </Button>
                  )}
                </div>
              )
            })}
          </SourceGroup>
        </div>
      )}
    </section>
  )
}

function SourceGroup({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <section>
      <h3 className="font-serif text-base font-semibold">{title}</h3>
      <div className="mt-2 divide-y divide-(--ui-stroke-tertiary) border-y border-(--ui-stroke-tertiary)">
        {children}
      </div>
    </section>
  )
}

function PageHeading({ action, subtitle, title }: { action?: React.ReactNode; subtitle: string; title: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h2 className="font-serif text-xl font-semibold tracking-tight">{title}</h2>
        <p className="mt-1 max-w-2xl text-xs leading-5 text-(--ui-text-secondary)">{subtitle}</p>
      </div>
      {action}
    </div>
  )
}

function JobLink({ href, label }: { href: null | string; label: string }) {
  if (!href) {
    return null
  }

  return (
    <a
      className="inline-flex items-center gap-1 text-xs text-(--ui-text-secondary) underline decoration-(--ui-stroke-primary) underline-offset-4 hover:text-(--ui-text-primary)"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {label}
      <ExternalLink className="size-3" />
    </a>
  )
}

export default BioJobWorkbench
