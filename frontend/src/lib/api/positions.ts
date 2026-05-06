import { apiFetch } from './client'

export interface PositionSummary {
  id: number
  ticker: string
  contract_symbol: string
  side: string
  quantity: number
  entry_price: string
  entry_ts: string
  status: string
  pnl: string | null
  pnl_pct: string | null
}

export interface PositionDetail {
  position: Record<string, unknown>
  lifecycle_events: Record<string, unknown>[]
  latest_monitor_evaluation: Record<string, unknown> | null
  pending_exit_candidate: Record<string, unknown> | null
}

export interface ListPositionsParams {
  status?: 'open' | 'closed' | 'all'
  limit?: number
}

export const positionsApi = {
  list: (params: ListPositionsParams = {}) =>
    apiFetch<PositionSummary[]>('/api/positions', { query: params }),
  detail: (id: number) => apiFetch<PositionDetail>(`/api/positions/${id}`),
  lifecycle: (id: number, limit = 50) =>
    apiFetch<Record<string, unknown>[]>(`/api/positions/${id}/lifecycle`, {
      query: { limit },
    }),
}
