import { apiFetch } from './client'

export interface WatchlistResponse {
  date: string
  tickers: string[]
  per_ticker_overrides: Record<string, Record<string, unknown>>
  notes: string | null
}

export interface WatchlistSetRequest {
  tickers: string[]
  per_ticker_overrides?: Record<string, Record<string, unknown>>
  notes?: string
  date?: string
}

export const watchlistApi = {
  today: () => apiFetch<WatchlistResponse>('/api/watchlist/today'),
  set: (req: WatchlistSetRequest) =>
    apiFetch<WatchlistResponse>('/api/watchlist', { method: 'PUT', body: req }),
  addTicker: (ticker: string) =>
    apiFetch<WatchlistResponse>(`/api/watchlist/tickers/${ticker}`, {
      method: 'POST',
    }),
  removeTicker: (ticker: string) =>
    apiFetch<WatchlistResponse>(`/api/watchlist/tickers/${ticker}`, {
      method: 'DELETE',
    }),
  history: (days = 7) =>
    apiFetch<WatchlistResponse[]>('/api/watchlist/history', { query: { days } }),
}
