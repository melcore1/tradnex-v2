'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { settingsApi, type SettingsUpdateRequest } from '@/lib/api/settings'
import { queryKeys } from '@/lib/api/query-keys'
import { toast } from '@/components/ui/sonner'

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings.all,
    queryFn: settingsApi.get,
  })
}

export function usePatchSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: SettingsUpdateRequest) => settingsApi.patch(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings.all })
      toast.success('Settings saved')
    },
    onError: () => toast.error('Save failed'),
  })
}
