'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  credentialsApi,
  type CredentialType,
  type UpsertCredentialBody,
} from '@/lib/api/credentials'
import { queryKeys } from '@/lib/api/query-keys'
import { toast } from '@/components/ui/sonner'

export function useCredentials() {
  return useQuery({
    queryKey: queryKeys.credentials.all,
    queryFn: credentialsApi.list,
  })
}

export function useUpsertCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      type,
      body,
    }: {
      type: CredentialType
      body: UpsertCredentialBody
    }) => credentialsApi.upsert(type, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.credentials.all })
      toast.success('Credential saved')
    },
    onError: () => {
      toast.error('Save failed')
    },
  })
}

export function useDeleteCredential() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (type: CredentialType) => credentialsApi.delete(type),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.credentials.all })
      toast.success('Credential removed')
    },
    onError: () => {
      toast.error('Delete failed')
    },
  })
}
