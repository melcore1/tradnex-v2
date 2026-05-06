'use client'

import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { LogOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ModeBadge } from '@/components/shared/ModeBadge'
import { authApi } from '@/lib/api/auth'
import { systemApi } from '@/lib/api/system'
import { queryKeys } from '@/lib/api/query-keys'
import { deriveSystemDisplay } from '@/lib/format/system'
import { useRouter } from 'next/navigation'

export function Header() {
  const router = useRouter()
  const qc = useQueryClient()

  const { data: me } = useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: authApi.me,
    retry: false,
  })

  const { data: status } = useQuery({
    queryKey: queryKeys.system.status,
    queryFn: systemApi.status,
  })

  const display = status ? deriveSystemDisplay(status) : null

  const logout = useMutation({
    mutationFn: authApi.logout,
    onSettled: () => {
      qc.clear()
      router.push('/login')
    },
  })

  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
      <div className="flex h-14 items-center gap-4 px-4 lg:px-6">
        <Link href="/" className="text-base font-semibold tracking-tight">
          TradNex
        </Link>
        {display ? (
          <div className="hidden items-center gap-3 md:flex">
            <MiniToggle label="S" enabled={display.scanner.enabled} title="Scanner" />
            <MiniToggle label="M" enabled={display.monitor.enabled} title="Monitor" />
            <MiniToggle label="L" enabled={display.llm.enabled} title="LLM" />
            <ModeBadge mode={display.mode} />
          </div>
        ) : null}
        <div className="ml-auto flex items-center gap-3">
          {me ? (
            <span className="hidden text-xs text-muted-foreground md:inline">{me.email}</span>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
            aria-label="Log out"
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Log out</span>
          </Button>
        </div>
      </div>
    </header>
  )
}

function MiniToggle({ label, enabled, title }: { label: string; enabled: boolean; title: string }) {
  return (
    <Badge variant={enabled ? 'success' : 'destructive'} title={title}>
      {label}
    </Badge>
  )
}
