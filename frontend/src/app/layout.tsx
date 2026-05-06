import type { Metadata } from 'next'
import './globals.css'
import { Providers } from './providers'
import { Header } from '@/components/layout/Header'
import { Sidebar } from '@/components/layout/Sidebar'
import { MobileNav } from '@/components/layout/MobileNav'

export const metadata: Metadata = {
  title: 'TradNex',
  description: 'Autonomous paper-options trading research',
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>
          <div className="flex min-h-screen flex-col">
            <Header />
            <div className="flex flex-1">
              <Sidebar className="hidden lg:block" />
              <main className="flex-1 px-4 py-4 pb-20 lg:px-6 lg:pb-6">{children}</main>
            </div>
            <MobileNav className="lg:hidden" />
          </div>
        </Providers>
      </body>
    </html>
  )
}
