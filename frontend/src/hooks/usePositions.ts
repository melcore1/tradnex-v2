'use client'

import { useQuery } from '@tanstack/react-query'
import { positionsApi, type ListPositionsParams } from '@/lib/api/positions'
import { queryKeys } from '@/lib/api/query-keys'

export function usePositions(params: ListPositionsParams = {}) {
  return useQuery({
    queryKey: queryKeys.positions.list(params as Record<string, unknown>),
    queryFn: () => positionsApi.list(params),
  })
}

export function usePositionLifecycle(id: number) {
  return useQuery({
    queryKey: queryKeys.positions.lifecycle(id),
    queryFn: () => positionsApi.lifecycle(id),
  })
}
