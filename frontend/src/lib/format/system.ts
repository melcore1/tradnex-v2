import type { SystemStatusResponse } from '@/lib/api/system'

export interface SystemDisplay {
  scanner: { enabled: boolean; override: string | null }
  monitor: { enabled: boolean; override: string | null }
  llm: { enabled: boolean; override: string | null }
  mode: 'paper' | 'live'
}

/**
 * Maps the API's storage-flavored fields (`paused`, `monitor_paused`) to
 * UI-friendly enabled flags. Toggles in the UI represent "running" — the
 * API stores "paused".
 */
export function deriveSystemDisplay(s: SystemStatusResponse): SystemDisplay {
  return {
    scanner: {
      enabled: !s.paused,
      override: s.override_reasons?.scanner ?? null,
    },
    monitor: {
      enabled: !s.monitor_paused,
      override: s.override_reasons?.monitor ?? null,
    },
    llm: {
      enabled: s.llm_enabled,
      override: s.override_reasons?.llm ?? null,
    },
    mode: s.trading_mode,
  }
}
