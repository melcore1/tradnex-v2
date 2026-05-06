import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiFetch, ApiError } from '@/lib/api/client'

describe('apiFetch', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('sends credentials and JSON content-type', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    await apiFetch('/api/test')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(init.credentials).toBe('include')
    const headers = init.headers as Record<string, string>
    expect(headers['Content-Type']).toBe('application/json')
  })

  it('throws ApiError on non-2xx, capturing status and body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'nope' }), { status: 401 }),
    )
    await expect(apiFetch('/api/test')).rejects.toMatchObject({
      status: 401,
      body: { detail: 'nope' },
    })
    await expect(apiFetch('/api/test')).rejects.toBeInstanceOf(ApiError)
  })

  it('parses JSON body on 2xx', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ x: 42 }), { status: 200 }),
    )
    const out = await apiFetch<{ x: number }>('/api/test')
    expect(out.x).toBe(42)
  })

  it('does not crash on non-JSON 500 body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('plaintext oops', { status: 500 }),
    )
    await expect(apiFetch('/api/test')).rejects.toMatchObject({ status: 500 })
  })
})
