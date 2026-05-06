import { apiFetch } from './client'

export type CredentialType =
  | 'alpaca_paper'
  | 'alpaca_live'
  | 'schwab_oauth'
  | 'finnhub'
  | 'exa'

export interface CredentialRecord {
  credential_type: CredentialType
  is_configured: boolean
  expires_at: string | null
  refresh_token_expires_at: string | null
  last_used_ts: string | null
  created_ts: string
  updated_ts: string
  notes: string | null
}

export interface UpsertCredentialBody {
  secrets: Record<string, string>
  notes?: string
}

export const credentialsApi = {
  list: () => apiFetch<CredentialRecord[]>('/api/credentials'),
  get: (type: CredentialType) =>
    apiFetch<CredentialRecord>(`/api/credentials/${type}`),
  upsert: (type: CredentialType, body: UpsertCredentialBody) =>
    apiFetch<CredentialRecord>(`/api/credentials/${type}`, {
      method: 'PUT',
      body,
    }),
  delete: (type: CredentialType) =>
    apiFetch<void>(`/api/credentials/${type}`, { method: 'DELETE' }),
}
