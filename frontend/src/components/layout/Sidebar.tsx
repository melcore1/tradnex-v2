'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  BookOpen,
  CheckSquare,
  Home,
  Settings,
  TrendingUp,
  ListChecks,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '/', label: 'Dashboard', icon: Home },
  { href: '/approvals', label: 'Approvals', icon: CheckSquare },
  { href: '/trades', label: 'Active Trades', icon: TrendingUp },
  { href: '/watchlist', label: 'Watchlist', icon: ListChecks },
  { href: '/journal', label: 'Journal', icon: BookOpen },
  { href: '/settings/system', label: 'Settings', icon: Settings },
] as const

export function Sidebar({ className }: { className?: string }) {
  const pathname = usePathname()
  return (
    <aside className={cn('w-56 border-r bg-card', className)}>
      <nav className="flex flex-col gap-1 p-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === '/' ? pathname === '/' : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
                active
                  ? 'bg-accent text-accent-foreground'
                  : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground',
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
              <span>{label}</span>
            </Link>
          )
        })}
      </nav>
    </aside>
  )
}
