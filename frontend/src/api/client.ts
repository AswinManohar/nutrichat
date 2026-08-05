import { useAuthStore } from '../stores/authStore'
import { supabase } from '../lib/supabase'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Return a currently-valid access token, refreshing it if it has expired.
 *
 * The auth store caches the access token it saw at sign-in or at the last
 * `onAuthStateChange`. That copy goes stale whenever a background refresh
 * fails to reach the store — typically after the tab has been hidden or the
 * machine asleep past the token's one-hour lifetime. Supabase's `getSession()`
 * checks the expiry itself and refreshes before returning, so asking it per
 * request keeps the token fresh no matter what the store holds.
 */
async function getAccessToken(): Promise<string | null> {
  const { data, error } = await supabase.auth.getSession()
  if (error) return useAuthStore.getState().token
  return data.session?.access_token ?? null
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const { isBypassed, debugUserId } = useAuthStore.getState()

  const buildHeaders = (token: string | null): Record<string, string> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }

    // Add authorization details
    if (isBypassed) {
      headers['X-Debug-User-Id'] = debugUserId
      headers['Authorization'] = 'Bearer dev-bypass-token'
    } else if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    // Merge headers from options
    if (options.headers) {
      const customHeaders = options.headers as Record<string, string>
      Object.keys(customHeaders).forEach((key) => {
        headers[key] = customHeaders[key]
      })
    }

    return headers
  }

  const send = (token: string | null) =>
    fetch(`${BASE_URL}${endpoint}`, { ...options, headers: buildHeaders(token) })

  let response = await send(isBypassed ? null : await getAccessToken())

  // A 401 means the token we sent was rejected. Force one refresh and retry:
  // without this the query parks in an error state and the app keeps rendering
  // its shell with no data until the user manually reloads the page.
  if (response.status === 401 && !isBypassed) {
    const { data, error } = await supabase.auth.refreshSession()
    if (!error && data.session) {
      response = await send(data.session.access_token)
    }
    if (response.status === 401) {
      // The session is genuinely gone — surface the login screen instead of
      // leaving the user in an app where every action silently fails.
      await useAuthStore.getState().signOut()
    }
  }

  if (!response.ok) {
    let errorDetail = 'API Request failed'
    try {
      const errJson = await response.json()
      errorDetail = errJson.detail || errJson.message || errorDetail
    } catch {
      // fallback to status text
      errorDetail = response.statusText || errorDetail
    }
    throw new ApiError(errorDetail, response.status)
  }

  if (response.status === 204) {
    return {} as T
  }

  return response.json() as Promise<T>
}

export const apiClient = {
  get: <T>(endpoint: string, options?: RequestInit) => 
    request<T>(endpoint, { ...options, method: 'GET' }),
    
  post: <T>(endpoint: string, body?: unknown, options?: RequestInit) => 
    request<T>(endpoint, { 
      ...options, 
      method: 'POST', 
      body: body ? JSON.stringify(body) : undefined 
    }),
    
  put: <T>(endpoint: string, body?: unknown, options?: RequestInit) => 
    request<T>(endpoint, { 
      ...options, 
      method: 'PUT', 
      body: body ? JSON.stringify(body) : undefined 
    }),
    
  delete: <T>(endpoint: string, options?: RequestInit) => 
    request<T>(endpoint, { ...options, method: 'DELETE' }),
}
