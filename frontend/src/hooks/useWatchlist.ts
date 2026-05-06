'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { watchlistApi, type WatchlistSetRequest } from '@/lib/api/watchlist'
import { universeApi } from '@/lib/api/universe'
import { queryKeys } from '@/lib/api/query-keys'
import { toast } from '@/components/ui/sonner'

export function useWatchlistToday() {
  return useQuery({
    queryKey: queryKeys.watchlist.today,
    queryFn: watchlistApi.today,
  })
}

export function useUniverse() {
  return useQuery({
    queryKey: queryKeys.universe.all,
    queryFn: universeApi.list,
  })
}

export function useSetWatchlist() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: WatchlistSetRequest) => watchlistApi.set(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.all })
      qc.invalidateQueries({ queryKey: queryKeys.dashboard.summary })
      qc.invalidateQueries({ queryKey: queryKeys.dashboard.morningView })
      toast.success('Watchlist updated')
    },
    onError: () => {
      toast.error('Watchlist update failed')
    },
  })
}

export function useAddUniverseTicker() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => universeApi.add({ tickers: [ticker.toUpperCase()] }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.universe.all })
      toast.success('Added to universe')
    },
    onError: () => {
      toast.error('Failed to add')
    },
  })
}

export function useRemoveUniverseTicker() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => universeApi.remove(ticker.toUpperCase()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.universe.all })
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.all })
      toast.success('Removed from universe')
    },
    onError: () => {
      toast.error('Failed to remove')
    },
  })
}
