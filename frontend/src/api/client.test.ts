import { beforeEach, describe, expect, it, vi } from 'vitest'

const getSession = vi.fn()
const refreshSession = vi.fn()
const signOut = vi.fn()

vi.mock('../lib/supabase', () => ({
  supabase: { auth: { getSession: () => getSession(), refreshSession: () => refreshSession() } },
}))

vi.mock('../stores/authStore', () => ({
  useAuthStore: {
    getState: () => ({
      token: 'stale-token',
      isBypassed: false,
      debugUserId: '',
      signOut,
    }),
  },
}))

const { apiClient, ApiError } = await import('./client')

/** Build a fetch Response stand-in with the given status and JSON body. */
function reply(status: number, body: unknown = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: String(status),
    json: async () => body,
  }
}

/** Read the Authorization header off a recorded fetch call. */
function sentToken(call: unknown[]): string | undefined {
  const init = call[1] as { headers: Record<string, string> }
  return init.headers.Authorization
}

describe('apiClient auth handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getSession.mockResolvedValue({ data: { session: { access_token: 'fresh-token' } }, error: null })
  })

  it('sends the token from getSession, never the stale store copy', async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await apiClient.get('/my-meals')

    expect(sentToken(fetchMock.mock.calls[0])).toBe('Bearer fresh-token')
    expect(sentToken(fetchMock.mock.calls[0])).not.toContain('stale-token')
  })

  it('refreshes and retries once when the API rejects the token', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(401, { detail: 'Invalid or expired token' }))
      .mockResolvedValueOnce(reply(201, { id: 'saved' }))
    vi.stubGlobal('fetch', fetchMock)
    refreshSession.mockResolvedValue({
      data: { session: { access_token: 'refreshed-token' } },
      error: null,
    })

    const result = await apiClient.post('/my-meals', { name: 'oats' })

    expect(refreshSession).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sentToken(fetchMock.mock.calls[1])).toBe('Bearer refreshed-token')
    expect(result).toEqual({ id: 'saved' })
    expect(signOut).not.toHaveBeenCalled()
  })

  it('signs out when the session cannot be recovered', async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(401, { detail: 'Invalid or expired token' }))
    vi.stubGlobal('fetch', fetchMock)
    refreshSession.mockResolvedValue({ data: { session: null }, error: { message: 'expired' } })

    await expect(apiClient.get('/goals')).rejects.toBeInstanceOf(ApiError)
    expect(signOut).toHaveBeenCalledOnce()
  })
})
