export type ApplicationStatus =
  'considering' | 'preparing' | 'applied' | 'assessment' | 'interview' | 'offer' | 'rejected' | 'withdrawn' | 'expired'

export type CandidateDecision = 'pending' | 'kept' | 'ignored' | 'later' | 'error'
export type FactStatus = 'pending' | 'confirmed' | 'rejected' | 'conflicted'
export type FactVisibility = 'matching' | 'resume' | 'both' | 'private'

export interface BioJobLinks {
  apply: null | string
  careers: null | string
  detail: null | string
}

export interface BioJobApplication {
  applied_at: null | string
  created_at: string
  id: string
  job_id: string
  next_follow_up_at: null | string
  notes: string
  status: ApplicationStatus
  updated_at: string
}

export interface BioJobCompany {
  canonical_name: string
  city: null | string
  company_type: null | string
  id: string
  name: string
}

export interface BioJobMatchDimension {
  fact_evidence: string[]
  job_evidence: string[]
  key: string
  label: string
  score: number
  weight: number
}

export interface BioJobHardRule {
  blocked: boolean
  evidence: string
  message: string
  rule: string
}

export interface BioJobMatchReport {
  blocked: boolean
  confidence: 'high' | 'low' | 'medium'
  created_at: string
  dimensions: BioJobMatchDimension[]
  fact_ids: string[]
  gaps: string[]
  hard_gaps: string[]
  hard_rules: BioJobHardRule[]
  id: string
  job_id: string
  level: 'blocked' | 'cautious' | 'low' | 'priority' | 'suggested'
  model_name: null | string
  model_provider: null | string
  positive_terms: string[]
  recommendation: string
  risks: string[]
  rule_version: string
  score: number
}

export interface BioJobRecord {
  application: BioJobApplication
  apply_url: null | string
  careers_url: null | string
  city: null | string
  company: BioJobCompany
  created_at: string
  deadline_at: null | string
  detail_url: null | string
  direction: null | string
  education_requirement: null | string
  id: string
  jd_text: null | string
  lifecycle_status: 'closed' | 'open' | 'unknown'
  links: BioJobLinks
  major_requirement: null | string
  notes: string
  published_at: null | string
  recruitment_type: null | string
  title: string
  updated_at: string
}

export interface BioJobCandidate extends Omit<BioJobRecord, 'application'> {
  application: BioJobApplication | null
  decision: CandidateDecision
  match: {
    created_at: string
    evidence: Record<string, unknown>
    id: string
    model_name: null | string
    model_provider: null | string
    recommendation: string
    rule_version: string
    score: number
  }
  needs_verification: boolean
  snapshot_count: number
  source_count: number
}

export interface ProfileFact {
  category: string
  confirmed_at: null | string
  created_at: string
  fact_key: string
  id: string
  source_ref: null | string
  source_type: string
  status: FactStatus
  updated_at: string
  value: unknown
  visibility: FactVisibility
}

export interface BioJobSource {
  adapter_type: 'feed' | 'manual' | 'portal' | 'public_page' | 'search_feed'
  config: Record<string, unknown>
  created_at: string
  description: null | string
  enabled: boolean
  health_status: 'degraded' | 'failed' | 'healthy' | 'unknown'
  id: string
  last_checked_at: null | string
  name: string
  updated_at: string
}

export interface BioJobBatchRun {
  runs: BioJobSourceRun[]
  summary: {
    completed_sources: number
    failed_sources: number
    merged_results: number
    new_candidates: number
    pending_verification: number
  }
}

export interface BioJobSourceRun {
  error_summary: null | string
  finished_at: null | string
  id: string
  result_count: number
  source_adapter_type: string
  source_id: string
  source_name: string
  started_at: string
  status: 'cancelled' | 'completed' | 'failed' | 'running'
}

export interface BioJobDashboard {
  application_counts: Record<ApplicationStatus, number>
  candidate_counts: Record<CandidateDecision, number>
  source_counts: { degraded: number; enabled: number; failed: number; healthy: number; total: number }
}

export interface CandidateImportPayload {
  apply_url?: null | string
  careers_url?: null | string
  city?: null | string
  company_name: string
  deadline_at?: null | string
  detail_url: string
  external_id?: null | string
  jd_text?: null | string
  published_at?: null | string
  recruitment_type?: null | string
  title: string
}

export interface ProfileFactCreatePayload {
  category: string
  fact_key: string
  source_ref?: string
  source_type: string
  value: unknown
  visibility: FactVisibility
}

export interface ProfileDocument {
  created_at: string
  document_type: 'docx' | 'pdf'
  fact_count: number
  id: string
  local_path: string
  original_name: string
  sha256: string
}

export interface ResumeVersion {
  content_hash: string
  created_at: string
  fact_ids: string[]
  facts: Array<{ category: string; fact_key: string; id: string; value: unknown }>
  file_path: string
  id: string
  job_id: string
  template_name: string
}

export interface ApplicationExport {
  candidate_count: number
  created_at: string
  file_path: string
  id: string
  job_count: number
  sheet_names: string[]
}
