import { apiFetch } from './client'
import type { WatchlistResponse } from './watchlist'
import type { PositionSummary } from './positions'
import type { SystemStatusResponse } from './system'

export interface DashboardSummary {
  today_watchlist: WatchlistResponse | null
  open_positions_count: number
  open_positions_total_pnl: string | null
  pending_human_approvals: number
  pending_llm_evaluations: number
  recent_events: Record<string, unknown>[]
  system_status: SystemStatusResponse
}

export interface MorningView {
  yesterday_results: Record<string, unknown>
  today_watchlist: WatchlistResponse | null
  universe: string[]
  upcoming_calendar: Record<string, unknown>[]
  pre_market_gaps: Record<string, unknown>[]
}

export interface ActiveTrade {
  position: PositionSummary
  latest_monitor_evaluation: Record<string, unknown> | null
  pending_exit_candidate_id: number | null
}

export interface JournalEntry {
  date: string
  scanner_cycles_run: number
  candidates_fired: number
  decisions: Record<string, number>
  position_state_changes: Record<string, unknown>[]
  pnl_dollars: string | null
}

export const dashboardApi = {
  summary: () => apiFetch<DashboardSummary>('/api/dashboard/summary'),
  morningView: () => apiFetch<MorningView>('/api/dashboard/morning-view'),
  activeTrades: () => apiFetch<ActiveTrade[]>('/api/dashboard/active-trades'),
  journal: (date?: string) =>
    apiFetch<JournalEntry>('/api/dashboard/journal', {
      query: date ? { date } : {},
    }),
}
