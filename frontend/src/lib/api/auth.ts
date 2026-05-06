import { apiFetch } from './client'

export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  user: string
  expires_at: string
}

export interface MeResponse {
  id: number
  email: string
  last_login_ts: string | null
}

export const authApi = {
  login: (req: LoginRequest) =>
    apiFetch<LoginResponse>('/api/auth/login', { method: 'POST', body: req }),
  logout: () =>
    apiFetch<{ status: string }>('/api/auth/logout', { method: 'POST' }),
  me: () => apiFetch<MeResponse>('/api/auth/me'),
}
