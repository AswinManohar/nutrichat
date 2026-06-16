import { useEffect } from 'react'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { useGoals } from '../../api/hooks'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'
import { MascotSprite } from '../mascot/MascotSprite'
import { MascotPeek } from '../mascot/MascotPeek'
import { useMascotStore } from '../../stores/mascotStore'

function LoadingScreen({ message }: { message: string }) {
  const mascotEnabled = useMascotStore((s) => s.enabled)
  return (
    <div className="fixed inset-0 bg-surface flex flex-col items-center justify-center gap-5 z-50">
      {mascotEnabled ? (
        <MascotSprite size={12} />
      ) : (
        <div className="flex gap-1.5">
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '0ms' }} />
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '150ms' }} />
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '300ms' }} />
        </div>
      )}
      <span className="text-[13px] text-muted">{message}</span>
    </div>
  )
}

export function ProtectedLayout() {
  const { user, isLoading: authLoading, initialize } = useAuthStore()
  const { data: goals, isLoading: goalsLoading, error } = useGoals()
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    initialize()
  }, [initialize])

  // 404 on /goals means not onboarded yet
  useEffect(() => {
    if (error && (error.status === 404 || error.message.includes('404'))) {
      if (location.pathname !== '/onboarding') {
        navigate('/onboarding')
      }
    }
  }, [error, location.pathname, navigate])

  if (authLoading) {
    return <LoadingScreen message="Syncing session…" />
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (goalsLoading && location.pathname !== '/onboarding') {
    return <LoadingScreen message="Loading your goals…" />
  }

  if (goals && location.pathname === '/onboarding') {
    return <Navigate to="/chat" replace />
  }

  return (
    <div className="flex min-h-screen bg-surface text-ink font-sans">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden pb-20 md:pb-0 h-screen relative">
        <Outlet />
      </main>
      <MobileNav />
      <MascotPeek />
    </div>
  )
}
