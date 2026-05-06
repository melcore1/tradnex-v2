import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PnlBadge } from '@/components/shared/PnlBadge'

describe('PnlBadge', () => {
  it('renders an em dash for null', () => {
    render(<PnlBadge pct={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders positive pct with + sign', () => {
    render(<PnlBadge pct={0.05} />)
    expect(screen.getByText('+5.00%')).toBeInTheDocument()
  })

  it('renders negative pct without forced sign (already has -)', () => {
    render(<PnlBadge pct={-0.1} />)
    expect(screen.getByText('-10.00%')).toBeInTheDocument()
  })
})
