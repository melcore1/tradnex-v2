import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SchwabCredentialCard } from '@/components/credentials/SchwabCredentialCard'
import type { CredentialRecord } from '@/lib/api/credentials'

vi.mock('@/components/ui/sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}))

function renderWithClient(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

function makeRecord(
  type: CredentialRecord['credential_type'],
  overrides: Partial<CredentialRecord> = {},
): CredentialRecord {
  return {
    credential_type: type,
    is_configured: true,
    expires_at: null,
    refresh_token_expires_at: null,
    last_used_ts: null,
    created_ts: '2026-05-01T00:00:00Z',
    updated_ts: '2026-05-12T00:00:00Z',
    notes: null,
    ...overrides,
  }
}

describe('SchwabCredentialCard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the client-credentials form when no client record exists', () => {
    renderWithClient(
      <SchwabCredentialCard
        clientRecord={undefined}
        oauthRecord={undefined}
      />,
    )
    // CredentialEditor renders the "Not configured" badge for schwab_client.
    expect(screen.getByText(/Connect your account/i)).toBeInTheDocument()
    expect(screen.getByText(/Not configured/)).toBeInTheDocument()
  })

  it('renders the Connect Schwab button when client creds saved but no OAuth', () => {
    renderWithClient(
      <SchwabCredentialCard
        clientRecord={makeRecord('schwab_client')}
        oauthRecord={undefined}
      />,
    )
    expect(screen.getByTestId('schwab-card-ready')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Connect Schwab/i }),
    ).toBeInTheDocument()
  })

  it('renders connected state with token expirations + refresh/disconnect buttons', () => {
    const farFuture = new Date(Date.now() + 6 * 24 * 60 * 60 * 1000).toISOString()
    renderWithClient(
      <SchwabCredentialCard
        clientRecord={makeRecord('schwab_client')}
        oauthRecord={makeRecord('schwab_oauth', {
          refresh_token_expires_at: farFuture,
          expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
        })}
      />,
    )
    expect(screen.getByTestId('schwab-card-connected')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Refresh now/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Disconnect/i }),
    ).toBeInTheDocument()
  })

  it('renders expiring banner when refresh window is < 24h', () => {
    const soon = new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString() // 6h
    renderWithClient(
      <SchwabCredentialCard
        clientRecord={makeRecord('schwab_client')}
        oauthRecord={makeRecord('schwab_oauth', {
          refresh_token_expires_at: soon,
        })}
      />,
    )
    expect(screen.getByTestId('schwab-card-expiring')).toBeInTheDocument()
    expect(screen.getByText(/Refresh window expiring/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Re-authenticate/i }),
    ).toBeInTheDocument()
  })
})
