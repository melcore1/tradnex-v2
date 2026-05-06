'use client'

import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { EVENT_TO_QUERIES, type SseEventEnvelope } from './event-map'

/**
 * Subscribes to /api/events/stream and translates each event into
 * TanStack Query cache invalidations. Reconnects with exponential
 * backoff on connection error. EventSource auto-attaches Last-Event-ID
 * on reconnect; the API supports it.
 */
export function SseProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient()
  const cancelledRef = useRef(false)

  useEffect(() => {
    cancelledRef.current = false
    let es: EventSource | null = null
    let backoff = 2000

    function connect() {
      if (cancelledRef.current) return
      es = new EventSource('/api/events/stream', { withCredentials: true })

      es.onopen = () => {
        backoff = 2000
      }

      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data) as SseEventEnvelope
          const keys = EVENT_TO_QUERIES[ev.event_type] ?? []
          for (const key of keys) {
            void qc.invalidateQueries({ queryKey: key as readonly unknown[] })
          }
        } catch {
          // Malformed event — ignore. Backend sends valid JSON; this guard
          // is purely defensive against partial frames.
        }
      }

      es.onerror = () => {
        es?.close()
        es = null
        if (!cancelledRef.current) {
          setTimeout(connect, backoff)
          backoff = Math.min(backoff * 2, 30_000)
        }
      }
    }

    connect()

    return () => {
      cancelledRef.current = true
      es?.close()
    }
  }, [qc])

  return <>{children}</>
}
