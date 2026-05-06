/**
 * Maps SSE event_type strings (emitted by Phase 0–6 services) to TanStack
 * Query keys to invalidate.
 *
 * Verified against grep on `emit(...)` calls in:
 *   - services/scanner/cycle.py
 *   - services/orchestrator/process_candidate.py
 *   - services/evaluator/{evaluate.py, queue.py, poller.py}
 *   - services/monitor/cycle.py
 *   - services/api/routers/{auth,candidates,settings,system,prompts}.py
 *   - services/data/{watchlist,calendar,...}.py
 */
import { queryKeys } from '@/lib/api/query-keys'

type QueryKey = readonly unknown[]

export const EVENT_TO_QUERIES: Record<string, readonly QueryKey[]> = {
  // ---- Scanner ----
  scan_cycle_complete: [queryKeys.candidates.all, queryKeys.dashboard.summary],
  shortlist_empty_no_fire: [queryKeys.dashboard.summary],

  // ---- Evaluator ----
  candidate_evaluated: [
    queryKeys.candidates.all,
    queryKeys.evaluations.llm,
    queryKeys.dashboard.summary,
  ],
  fallback_evaluated: [queryKeys.candidates.all, queryKeys.evaluations.llm],
  queued: [queryKeys.system.status],
  rehydrated: [queryKeys.system.status],

  // ---- Monitor ----
  monitor_cycle_complete: [
    queryKeys.positions.all,
    queryKeys.evaluations.monitor,
    queryKeys.dashboard.activeTrades,
    queryKeys.dashboard.summary,
  ],

  // ---- API mutations ----
  candidate_approved: [queryKeys.candidates.all, queryKeys.dashboard.summary],
  candidate_rejected: [queryKeys.candidates.all, queryKeys.dashboard.summary],
  settings_updated: [queryKeys.settings.all],
  system_toggle: [queryKeys.system.status, queryKeys.dashboard.summary],
  prompt_version_created: [queryKeys.prompts.all],
  prompt_version_activated: [queryKeys.prompts.all],
  prompt_version_rollback: [queryKeys.prompts.all],

  // ---- Data ----
  watchlist_set: [queryKeys.watchlist.all, queryKeys.dashboard.morningView],
  watchlist_carried_forward: [queryKeys.watchlist.all],
  watchlist_ticker_added: [queryKeys.watchlist.all],
  watchlist_ticker_removed: [queryKeys.watchlist.all],
  universe_changed: [queryKeys.universe.all],
  calendar_refreshed: [queryKeys.dashboard.morningView],

  // ---- Credentials (Phase 8a) ----
  credentials_updated: [queryKeys.credentials.all],
  credentials_deleted: [queryKeys.credentials.all],
  env_credential_migrated: [queryKeys.credentials.all],
}

export interface SseEventEnvelope {
  id: number
  service: string
  level: string
  event_type: string
  payload: Record<string, unknown>
  timestamp: number
}
