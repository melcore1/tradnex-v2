/**
 * Format a Decimal-as-string (FastAPI Decimal serialization) for display.
 * Returns "—" for null/undefined.
 */
export function fmtMoney(v: string | number | null | undefined, opts: { withSign?: boolean } = {}): string {
  if (v === null || v === undefined) return '—'
  const n = typeof v === 'number' ? v : Number(v)
  if (Number.isNaN(n)) return '—'
  const sign = opts.withSign && n > 0 ? '+' : ''
  return `${sign}$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function fmtPct(v: string | number | null | undefined, opts: { withSign?: boolean } = {}): string {
  if (v === null || v === undefined) return '—'
  const n = typeof v === 'number' ? v : Number(v)
  if (Number.isNaN(n)) return '—'
  const sign = opts.withSign && n > 0 ? '+' : ''
  return `${sign}${(n * 100).toFixed(2)}%`
}

export function fmtNumber(v: number | string | null | undefined, decimals = 2): string {
  if (v === null || v === undefined) return '—'
  const n = typeof v === 'number' ? v : Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}
