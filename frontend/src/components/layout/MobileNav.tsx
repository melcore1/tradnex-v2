'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { CheckSquare, Home, ListChecks, Menu, TrendingUp } from 'lucide-react'
import { cn } from '@/lib/utils'

const PRIMARY = [
  { href: '/', label: 'Home', icon: Home },
  { href: '/approvals', label: 'Approvals', icon: CheckSquare },
  { href: '/trades', label: 'Trades', icon: TrendingUp },
  { href: '/watchlist', label: 'Watch', icon: ListChecks },
  { href: '/settings/system', label: 'More', icon: Menu },
] as const

export function MobileNav({ className }: { className?: string }) {
  const pathname = usePathname()
  return (
    <nav
      className={cn(
        'fixed bottom-0 left-0 right-0 z-30 border-t bg-background/95 backdrop-blur',
        className,
      )}
      aria-label="Mobile navigation"
    >
      <ul className="flex">
        {PRIMARY.map(({ href, label, icon: Icon }) => {
          const active = href === '/' ? pathname === '/' : pathname.startsWith(href)
          return (
            <li key={href} className="flex-1">
              <Link
                href={href}
                className={cn(
                  'flex flex-col items-center justify-center gap-1 py-2 text-xs tap-target',
                  active ? 'text-primary' : 'text-muted-foreground',
                )}
              >
                <Icon className="h-5 w-5" aria-hidden />
                <span>{label}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
