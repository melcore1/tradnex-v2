import { apiFetch } from './client'

export interface SettingsResponse {
  settings_json: Record<string, unknown>
}

export interface SettingsUpdateRequest {
  updates: Record<string, unknown>
}

export const settingsApi = {
  get: () => apiFetch<SettingsResponse>('/api/settings'),
  patch: (req: SettingsUpdateRequest) =>
    apiFetch<SettingsResponse>('/api/settings', { method: 'PATCH', body: req }),
}
