import { apiFetch } from './client'

export interface SchwabRefreshResponse {
  success: boolean
  expires_at: string | null
  refresh_token_expires_at: string | null
  refresh_token_rotated: boolean
  message: string
}

export const schwabOAuthApi = {
  /** Full URL of the auth-start endpoint. The browser navigates here directly
   *  (window.location) — apiFetch isn't used because we need a real redirect
   *  to Schwab, not a JSON response. */
  authStartUrl: (): string => {
    const base = process.env.NEXT_PUBLIC_API_BASE ?? ''
    return `${base}/api/schwab/oauth/auth/start`
  },
  refresh: () =>
    apiFetch<SchwabRefreshResponse>('/api/schwab/oauth/refresh', {
      method: 'POST',
    }),
  disconnect: () =>
    apiFetch<void>('/api/schwab/oauth/disconnect', { method: 'DELETE' }),
}
