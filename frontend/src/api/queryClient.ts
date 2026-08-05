import { QueryClient } from '@tanstack/react-query'

import { ApiError } from './client'

// 4xx responses are decisions, not blips — retrying them just doubles the
// noise. The client already refreshes the token and retries once on a 401
// before the error ever reaches here.
function retryUnlessClientError(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false
  }
  return failureCount < 1
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: retryUnlessClientError,
    },
  },
})
