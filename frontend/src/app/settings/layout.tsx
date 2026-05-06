'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const TABS = [
  { href: '/settings/system', label: 'System' },
  { href: '/settings/strategy', label: 'Strategy' },
  { href: '/settings/prompts', label: 'Prompts' },
  { href: '/settings/universe', label: 'Universe' },
] as const

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Settings</h1>
      <nav className="flex gap-1 border-b" aria-label="Settings sections">
        {TABS.map((t) => {
          const active = pathname.startsWith(t.href)
          return (
            <Link
              key={t.href}
              href={t.href}
              className={cn(
                'px-3 py-2 text-sm border-b-2 -mb-px transition-colors',
                active
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              {t.label}
            </Link>
          )
        })}
      </nav>
      <div>{children}</div>
    </div>
  )
}
