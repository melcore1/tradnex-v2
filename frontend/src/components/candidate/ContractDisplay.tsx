import { RawJsonToggle } from '@/components/shared/RawJsonToggle'

interface ContractDisplayProps {
  contract: Record<string, unknown> | null | undefined
}

export function ContractDisplay({ contract }: ContractDisplayProps) {
  if (!contract) return <p className="text-sm text-muted-foreground">No contract selected.</p>

  const sym = (contract.symbol as string) ?? '—'
  const strike = contract.strike as number | string | null
  const exp = (contract.expiration as string) ?? null
  const right = (contract.right as string) ?? null
  const bid = contract.bid as number | string | null
  const ask = contract.ask as number | string | null
  const delta = contract.delta as number | string | null

  const formatted = (
    <dl className="grid grid-cols-2 gap-2 text-sm">
      <div>
        <dt className="text-xs text-muted-foreground">Symbol</dt>
        <dd className="font-mono">{sym}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Strike / right</dt>
        <dd>
          {strike ?? '—'} {right ?? ''}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Expiration</dt>
        <dd>{exp ?? '—'}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Bid / Ask</dt>
        <dd>
          {bid ?? '—'} / {ask ?? '—'}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Δ delta</dt>
        <dd>{delta ?? '—'}</dd>
      </div>
    </dl>
  )

  return <RawJsonToggle formatted={formatted} raw={contract} />
}
