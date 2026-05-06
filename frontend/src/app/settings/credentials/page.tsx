'use client'

import { CredentialEditor } from '@/components/credentials/CredentialEditor'
import { useCredentials } from '@/hooks/useCredentials'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { CredentialRecord, CredentialType } from '@/lib/api/credentials'

const ALPACA_FIELDS = [
  { name: 'api_key', label: 'API key', type: 'text' as const },
  { name: 'api_secret', label: 'API secret', type: 'password' as const },
]

const SINGLE_KEY_FIELDS = [
  { name: 'api_key', label: 'API key', type: 'password' as const },
]

export default function CredentialsSettingsPage() {
  const { data, isLoading, error } = useCredentials()

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>
  if (error || !data) return <p className="text-sm text-destructive">Failed to load credentials.</p>

  const recordOf = (type: CredentialType): CredentialRecord | undefined =>
    data.find((c) => c.credential_type === type)

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Encryption</CardTitle>
          <CardDescription>
            All credentials below are encrypted at rest with the master key
            in <code>ENCRYPTION_KEY</code>. The key itself never leaves your
            <code>.env</code> file. Generate one via{' '}
            <code>python -m services.api.cli generate-encryption-key</code>.
          </CardDescription>
        </CardHeader>
      </Card>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Trading</h2>
        <CredentialEditor
          type="alpaca_paper"
          title="Alpaca — Paper"
          description="Paper-trading API keys. Used for risk-free order simulation."
          fields={ALPACA_FIELDS}
          record={recordOf('alpaca_paper')}
        />
        <CredentialEditor
          type="alpaca_live"
          title="Alpaca — Live"
          description="Real-money trading. Stored encrypted, never echoed."
          warning="REAL MONEY. Only enable after extensive paper testing."
          fields={ALPACA_FIELDS}
          record={recordOf('alpaca_live')}
        />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Market data — Schwab</h2>
        <CredentialEditor
          type="schwab_oauth"
          title="Schwab"
          description="OAuth flow handled in a future phase."
          fields={[]}
          record={recordOf('schwab_oauth')}
          disabled
          disabledMessage="Pending Schwab API approval. The OAuth flow lands in a later phase; until then, market data uses the mock client."
        />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">External APIs</h2>
        <CredentialEditor
          type="finnhub"
          title="Finnhub"
          description="Calendar feed (earnings, FOMC, CPI). Falls back to a deterministic mock when not configured."
          fields={SINGLE_KEY_FIELDS}
          record={recordOf('finnhub')}
        />
        <CredentialEditor
          type="exa"
          title="Exa"
          description="News context for the LLM evaluator. Falls back to a deterministic mock when not configured."
          fields={SINGLE_KEY_FIELDS}
          record={recordOf('exa')}
        />
      </section>
    </div>
  )
}
