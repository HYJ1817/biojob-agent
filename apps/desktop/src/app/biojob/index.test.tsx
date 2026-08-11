import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'

import * as api from './api'

import { BioJobWorkbench } from './index'

vi.mock('./api', () => ({
  createProfileFact: vi.fn(),
  decideCandidate: vi.fn(),
  getBioJobDashboard: vi.fn(),
  getJobMatch: vi.fn(),
  importCandidate: vi.fn(),
  listCandidates: vi.fn(),
  listJobs: vi.fn(),
  listProfileFacts: vi.fn(),
  listSourceRuns: vi.fn(),
  listSources: vi.fn(),
  patchJob: vi.fn(),
  runJobMatch: vi.fn(),
  runSource: vi.fn(),
  setProfileFactStatus: vi.fn(),
  updateSource: vi.fn()
}))

const candidate = {
  application: null,
  city: '济南',
  company: { name: '齐鲁制药' },
  decision: 'pending',
  id: 'job-1',
  jd_text: '负责细胞培养和GMP记录',
  links: {
    apply: 'https://jobs.example.test/apply/1',
    careers: 'https://jobs.example.test',
    detail: 'https://jobs.example.test/1'
  },
  match: { recommendation: '建议查看', score: 72 },
  title: '生物工艺工程师'
}

function renderWorkbench() {
  return render(
    <MemoryRouter initialEntries={['/biojob']}>
      <I18nProvider configClient={null} initialLocale="zh">
        <BioJobWorkbench />
      </I18nProvider>
    </MemoryRouter>
  )
}

describe('BioJob workbench', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getBioJobDashboard).mockResolvedValue({
      application_counts: { considering: 2, preparing: 1 },
      candidate_counts: { pending: 3 },
      source_counts: { degraded: 0, enabled: 5, failed: 0, healthy: 4, total: 6 }
    } as never)
    vi.mocked(api.listCandidates).mockResolvedValue([candidate] as never)
    vi.mocked(api.listJobs).mockResolvedValue([])
    vi.mocked(api.listProfileFacts).mockResolvedValue([])
    vi.mocked(api.listSources).mockResolvedValue([])
    vi.mocked(api.decideCandidate).mockResolvedValue({ ...candidate, decision: 'kept' } as never)
  })

  it('shows the real job workflow in the first viewport', async () => {
    renderWorkbench()

    expect(await screen.findByRole('heading', { name: '秋招工作台' })).toBeTruthy()
    expect(screen.getByText('3')).toBeTruthy()
    expect(screen.getByText('待复核岗位')).toBeTruthy()
    expect(screen.getByRole('button', { name: '候选岗位' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'AI 设置' })).toBeTruthy()
  })

  it('reviews a candidate with clickable source links and authoritative refresh', async () => {
    vi.mocked(api.listCandidates)
      .mockResolvedValueOnce([candidate] as never)
      .mockResolvedValueOnce([])
    renderWorkbench()
    fireEvent.click(await screen.findByRole('button', { name: '候选岗位' }))

    expect(await screen.findByText('生物工艺工程师')).toBeTruthy()
    expect(screen.getByRole('link', { name: '查看 JD' }).getAttribute('href')).toBe(candidate.links.detail)
    expect(screen.getByRole('link', { name: '立即申请' }).getAttribute('href')).toBe(candidate.links.apply)

    fireEvent.click(screen.getByRole('button', { name: '保留并进入投递表' }))
    await waitFor(() => expect(api.decideCandidate).toHaveBeenCalledWith('job-1', 'kept'))
    await waitFor(() => expect(api.listCandidates).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByText('生物工艺工程师')).toBeNull())
  })

  it('surfaces loading failures with a retry action', async () => {
    vi.mocked(api.getBioJobDashboard).mockRejectedValueOnce(new Error('offline'))
    renderWorkbench()

    expect(await screen.findByText('暂时无法读取求职数据')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByRole('heading', { name: '秋招工作台' })).toBeTruthy()
  })
})
