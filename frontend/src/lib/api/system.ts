import { apiFetch } from './client'

export interface SystemStatusResponse {
  paused: boolean
  monitor_paused: boolean
  llm_enabled: boolean
  queue_depth: number
  queue_in_flight: number
  open_positions: number
  pending_human_approvals: number
  trading_mode: 'paper' | 'live'
  override_reasons: Record<string, string | null>
}

export type ToggleName = 'paused' | 'monitor_paused' | 'llm_enabled'

export interface ToggleRequest {
  name: ToggleName
  enabled: boolean
}

export interface SchwabTokenStatus {
  access_expires_at: string | null
  refresh_expires_at: string | null
  refresh_token_hours_remaining: number | null
}

export interface DataStatus {
  active_client: 'mock' | 'schwab'
  is_configured: boolean
  schwab_oauth_enabled: boolean
  schwab_token_status: SchwabTokenStatus | null
  last_quote_ts: string | null
}

export const systemApi = {
  status: () => apiFetch<SystemStatusResponse>('/api/system/status'),
  toggle: (req: ToggleRequest) =>
    apiFetch<SystemStatusResponse>('/api/system/toggle', {
      method: 'POST',
      body: req,
    }),
  dataStatus: () => apiFetch<DataStatus>('/api/system/data-status'),
}
