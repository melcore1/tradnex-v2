import { describe, it, expect } from 'vitest'
import { EVENT_TO_QUERIES } from '@/lib/sse/event-map'

describe('EVENT_TO_QUERIES', () => {
  it('maps the events most relevant to UI screens', () => {
    expect(EVENT_TO_QUERIES['scan_cycle_complete']).toBeDefined()
    expect(EVENT_TO_QUERIES['monitor_cycle_complete']).toBeDefined()
    expect(EVENT_TO_QUERIES['candidate_evaluated']).toBeDefined()
    expect(EVENT_TO_QUERIES['candidate_approved']).toBeDefined()
    expect(EVENT_TO_QUERIES['system_toggle']).toBeDefined()
    expect(EVENT_TO_QUERIES['watchlist_set']).toBeDefined()
  })

  it('returns frozen-shape arrays of arrays', () => {
    for (const [, keys] of Object.entries(EVENT_TO_QUERIES)) {
      expect(Array.isArray(keys)).toBe(true)
      for (const k of keys) {
        expect(Array.isArray(k)).toBe(true)
        expect((k as readonly unknown[]).length).toBeGreaterThan(0)
      }
    }
  })

  it('returns undefined for unknown event types', () => {
    expect(EVENT_TO_QUERIES['no_such_event']).toBeUndefined()
  })
})
