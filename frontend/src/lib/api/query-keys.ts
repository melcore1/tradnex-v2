/**
 * Central query-key factory. Keys must be readonly tuples so TanStack
 * Query treats them as stable. The SSE→invalidation map references
 * these directly.
 */

export const queryKeys = {
  auth: {
    all: ['auth'] as const,
    me: () => ['auth', 'me'] as const,
  },
  candidates: {
    all: ['candidates'] as const,
    list: (filters?: Record<string, unknown>) =>
      filters ? (['candidates', 'list', filters] as const) : (['candidates', 'list'] as const),
    detail: (id: number) => ['candidates', id, 'detail'] as const,
    fullContext: (id: number) => ['candidates', id, 'full-context'] as const,
  },
  positions: {
    all: ['positions'] as const,
    list: (filters?: Record<string, unknown>) =>
      filters ? (['positions', 'list', filters] as const) : (['positions', 'list'] as const),
    detail: (id: number) => ['positions', id, 'detail'] as const,
    lifecycle: (id: number) => ['positions', id, 'lifecycle'] as const,
  },
  evaluations: {
    all: ['evaluations'] as const,
    scanner: ['evaluations', 'scanner'] as const,
    monitor: ['evaluations', 'monitor'] as const,
    llm: ['evaluations', 'llm'] as const,
  },
  watchlist: {
    all: ['watchlist'] as const,
    today: ['watchlist', 'today'] as const,
    history: ['watchlist', 'history'] as const,
  },
  universe: {
    all: ['universe'] as const,
  },
  settings: {
    all: ['settings'] as const,
  },
  system: {
    all: ['system'] as const,
    status: ['system', 'status'] as const,
    dataStatus: ['system', 'data-status'] as const,
  },
  prompts: {
    all: ['prompts'] as const,
    active: (template: string) => ['prompts', template, 'active'] as const,
    history: (template: string) => ['prompts', template, 'history'] as const,
  },
  credentials: {
    all: ['credentials'] as const,
    detail: (type: string) => ['credentials', type] as const,
  },
  dashboard: {
    all: ['dashboard'] as const,
    summary: ['dashboard', 'summary'] as const,
    morningView: ['dashboard', 'morning-view'] as const,
    activeTrades: ['dashboard', 'active-trades'] as const,
    journal: (date?: string) =>
      date ? (['dashboard', 'journal', date] as const) : (['dashboard', 'journal'] as const),
  },
} as const
