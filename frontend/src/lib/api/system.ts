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

export const systemApi = {
  status: () => apiFetch<SystemStatusResponse>('/api/system/status'),
  toggle: (req: ToggleRequest) =>
    apiFetch<SystemStatusResponse>('/api/system/toggle', {
      method: 'POST',
      body: req,
    }),
}
