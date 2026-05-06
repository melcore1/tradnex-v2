import { apiFetch } from './client'

export interface ScannerEvaluationParams {
  ticker?: string
  hours?: number
  limit?: number
}

export interface MonitorEvaluationParams {
  position_id?: number
  hours?: number
  limit?: number
}

export interface LlmEvaluationParams {
  candidate_id?: number
  hours?: number
  limit?: number
  fallback_only?: boolean
  decision?: string
}

export const evaluationsApi = {
  scanner: (params: ScannerEvaluationParams = {}) =>
    apiFetch<Record<string, unknown>[]>('/api/evaluations/scanner', { query: params }),
  monitor: (params: MonitorEvaluationParams = {}) =>
    apiFetch<Record<string, unknown>[]>('/api/evaluations/monitor', { query: params }),
  llm: (params: LlmEvaluationParams = {}) =>
    apiFetch<Record<string, unknown>[]>('/api/evaluations/llm', { query: params }),
}
