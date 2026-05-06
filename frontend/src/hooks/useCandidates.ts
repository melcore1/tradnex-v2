'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { candidatesApi, type ApproveRequest, type ListCandidatesParams, type RejectRequest } from '@/lib/api/candidates'
import { queryKeys } from '@/lib/api/query-keys'
import { ApiError } from '@/lib/api/client'
import { toast } from '@/components/ui/sonner'

export function useCandidates(params: ListCandidatesParams = {}) {
  return useQuery({
    queryKey: queryKeys.candidates.list(params as Record<string, unknown>),
    queryFn: () => candidatesApi.list(params),
  })
}

export function useCandidateDetail(id: number | null) {
  return useQuery({
    queryKey: id !== null ? queryKeys.candidates.detail(id) : ['candidates', 'noop'],
    queryFn: () => {
      if (id === null) throw new Error('id required')
      return candidatesApi.detail(id)
    },
    enabled: id !== null,
  })
}

export function useApprove() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ApproveRequest }) =>
      candidatesApi.approve(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.candidates.all })
      qc.invalidateQueries({ queryKey: queryKeys.dashboard.summary })
      toast.success('Approved')
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        toast.error('Cannot approve — wrong state')
      } else {
        toast.error('Approval failed')
      }
    },
  })
}

export function useReject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: RejectRequest }) =>
      candidatesApi.reject(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.candidates.all })
      qc.invalidateQueries({ queryKey: queryKeys.dashboard.summary })
      toast.success('Rejected')
    },
    onError: () => {
      toast.error('Rejection failed')
    },
  })
}
