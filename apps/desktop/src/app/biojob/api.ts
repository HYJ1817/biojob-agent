import type {
  ApplicationExport,
  ApplicationStatus,
  BioJobCandidate,
  BioJobDashboard,
  BioJobMatchReport,
  BioJobRecord,
  BioJobSource,
  BioJobSourceRun,
  CandidateDecision,
  CandidateImportPayload,
  FactStatus,
  ProfileDocument,
  ProfileFact,
  ProfileFactCreatePayload,
  ResumeVersion
} from './types'

interface ApiOptions {
  body?: unknown
  method?: 'PATCH' | 'POST'
  path: string
  timeoutMs?: number
}

function call<T>(options: ApiOptions): Promise<T> {
  const api = window.hermesDesktop?.api

  return api ? api<T>(options) : Promise.reject(new Error('BioJob backend is not available'))
}

const itemList = <T>(path: string) => call<{ items: T[] }>({ path }).then(response => response.items)

export const getBioJobDashboard = () => call<BioJobDashboard>({ path: '/api/biojob/dashboard' })
export const listJobs = () => itemList<BioJobRecord>('/api/biojob/jobs')
export const getJob = (jobId: string) => call<BioJobRecord>({ path: `/api/biojob/jobs/${encodeURIComponent(jobId)}` })

export function patchJob(
  jobId: string,
  body: { application_status?: ApplicationStatus; next_follow_up_at?: null | string; notes?: null | string }
) {
  return call<BioJobRecord>({ body, method: 'PATCH', path: `/api/biojob/jobs/${encodeURIComponent(jobId)}` })
}

export function listCandidates(
  filters: {
    city?: string
    decision?: CandidateDecision
    direction?: string
    query?: string
  } = {}
) {
  const params = new URLSearchParams()
  params.set('decision', filters.decision ?? 'pending')

  for (const key of ['query', 'direction', 'city'] as const) {
    const value = filters[key]?.trim()

    if (value) {
      params.set(key, value)
    }
  }

  return itemList<BioJobCandidate>(`/api/biojob/candidates?${params.toString()}`)
}

export const getCandidate = (jobId: string) =>
  call<BioJobCandidate>({ path: `/api/biojob/candidates/${encodeURIComponent(jobId)}` })

export const importCandidate = (body: CandidateImportPayload) =>
  call<BioJobCandidate>({ body, method: 'POST', path: '/api/biojob/candidates/import' })

export const decideCandidate = (jobId: string, decision: CandidateDecision, note?: string) =>
  call<BioJobCandidate>({
    body: { decision, ...(note ? { note } : {}) },
    method: 'POST',
    path: `/api/biojob/candidates/${encodeURIComponent(jobId)}/decision`
  })

export const getJobMatch = (jobId: string) =>
  call<BioJobMatchReport>({ path: `/api/biojob/jobs/${encodeURIComponent(jobId)}/match` })

export const runJobMatch = (jobId: string) =>
  call<BioJobMatchReport>({ body: {}, method: 'POST', path: `/api/biojob/jobs/${encodeURIComponent(jobId)}/match` })

export function listProfileFacts(purpose?: 'matching' | 'resume') {
  return itemList<ProfileFact>(`/api/biojob/profile-facts${purpose ? `?purpose=${purpose}` : ''}`)
}

export const createProfileFact = (body: ProfileFactCreatePayload) =>
  call<ProfileFact>({ body, method: 'POST', path: '/api/biojob/profile-facts' })

export const setProfileFactStatus = (factId: string, status: FactStatus) =>
  call<ProfileFact>({
    body: { status },
    method: 'PATCH',
    path: `/api/biojob/profile-facts/${encodeURIComponent(factId)}`
  })

export const listProfileDocuments = () => itemList<ProfileDocument>('/api/biojob/profile-documents')
export const importProfileDocument = (filePath: string) =>
  call<ProfileDocument>({
    body: { file_path: filePath },
    method: 'POST',
    path: '/api/biojob/profile-documents/import'
  })

export const listResumeVersions = (jobId: string) =>
  itemList<ResumeVersion>(`/api/biojob/jobs/${encodeURIComponent(jobId)}/resumes`)
export const generateResume = (jobId: string) =>
  call<ResumeVersion>({
    body: {},
    method: 'POST',
    path: `/api/biojob/jobs/${encodeURIComponent(jobId)}/resumes`
  })

export const exportApplications = () =>
  call<ApplicationExport>({ body: {}, method: 'POST', path: '/api/biojob/exports/applications' })

export const listSources = () => itemList<BioJobSource>('/api/biojob/sources')
export const updateSource = (sourceId: string, body: { enabled?: boolean }) =>
  call<BioJobSource>({ body, method: 'PATCH', path: `/api/biojob/sources/${encodeURIComponent(sourceId)}` })
export const runSource = (sourceId: string) =>
  call<BioJobSourceRun>({ body: {}, method: 'POST', path: `/api/biojob/sources/${encodeURIComponent(sourceId)}/run` })

export function listSourceRuns(sourceId?: string) {
  // URLSearchParams stringification is intentional: spaces use '+', matching the bridge tests and browser semantics.
  const suffix = sourceId ? `?${new URLSearchParams({ source_id: sourceId }).toString()}` : ''

  return itemList<BioJobSourceRun>(`/api/biojob/source-runs${suffix}`)
}
