import { apiFetch } from './client'

export type CandidateKind = 'entry' | 'exit'

export interface CandidateSummary {
  id: number
  candidate_kind: CandidateKind
  ticker: string
  direction: string
  status: string
  confidence: string | null
  created_ts: string
  summary_text: string
}

export interface CandidateDetail {
  candidate: Record<string, unknown>
  rule_trace: Record<string, unknown> | null
  veto_trace: Record<string, unknown> | null
  selected_contract: Record<string, unknown> | null
  llm_evaluation: Record<string, unknown> | null
  lifecycle_events: Record<string, unknown>[]
  copyable_text: string
}

export interface ListCandidatesParams {
  since_hours?: number
  limit?: number
  status?: string
  kind?: CandidateKind
}

export interface ApproveRequest {
  notes?: string
  quantity_override?: number
}

export interface RejectRequest {
  notes?: string
  reason?: string
}

export interface CandidateActionResponse {
  id: number
  new_status: string
  already_processed: boolean
}

export interface FullContextResponse {
  copyable_text: string
}

export const candidatesApi = {
  list: (params: ListCandidatesParams = {}) =>
    apiFetch<CandidateSummary[]>('/api/candidates', { query: params }),
  detail: (id: number) => apiFetch<CandidateDetail>(`/api/candidates/${id}`),
  fullContext: (id: number) =>
    apiFetch<FullContextResponse>(`/api/candidates/${id}/full-context`),
  approve: (id: number, body: ApproveRequest) =>
    apiFetch<CandidateActionResponse>(`/api/candidates/${id}/approve`, {
      method: 'POST',
      body,
    }),
  reject: (id: number, body: RejectRequest) =>
    apiFetch<CandidateActionResponse>(`/api/candidates/${id}/reject`, {
      method: 'POST',
      body,
    }),
}
