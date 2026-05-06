'use client'

import { useQuery } from '@tanstack/react-query'
import { dashboardApi } from '@/lib/api/dashboard'
import { queryKeys } from '@/lib/api/query-keys'

export function useDashboardSummary() {
  return useQuery({
    queryKey: queryKeys.dashboard.summary,
    queryFn: dashboardApi.summary,
  })
}

export function useMorningView() {
  return useQuery({
    queryKey: queryKeys.dashboard.morningView,
    queryFn: dashboardApi.morningView,
  })
}

export function useActiveTrades() {
  return useQuery({
    queryKey: queryKeys.dashboard.activeTrades,
    queryFn: dashboardApi.activeTrades,
  })
}

export function useJournal(date?: string) {
  return useQuery({
    queryKey: queryKeys.dashboard.journal(date),
    queryFn: () => dashboardApi.journal(date),
  })
}
