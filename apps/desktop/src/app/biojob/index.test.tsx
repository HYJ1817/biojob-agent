import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '@/i18n'

import * as api from './api'

import { BioJobWorkbench } from './index'

vi.mock('./api', () => ({
  createProfileFact: vi.fn(),
  decideCandidate: vi.fn(),
  exportApplications: vi.fn(),
  generateResume: vi.fn(),
  getBioJobDashboard: vi.fn(),
  getJobMatch: vi.fn(),
  importCandidate: vi.fn(),
  importProfileDocument: vi.fn(),
  listCandidates: vi.fn(),
  listJobs: vi.fn(),
  listProfileFacts: vi.fn(),
  listProfileDocuments: vi.fn(),
  listResumeVersions: vi.fn(),
  listSourceRuns: vi.fn(),
  listSources: vi.fn(),
  patchJob: vi.fn(),
  runJobMatch: vi.fn(),
  runEnabledSources: vi.fn(),
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
  needs_verification: false,
  title: '生物工艺工程师'
}

function renderWorkbench(locale = 'zh') {
  return render(
    <MemoryRouter initialEntries={['/biojob']}>
      <I18nProvider configClient={null} initialLocale={locale as never}>
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
    vi.mocked(api.exportApplications).mockResolvedValue({ file_path: 'C:\\BioJob\\投递表.xlsx' } as never)
    vi.mocked(api.generateResume).mockResolvedValue({ file_path: 'C:\\BioJob\\简历.docx' } as never)
    vi.mocked(api.importProfileDocument).mockResolvedValue({ fact_count: 2 } as never)
    vi.mocked(api.runEnabledSources).mockResolvedValue({
      runs: [],
      summary: {
        completed_sources: 9,
        failed_sources: 1,
        merged_results: 3,
        new_candidates: 6,
        pending_verification: 8
      }
    } as never)
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

  it('groups automatic discovery and official portals and summarizes run all', async () => {
    vi.mocked(api.listSources).mockResolvedValue([
      {
        adapter_type: 'search_feed',
        config: { query_label: '山东', url: 'https://www.bing.com/search?format=rss&q=test' },
        created_at: '2026-08-13T00:00:00Z',
        description: '山东岗位发现',
        enabled: true,
        health_status: 'healthy',
        id: 'search-shandong',
        last_checked_at: null,
        name: '山东生物医药岗位发现',
        updated_at: '2026-08-13T00:00:00Z'
      },
      {
        adapter_type: 'portal',
        config: { company_name: '齐鲁制药', url: 'https://www.qilu-pharma.com/position.html' },
        created_at: '2026-08-13T00:00:00Z',
        description: '官方招聘入口',
        enabled: false,
        health_status: 'unknown',
        id: 'default-qilu',
        last_checked_at: null,
        name: '齐鲁制药招聘',
        updated_at: '2026-08-13T00:00:00Z'
      }
    ] as never)
    renderWorkbench()
    fireEvent.click(await screen.findByRole('button', { name: '岗位来源' }))

    expect(await screen.findByRole('heading', { name: '自动发现来源' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '官方核验入口' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '打开招聘页' }).getAttribute('href')).toBe(
      'https://www.qilu-pharma.com/position.html'
    )

    fireEvent.click(screen.getByRole('button', { name: '运行全部启用来源' }))
    await waitFor(() => expect(api.runEnabledSources).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('新增 6')).toBeTruthy()
    expect(screen.getByText('合并重复 3')).toBeTruthy()
    expect(screen.getByText('待核验 8')).toBeTruthy()
    expect(screen.getByText('失败来源 1')).toBeTruthy()
  })

  it('marks public search candidates for original-page verification', async () => {
    vi.mocked(api.listCandidates).mockResolvedValue([{ ...candidate, needs_verification: true }] as never)
    renderWorkbench()
    fireEvent.click(await screen.findByRole('button', { name: '候选岗位' }))

    expect(await screen.findByText('待核验')).toBeTruthy()
    expect(screen.getByRole('link', { name: '打开原页面' }).getAttribute('href')).toBe(candidate.links.detail)
  })

  it('imports a base resume and reveals generated Word and Excel files', async () => {
    const preparingJob = {
      ...candidate,
      application: { status: 'preparing' },
      company: { name: 'RemeGen' }
    }

    vi.mocked(api.listJobs).mockResolvedValue([preparingJob] as never)
    Object.defineProperty(window, 'hermesDesktop', {
      configurable: true,
      value: {
        revealPath: vi.fn().mockResolvedValue(true),
        selectPaths: vi.fn().mockResolvedValue(['C:\\Users\\me\\base.docx'])
      }
    })
    renderWorkbench('en')

    fireEvent.click(await screen.findByRole('button', { name: 'Profile facts' }))
    fireEvent.click(screen.getByRole('button', { name: 'Import base resume' }))
    await waitFor(() => expect(api.importProfileDocument).toHaveBeenCalledWith('C:\\Users\\me\\base.docx'))

    fireEvent.click(screen.getByRole('button', { name: 'Applications' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Generate Word resume' }))
    await waitFor(() => expect(api.generateResume).toHaveBeenCalledWith('job-1'))
    await waitFor(() => expect(window.hermesDesktop?.revealPath).toHaveBeenCalledWith('C:\\BioJob\\简历.docx'))

    fireEvent.click(screen.getByRole('button', { name: 'Export Excel tracker' }))
    await waitFor(() => expect(api.exportApplications).toHaveBeenCalled())
    await waitFor(() => expect(window.hermesDesktop?.revealPath).toHaveBeenCalledWith('C:\\BioJob\\投递表.xlsx'))
  })
})
