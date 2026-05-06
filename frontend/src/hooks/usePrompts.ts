'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { promptsApi, type PromptCreateRequest, type PromptTemplateName } from '@/lib/api/prompts'
import { queryKeys } from '@/lib/api/query-keys'
import { toast } from '@/components/ui/sonner'

export function useActivePrompt(template: PromptTemplateName) {
  return useQuery({
    queryKey: queryKeys.prompts.active(template),
    queryFn: () => promptsApi.active(template),
  })
}

export function usePromptHistory(template: PromptTemplateName) {
  return useQuery({
    queryKey: queryKeys.prompts.history(template),
    queryFn: () => promptsApi.history(template),
  })
}

export function useCreatePrompt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (req: PromptCreateRequest) => promptsApi.create(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prompts.all })
      toast.success('Draft created')
    },
    onError: () => toast.error('Create failed'),
  })
}

export function useActivatePrompt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (version_id: number) => promptsApi.activate({ version_id }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prompts.all })
      toast.success('Activated')
    },
    onError: () => toast.error('Activation failed'),
  })
}

export function useRollbackPrompt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ template, version_number }: { template: PromptTemplateName; version_number: number }) =>
      promptsApi.rollback(template, version_number),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.prompts.all })
      toast.success('Rolled back')
    },
    onError: () => toast.error('Rollback failed'),
  })
}
