import { useAuthStore } from '../stores/authStore'

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const { token, isBypassed, debugUserId } = useAuthStore.getState()
  
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

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
  })

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
