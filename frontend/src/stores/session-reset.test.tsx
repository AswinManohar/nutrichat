import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'

const signOutMock = vi.fn()
let authListener: ((event: string, session: unknown) => void) | null = null

vi.mock('../lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: null } }),
      signOut: () => signOutMock(),
      onAuthStateChange: (cb: (event: string, session: unknown) => void) => {
        authListener = cb
        return { data: { subscription: { unsubscribe: vi.fn() } } }
      },
    },
  },
}))

const post = vi.fn()
vi.mock('../api/client', () => ({
  apiClient: { post: (...args: unknown[]) => post(...args), get: vi.fn() },
  ApiError: class ApiError extends Error {
    status = 500
  },
}))

const { queryClient } = await import('../api/queryClient')
const { useAuthStore } = await import('./authStore')
const { useMealStore } = await import('./mealStore')
const { ChatThread } = await import('../components/chat/ChatThread')

Element.prototype.scrollIntoView = vi.fn()

const item = {
  food_name: 'Apple',
  qty_g: 100,
  confidence: 0.9,
  kcal: 52,
  protein_g: 0.3,
  carbs_g: 14,
  fat_g: 0.2,
  fiber_g: 2.4,
  fdc_id: 1,
  candidates: [],
  source: 'USDA',
  estimated: false,
}

function seedUserState() {
  useMealStore.setState({
    messages: [
      {
        id: 'm1',
        sender: 'user',
        text: 'private meal of user A',
        timestamp: new Date().toISOString(),
      },
    ],
    conversationId: 'thread-1',
  })
  queryClient.setQueryData(['dashboard', 'today'], { kcal: 500 })
}

describe('session reset (#55)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authListener = null
    useMealStore.getState().resetChat()
    queryClient.clear()
    useAuthStore.setState({ user: { id: 'a', email: 'a@x.io' }, token: 't' })
  })
  afterEach(cleanup)

  it('signOut clears chat state and the query cache', async () => {
    seedUserState()
    await useAuthStore.getState().signOut()
    expect(useMealStore.getState().messages).toEqual([])
    expect(useMealStore.getState().conversationId).toBeNull()
    expect(queryClient.getQueryData(['dashboard', 'today'])).toBeUndefined()
    expect(useAuthStore.getState().user).toBeNull()
  })

  it('a session change to a different user clears state', async () => {
    await useAuthStore.getState().initialize()
    seedUserState()
    authListener!('SIGNED_IN', { user: { id: 'b', email: 'b@x.io' }, access_token: 'tb' })
    expect(useMealStore.getState().messages).toEqual([])
    expect(queryClient.getQueryData(['dashboard', 'today'])).toBeUndefined()
    expect(useAuthStore.getState().user?.id).toBe('b')
  })

  it('a token refresh for the same user keeps state', async () => {
    await useAuthStore.getState().initialize()
    seedUserState()
    authListener!('TOKEN_REFRESHED', { user: { id: 'a', email: 'a@x.io' }, access_token: 't2' })
    expect(useMealStore.getState().messages).toHaveLength(1)
    expect(queryClient.getQueryData(['dashboard', 'today'])).toBeDefined()
  })
})

describe('failed confirm keeps the card actionable (#55)', () => {
  function Thread() {
    const { messages, logItemsDirect, confirmError, isProcessing } = useMealStore()
    return (
      <QueryClientProvider client={queryClient}>
        <ChatThread
          messages={messages}
          onAction={vi.fn()}
          onConfirmLog={logItemsDirect}
          onCancel={vi.fn()}
          onDismissCard={vi.fn()}
          onDecompose={vi.fn()}
          onCombine={vi.fn()}
          isLoading={isProcessing}
          confirmError={confirmError}
        />
      </QueryClientProvider>
    )
  }

  beforeEach(() => {
    vi.clearAllMocks()
    useMealStore.getState().resetChat()
    useMealStore.setState({
      messages: [
        {
          id: 'c1',
          sender: 'agent',
          text: 'found',
          timestamp: new Date().toISOString(),
          paused: true,
          items: [item],
        },
      ],
      conversationId: 'thread-1',
    })
  })
  afterEach(cleanup)

  it('shows an inline error with Retry, and Retry re-sends', async () => {
    post.mockRejectedValueOnce(new Error('offline'))
    render(<Thread />)
    fireEvent.click(screen.getByRole('button', { name: /confirm & log/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/couldn't log that/i)
    // Card still interactive: controls present, no extra chat bubble displaced it.
    expect(screen.getByRole('button', { name: /confirm & log/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeTruthy()
    expect(useMealStore.getState().messages).toHaveLength(1)

    post.mockResolvedValueOnce({ meal_id: 'meal-1', kcal: 52, message: 'Logged!' })
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(useMealStore.getState().messages[0].resolved).toBe('logged'))
    expect(useMealStore.getState().confirmError).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
