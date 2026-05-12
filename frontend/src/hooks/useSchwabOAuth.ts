'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { schwabOAuthApi } from '@/lib/api/schwab'
import { systemApi } from '@/lib/api/system'
import { queryKeys } from '@/lib/api/query-keys'
import { toast } from '@/components/ui/sonner'

export function useDataStatus() {
  return useQuery({
    queryKey: queryKeys.system.dataStatus,
    queryFn: systemApi.dataStatus,
  })
}

export function useStartSchwabAuth() {
  return () => {
    window.location.href = schwabOAuthApi.authStartUrl()
  }
}

export function useRefreshSchwab() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: schwabOAuthApi.refresh,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.credentials.all })
      qc.invalidateQueries({ queryKey: queryKeys.system.dataStatus })
      toast.success('Schwab tokens refreshed')
    },
    onError: () => {
      toast.error('Schwab refresh failed')
    },
  })
}

export function useDisconnectSchwab() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: schwabOAuthApi.disconnect,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.credentials.all })
      qc.invalidateQueries({ queryKey: queryKeys.system.dataStatus })
      toast.success('Schwab disconnected')
    },
    onError: () => {
      toast.error('Disconnect failed')
    },
  })
}
