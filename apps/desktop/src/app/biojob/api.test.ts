import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createProfileFact,
  decideCandidate,
  exportApplications,
  generateResume,
  getBioJobDashboard,
  getJobMatch,
  importCandidate,
  importProfileDocument,
  listCandidates,
  listJobs,
  listProfileDocuments,
  listProfileFacts,
  listResumeVersions,
  listSourceRuns,
  listSources,
  patchJob,
  runJobMatch,
  runSource,
  setProfileFactStatus,
  updateSource
} from './api'

describe('BioJob desktop API boundary', () => {
  let api: ReturnType<typeof vi.fn>

  beforeEach(() => {
    api = vi.fn().mockResolvedValue({ items: [] })
    Object.defineProperty(window, 'hermesDesktop', { configurable: true, value: { api } })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(window, 'hermesDesktop')
  })

  it('uses the profile-scoped authenticated read endpoints', async () => {
    await getBioJobDashboard()
    await listJobs()
    await listProfileFacts('matching')
    await listSources()
    await listSourceRuns('source 1')
    await getJobMatch('job 1')
    await listProfileDocuments()
    await listResumeVersions('job 1')

    expect(api.mock.calls.map(call => call[0].path)).toEqual([
      '/api/biojob/dashboard',
      '/api/biojob/jobs',
      '/api/biojob/profile-facts?purpose=matching',
      '/api/biojob/sources',
      '/api/biojob/source-runs?source_id=source+1',
      '/api/biojob/jobs/job%201/match',
      '/api/biojob/profile-documents',
      '/api/biojob/jobs/job%201/resumes'
    ])
  })

  it('encodes candidate filters and omits blank values', async () => {
    await listCandidates({ city: '济南', decision: 'later', direction: '', query: '细胞 培养' })

    expect(api).toHaveBeenCalledWith({
      path: '/api/biojob/candidates?decision=later&query=%E7%BB%86%E8%83%9E+%E5%9F%B9%E5%85%BB&city=%E6%B5%8E%E5%8D%97'
    })
  })

  it('sends strict mutation bodies and methods', async () => {
    const candidate = {
      company_name: '齐鲁制药',
      detail_url: 'https://example.test/job/1',
      title: '生物工艺工程师'
    }

    const fact = {
      category: 'skills',
      fact_key: 'cell-culture',
      source_type: 'user',
      value: '细胞培养',
      visibility: 'both' as const
    }

    await importCandidate(candidate)
    await decideCandidate('job 1', 'kept', '准备投递')
    await patchJob('job 1', { application_status: 'preparing', notes: '核对JD' })
    await runJobMatch('job 1')
    await createProfileFact(fact)
    await setProfileFactStatus('fact 1', 'confirmed')
    await updateSource('source 1', { enabled: false })
    await runSource('source 1')
    await importProfileDocument('C:\\Users\\me\\resume.docx')
    await generateResume('job 1')
    await exportApplications()

    expect(api.mock.calls.map(call => call[0])).toEqual([
      { body: candidate, method: 'POST', path: '/api/biojob/candidates/import' },
      {
        body: { decision: 'kept', note: '准备投递' },
        method: 'POST',
        path: '/api/biojob/candidates/job%201/decision'
      },
      {
        body: { application_status: 'preparing', notes: '核对JD' },
        method: 'PATCH',
        path: '/api/biojob/jobs/job%201'
      },
      { body: {}, method: 'POST', path: '/api/biojob/jobs/job%201/match' },
      { body: fact, method: 'POST', path: '/api/biojob/profile-facts' },
      {
        body: { status: 'confirmed' },
        method: 'PATCH',
        path: '/api/biojob/profile-facts/fact%201'
      },
      { body: { enabled: false }, method: 'PATCH', path: '/api/biojob/sources/source%201' },
      { body: {}, method: 'POST', path: '/api/biojob/sources/source%201/run' },
      {
        body: { file_path: 'C:\\Users\\me\\resume.docx' },
        method: 'POST',
        path: '/api/biojob/profile-documents/import'
      },
      { body: {}, method: 'POST', path: '/api/biojob/jobs/job%201/resumes' },
      { body: {}, method: 'POST', path: '/api/biojob/exports/applications' }
    ])
  })
})
