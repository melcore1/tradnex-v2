import { apiFetch } from './client'

export interface UniverseResponse {
  tickers: string[]
}

export interface UniverseAddRequest {
  tickers: string[]
}

export const universeApi = {
  list: () => apiFetch<UniverseResponse>('/api/universe'),
  add: (req: UniverseAddRequest) =>
    apiFetch<UniverseResponse>('/api/universe', { method: 'POST', body: req }),
  remove: (ticker: string) =>
    apiFetch<UniverseResponse>(`/api/universe/${ticker}`, { method: 'DELETE' }),
}
