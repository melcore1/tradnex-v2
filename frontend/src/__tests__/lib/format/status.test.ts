import { describe, it, expect } from 'vitest'
import { describeStatus, describeConfidence } from '@/lib/format/status'

describe('describeStatus', () => {
  it('returns labels for known candidate statuses', () => {
    expect(describeStatus('approved')).toEqual({ label: 'Approved', tone: 'success' })
    expect(describeStatus('pending_human_approval').tone).toBe('pending')
    expect(describeStatus('rejected_by_llm').tone).toBe('destructive')
  })

  it('falls back to neutral for unknown', () => {
    const r = describeStatus('mystery_state')
    expect(r.label).toBe('mystery_state')
    expect(r.tone).toBe('neutral')
  })
})

describe('describeConfidence', () => {
  it('returns a tone per confidence level', () => {
    expect(describeConfidence('STRONG').tone).toBe('success')
    expect(describeConfidence('VETO').tone).toBe('destructive')
    expect(describeConfidence(null).label).toBe('—')
  })
})
