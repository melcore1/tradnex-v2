import { describe, it, expect } from 'vitest'
import { deriveSystemDisplay } from '@/lib/format/system'
import type { SystemStatusResponse } from '@/lib/api/system'

const base: SystemStatusResponse = {
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

describe('deriveSystemDisplay', () => {
  it('maps fields with negation for paused flags', () => {
    const d = deriveSystemDisplay(base)
    expect(d.scanner.enabled).toBe(true)
    expect(d.monitor.enabled).toBe(true)
    expect(d.llm.enabled).toBe(true)
    expect(d.mode).toBe('paper')
  })

  it('reverses paused → enabled=false', () => {
    const d = deriveSystemDisplay({ ...base, paused: true, monitor_paused: true })
    expect(d.scanner.enabled).toBe(false)
    expect(d.monitor.enabled).toBe(false)
  })

  it('passes through llm_enabled directly', () => {
    const d = deriveSystemDisplay({ ...base, llm_enabled: false })
    expect(d.llm.enabled).toBe(false)
  })

  it('propagates override reasons', () => {
    const d = deriveSystemDisplay({
      ...base,
      override_reasons: { scanner: 'closed', monitor: 'open positions', llm: null },
    })
    expect(d.scanner.override).toBe('closed')
    expect(d.monitor.override).toBe('open positions')
    expect(d.llm.override).toBeNull()
  })
})
