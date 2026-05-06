import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SystemStatusPanel } from '@/components/system/SystemStatusPanel'
import type { SystemStatusResponse } from '@/lib/api/system'

const baseStatus: SystemStatusResponse = {
  paused: false,
  monitor_paused: false,
  llm_enabled: true,
  queue_depth: 0,
  queue_in_flight: 0,
  open_positions: 0,
  pending_human_approvals: 0,
  trading_mode: 'paper',
  override_reasons: { scanner: null, monitor: null, llm: null },
}

describe('SystemStatusPanel', () => {
  it('shows scanner/monitor/llm states', () => {
    render(<SystemStatusPanel status={baseStatus} />)
    const onBadges = screen.getAllByText('ON')
    expect(onBadges.length).toBe(3)
  })

  it('renders override message when present', () => {
    render(
      <SystemStatusPanel
        status={{
          ...baseStatus,
          monitor_paused: true,
          open_positions: 1,
          override_reasons: {
            scanner: null,
            monitor: 'Monitor forced active — 1 open position',
            llm: null,
          },
        }}
      />,
    )
    expect(screen.getByText(/Monitor forced active/i)).toBeInTheDocument()
  })

  it('shows PAPER mode badge', () => {
    render(<SystemStatusPanel status={baseStatus} />)
    expect(screen.getByText('[PAPER]')).toBeInTheDocument()
  })
})
