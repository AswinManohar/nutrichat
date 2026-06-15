import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import { Sparkles, LogIn, Mail, Lock, User } from 'lucide-react'

export const LoginPage: React.FC = () => {
  const navigate = useNavigate()

  // Standard Auth States
  const [authMode, setAuthMode] = useState<'signin' | 'signup'>('signin')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const handleStandardSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setErrorMsg(null)
    setSuccessMsg(null)

    try {
      if (authMode === 'signin') {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        if (error) {
          setErrorMsg(error.message)
        } else {
          navigate('/chat')
        }
      } else {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: {
            data: {
              full_name: fullName,
            },
          },
        })
        if (error) {
          setErrorMsg(error.message)
        } else if (data.session) {
          // Auto logged in
          navigate('/chat')
        } else {
          setSuccessMsg('Account created successfully! Please check your email for a verification link.')
        }
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'An unexpected error occurred')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen w-full bg-surface flex flex-col items-center justify-center p-4 relative overflow-hidden">
      {/* Background Gradients for aesthetic depth */}
      <div className="absolute top-1/4 left-1/4 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[400px] rounded-full bg-container blur-[100px] pointer-events-none"></div>
      <div className="absolute bottom-1/4 right-1/4 translate-x-1/2 translate-y-1/2 w-[350px] h-[350px] rounded-full bg-sage/10 blur-[100px] pointer-events-none"></div>

      <div className="w-full max-w-md relative z-10">
        {/* Branding header */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 bg-gradient-to-tr from-sage to-sage-deep rounded-2xl flex items-center justify-center shadow-lg shadow-black/5 mb-3">
            <Sparkles className="w-6 h-6 text-white" />
          </div>
          <h1 className="font-display text-3xl text-sage-deep">
            NutriChat
          </h1>
          <p className="text-xs text-muted mt-1">AI-Powered Macro Coaching & Meal Logging</p>
        </div>

        <Card className="border border-sand-border shadow-2xl bg-sand backdrop-blur-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <LogIn className="w-5 h-5 text-sage-deep" />
              {authMode === 'signin' ? 'Standard Login' : 'Create Account'}
            </CardTitle>
            <CardDescription>
              {authMode === 'signin'
                ? 'Sign in securely with your Supabase account.'
                : 'Sign up for a free tracker account.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleStandardSubmit} className="space-y-4">
                  {errorMsg && (
                    <div className="bg-danger/10 border border-danger/20 text-danger text-xs p-3 rounded-xl">
                      {errorMsg}
                    </div>
                  )}

                  {successMsg && (
                    <div className="bg-container border border-sage/30 text-sage-deep text-xs p-3 rounded-xl">
                      {successMsg}
                    </div>
                  )}

                  {authMode === 'signup' && (
                    <div className="space-y-1">
                      <label className="block text-xs text-muted">Full Name</label>
                      <div className="relative flex items-center">
                        <User className="w-4 h-4 text-muted absolute left-3" />
                        <input
                          type="text"
                          required={authMode === 'signup'}
                          value={fullName}
                          onChange={(e) => setFullName(e.target.value)}
                          placeholder="Jane Doe"
                          className="w-full bg-surface border border-sand-border rounded-xl pl-10 pr-4 py-2.5 text-sm text-ink-soft focus:outline-none focus:ring-1 focus:ring-sage/30"
                        />
                      </div>
                    </div>
                  )}

                  <div className="space-y-1">
                    <label className="block text-xs text-muted">Email Address</label>
                    <div className="relative flex items-center">
                      <Mail className="w-4 h-4 text-muted absolute left-3" />
                      <input
                        type="email"
                        required
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="you@example.com"
                        className="w-full bg-surface border border-sand-border rounded-xl pl-10 pr-4 py-2.5 text-sm text-ink-soft focus:outline-none focus:ring-1 focus:ring-sage/30"
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="block text-xs text-muted">Password</label>
                    <div className="relative flex items-center">
                      <Lock className="w-4 h-4 text-muted absolute left-3" />
                      <input
                        type="password"
                        required
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="••••••••"
                        className="w-full bg-surface border border-sand-border rounded-xl pl-10 pr-4 py-2.5 text-sm text-ink-soft focus:outline-none focus:ring-1 focus:ring-sage/30"
                      />
                    </div>
                  </div>

                  <Button type="submit" variant="primary" className="w-full py-2.5 mt-2" isLoading={loading}>
                    {authMode === 'signin' ? 'Sign In' : 'Sign Up & Start Free'}
                  </Button>

                  <div className="text-center mt-4 border-t border-sand-border pt-4">
                    <button
                      type="button"
                      onClick={() => {
                        setAuthMode(authMode === 'signin' ? 'signup' : 'signin')
                        setErrorMsg(null)
                        setSuccessMsg(null)
                      }}
                      className="text-xs text-sage-deep hover:text-sage-deep underline font-medium cursor-pointer"
                    >
                      {authMode === 'signin'
                        ? "Don't have an account? Sign Up"
                        : 'Already have an account? Sign In'}
                    </button>
                  </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
