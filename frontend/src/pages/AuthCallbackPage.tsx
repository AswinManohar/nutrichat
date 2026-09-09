import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import { Sparkles, TriangleAlert } from 'lucide-react'

type CallbackStatus = 'verifying' | 'error'

/**
 * Reads the auth callback parameters out of the current URL.
 *
 * The Supabase JS client defaults to the implicit flow, so a confirmed email
 * link lands here as `#access_token=...&refresh_token=...`, and a failed one as
 * `#error=access_denied&error_code=otp_expired&...`. Query parameters are also
 * read (and win on conflict) to mirror the client's own parsing.
 */
function readCallbackParams(): Record<string, string> {
  const params: Record<string, string> = {}
  const { hash, search } = window.location

  if (hash.startsWith('#')) {
    new URLSearchParams(hash.slice(1)).forEach((value, key) => {
      params[key] = value
    })
  }
  new URLSearchParams(search).forEach((value, key) => {
    params[key] = value
  })

  return params
}

const EXPIRED_LINK_MESSAGE =
  'This confirmation link has expired or has already been used. Head back and sign in — ' +
  'if the account still is not confirmed, sign up again to get a fresh link.'

function describeCallbackError(params: Record<string, string>): string {
  if (params.error_code === 'otp_expired' || params.error_code === 'access_denied') {
    return EXPIRED_LINK_MESSAGE
  }
  return params.error_description || 'We could not confirm your email address.'
}

export const AuthCallbackPage: React.FC = () => {
  const navigate = useNavigate()

  // Captured on first render: once the Supabase client consumes a valid link it
  // clears the URL fragment, so reading it later would come back empty.
  const [params] = useState(readCallbackParams)
  const [status, setStatus] = useState<CallbackStatus>('verifying')
  const [errorMsg, setErrorMsg] = useState<string>('')

  useEffect(() => {
    let cancelled = false

    const fail = (message: string) => {
      if (cancelled) return
      setErrorMsg(message)
      setStatus('error')
    }

    const completeVerification = async () => {
      if (params.error || params.error_code || params.error_description) {
        fail(describeCallbackError(params))
        return
      }

      try {
        // `detectSessionInUrl` is on by default, so the client already exchanged
        // the fragment for a session while it was initialising. `getSession()`
        // awaits that same initialisation promise, so this is not a race.
        const { data, error } = await supabase.auth.getSession()
        if (error) {
          fail(error.message)
          return
        }
        if (!data.session) {
          fail(EXPIRED_LINK_MESSAGE)
          return
        }
        if (!cancelled) navigate('/chat', { replace: true })
      } catch (err) {
        fail(err instanceof Error ? err.message : 'An unexpected error occurred')
      }
    }

    void completeVerification()

    return () => {
      cancelled = true
    }
  }, [params, navigate])

  return (
    <div className="min-h-screen w-full bg-surface flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Branding header */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 bg-sage rounded-xl flex items-center justify-center mb-3">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <h1 className="font-display text-3xl text-sage-deep">Mealsy</h1>
          <p className="text-xs text-muted mt-1">AI-Powered Macro Coaching &amp; Meal Logging</p>
        </div>

        <Card className="border border-sand-border shadow-2xl bg-sand backdrop-blur-md">
          {status === 'verifying' ? (
            <>
              <CardHeader>
                <CardTitle>Confirming your email…</CardTitle>
                <CardDescription>Hang tight, this only takes a moment.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex gap-1.5 justify-center py-2" role="status" aria-label="Confirming your email">
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '0ms' }} />
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '150ms' }} />
                  <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '300ms' }} />
                </div>
              </CardContent>
            </>
          ) : (
            <>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TriangleAlert className="w-5 h-5 text-danger" />
                  We couldn&apos;t confirm your email
                </CardTitle>
                <CardDescription>Your link did not check out.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="bg-danger/10 border border-danger/20 text-danger text-xs p-3 rounded-xl leading-relaxed">
                  {errorMsg}
                </div>
                <Link
                  to="/login"
                  className="block text-center text-xs text-sage-deep hover:text-sage-deep underline font-medium"
                >
                  Back to sign in
                </Link>
              </CardContent>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
