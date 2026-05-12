'use client'

import { CredentialEditor } from '@/components/credentials/CredentialEditor'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  useDisconnectSchwab,
  useRefreshSchwab,
  useStartSchwabAuth,
} from '@/hooks/useSchwabOAuth'
import type { CredentialRecord } from '@/lib/api/credentials'
import { fmtRelative } from '@/lib/format/datetime'

const SCHWAB_CLIENT_FIELDS = [
  { name: 'client_id', label: 'Client ID', type: 'text' as const },
  { name: 'client_secret', label: 'Client Secret', type: 'password' as const },
]

type SchwabState = 'no_client' | 'ready' | 'connected' | 'expiring'

function classifyState(
  clientRecord: CredentialRecord | undefined,
  oauthRecord: CredentialRecord | undefined,
): SchwabState {
  if (!clientRecord?.is_configured) return 'no_client'
  if (!oauthRecord?.is_configured) return 'ready'
  if (oauthRecord.refresh_token_expires_at) {
    const expiresAt = new Date(oauthRecord.refresh_token_expires_at).getTime()
    const hoursRemaining = (expiresAt - Date.now()) / (1000 * 60 * 60)
    if (hoursRemaining < 24) return 'expiring'
  }
  return 'connected'
}

interface SchwabCredentialCardProps {
  clientRecord: CredentialRecord | undefined
  oauthRecord: CredentialRecord | undefined
}

export function SchwabCredentialCard({
  clientRecord,
  oauthRecord,
}: SchwabCredentialCardProps) {
  const state = classifyState(clientRecord, oauthRecord)
  const startAuth = useStartSchwabAuth()
  const refresh = useRefreshSchwab()
  const disconnect = useDisconnectSchwab()

  if (state === 'no_client') {
    return (
      <CredentialEditor
        type="schwab_client"
        title="Schwab — Connect your account"
        description="Paste your Schwab Developer App's Client ID and Client Secret. The OAuth handshake runs after you save these."
        warning="Your Schwab app's callback URL must point at this server's /api/schwab/oauth/callback endpoint over HTTPS."
        fields={SCHWAB_CLIENT_FIELDS}
        record={clientRecord}
      />
    )
  }

  if (state === 'ready') {
    return (
      <Card data-testid="schwab-card-ready">
        <CardHeader>
          <div className="flex flex-row items-start justify-between gap-2">
            <div>
              <CardTitle className="flex items-center gap-2">
                Schwab
                <Badge variant="neutral">Ready to connect</Badge>
              </CardTitle>
              <CardDescription>
                Client credentials saved. Click below to authenticate with
                Schwab; you&apos;ll be redirected there to log in.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Button onClick={startAuth}>Connect Schwab</Button>
        </CardContent>
      </Card>
    )
  }

  const accessExpires = oauthRecord?.expires_at
    ? new Date(oauthRecord.expires_at).toLocaleString()
    : '—'
  const refreshExpires = oauthRecord?.refresh_token_expires_at
    ? new Date(oauthRecord.refresh_token_expires_at).toLocaleString()
    : '—'
  const lastUpdated = oauthRecord
    ? fmtRelative(oauthRecord.updated_ts)
    : '—'

  if (state === 'expiring') {
    return (
      <Card data-testid="schwab-card-expiring">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Schwab
            <Badge variant="warning">Refresh window expiring</Badge>
          </CardTitle>
          <CardDescription>
            Your Schwab refresh token expires soon ({refreshExpires}).
            Re-authenticate now to keep market data live — after expiration
            you&apos;ll need to start the OAuth flow from scratch.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Button onClick={startAuth}>Re-authenticate</Button>
          <Button
            variant="ghost"
            onClick={() => disconnect.mutate()}
            disabled={disconnect.isPending}
          >
            Disconnect
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card data-testid="schwab-card-connected">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Schwab
          <Badge variant="success">Connected</Badge>
        </CardTitle>
        <CardDescription>
          Market data flowing from Schwab. Access tokens auto-refresh every
          25 minutes; you only need to re-authenticate if the rolling 7-day
          refresh window lapses.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
          <div>
            <span className="text-muted-foreground">Access token valid until: </span>
            <span className="font-mono">{accessExpires}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Refresh token valid until: </span>
            <span className="font-mono">{refreshExpires}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Last refresh: </span>
            <span>{lastUpdated}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? 'Refreshing…' : 'Refresh now'}
          </Button>
          <Button
            variant="ghost"
            onClick={() => disconnect.mutate()}
            disabled={disconnect.isPending}
          >
            Disconnect
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
