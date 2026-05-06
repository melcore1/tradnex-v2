'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { systemApi, type ToggleName } from '@/lib/api/system'
import { queryKeys } from '@/lib/api/query-keys'
import { toast } from '@/components/ui/sonner'

export function useSystemStatus() {
  return useQuery({
    queryKey: queryKeys.system.status,
    queryFn: systemApi.status,
  })
}

/**
 * Toggle wrapper. UI semantics: `enabled=true` means "running".
 * For paused/monitor_paused, the API stores the negation; for
 * llm_enabled it's passed through.
 */
export function useToggle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, enabled }: { name: ToggleName; enabled: boolean }) =>
      systemApi.toggle({ name, enabled }),
    onSuccess: (data, vars) => {
      qc.setQueryData(queryKeys.system.status, data)
      qc.invalidateQueries({ queryKey: queryKeys.dashboard.summary })
      toast.success(`${vars.name} updated`)
    },
    onError: () => {
      toast.error('Toggle failed')
    },
  })
}
