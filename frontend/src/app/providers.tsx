'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { useState } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { ApiError } from '@/lib/api/client'
import { SseProvider } from '@/lib/sse/SseProvider'

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            refetchOnWindowFocus: false,
            retry: (n, err) => {
              if (err instanceof ApiError && err.status === 401) return false
              return n < 2
            },
          },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <SseProvider>{children}</SseProvider>
      <Toaster />
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
