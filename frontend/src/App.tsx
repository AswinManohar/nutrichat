import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './api/queryClient'
import { LoginPage } from './pages/LoginPage'
import { AuthCallbackPage } from './pages/AuthCallbackPage'
import { OnboardingPage } from './pages/OnboardingPage'
import { ChatPage } from './pages/ChatPage'
import { MyMealsPage } from './pages/MyMealsPage'
import { TrendsPage } from './pages/TrendsPage'
import { SettingsPage } from './pages/SettingsPage'
import { UpgradePage } from './pages/UpgradePage'
import { ProtectedLayout } from './components/layout/ProtectedLayout'

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Public Auth Portal */}
          <Route path="/login" element={<LoginPage />} />
          {/* Landing page for Supabase email verification links — the user is
              not signed in yet, so this must stay outside ProtectedLayout. */}
          <Route path="/auth/callback" element={<AuthCallbackPage />} />

          {/* Protected Area (Auth gated & Onboarding checked) */}
          <Route element={<ProtectedLayout />}>
            <Route path="/onboarding" element={<OnboardingPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/my-meals" element={<MyMealsPage />} />
            <Route path="/trends" element={<TrendsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/upgrade" element={<UpgradePage />} />
            {/* Standard landing redirects */}
            <Route path="/" element={<Navigate to="/chat" replace />} />
          </Route>

          {/* Catch-all Redirect */}
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
