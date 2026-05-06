/**
 * Single API client used by every frontend hook + page.
 *
 * - Always sends cookies (session auth).
 * - Uses relative URLs by default (same-origin via Caddy in production).
 * - Switches to NEXT_PUBLIC_API_BASE for the host-dev flow.
 * - Wraps non-200 responses in ApiError so callers can branch on status.
 */

const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE ?? ''

export class ApiError extends Error {
  public readonly status: number
  public readonly body: unknown

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `API error ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export type QueryValue = string | number | boolean | undefined | null
export type QueryShape = { [key: string]: QueryValue }

export interface ApiFetchOptions extends Omit<RequestInit, 'body' | 'method'> {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown // serialized as JSON
  /** Query params. Accepts any object whose values are primitives; null/undefined are dropped. */
  query?: QueryShape | object
}

function buildUrl(path: string, query?: ApiFetchOptions['query']): string {
  const url = `${API_BASE}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query as Record<string, unknown>)) {
    if (v === undefined || v === null) continue
    params.set(k, String(v))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { body, method = 'GET', query, headers = {}, ...rest } = options
  const init: RequestInit = {
    method,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...headers,
    },
    ...rest,
  }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
  }
  const res = await fetch(buildUrl(path, query), init)
  if (!res.ok) {
    let parsed: unknown = null
    try {
      parsed = await res.json()
    } catch {
      // Non-JSON error body (rare; keep null)
    }
    throw new ApiError(res.status, parsed)
  }
  // 204 No Content
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
