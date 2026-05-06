import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CredentialEditor } from '@/components/credentials/CredentialEditor'

vi.mock('@/components/ui/sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}))

function renderWithClient(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const FIELDS = [
  { name: 'api_key', label: 'API key', type: 'text' as const },
  { name: 'api_secret', label: 'API secret', type: 'password' as const },
]

describe('CredentialEditor', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows "Not configured" badge when record is undefined', () => {
    renderWithClient(
      <CredentialEditor
        type="alpaca_paper"
        title="Alpaca — Paper"
        fields={FIELDS}
        record={undefined}
      />,
    )
    expect(screen.getByText('Not configured')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /add/i })).toBeInTheDocument()
  })

  it('shows "Configured" badge when record exists', () => {
    renderWithClient(
      <CredentialEditor
        type="alpaca_paper"
        title="Alpaca — Paper"
        fields={FIELDS}
        record={{
          credential_type: 'alpaca_paper',
          is_configured: true,
          expires_at: null,
          refresh_token_expires_at: null,
          last_used_ts: null,
          created_ts: '2025-01-01T00:00:00Z',
          updated_ts: '2025-01-01T00:00:00Z',
          notes: null,
        }}
      />,
    )
    expect(screen.getByText('Configured')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /update/i })).toBeInTheDocument()
  })

  it('renders the disabled "Coming soon" state for Schwab placeholder', () => {
    renderWithClient(
      <CredentialEditor
        type="schwab_oauth"
        title="Schwab"
        fields={[]}
        record={undefined}
        disabled
        disabledMessage="Pending API approval"
      />,
    )
    expect(screen.getByText('Coming soon')).toBeInTheDocument()
    expect(screen.getByText('Pending API approval')).toBeInTheDocument()
    // No Add/Update button when disabled.
    expect(screen.queryByRole('button', { name: /add|update/i })).toBeNull()
  })

  it('opens dialog on Add and shows write-only fields', async () => {
    renderWithClient(
      <CredentialEditor
        type="finnhub"
        title="Finnhub"
        fields={[{ name: 'api_key', label: 'API key', type: 'password' as const }]}
        record={undefined}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: /add/i }))
    expect(screen.getByLabelText(/API key/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Notes/i)).toBeInTheDocument()
  })
})
