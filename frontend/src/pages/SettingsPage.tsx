import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useGoals,
  useUpdateGoals,
  useTelegramLinkStatus,
  useGenerateTelegramLinkCode,
  useDisconnectTelegram,
  useQuota,
} from '../api/hooks'
import { GoalSlider } from '../components/onboarding/GoalSlider'
import { PreferenceChips } from '../components/onboarding/PreferenceChips'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import { useAuthStore } from '../stores/authStore'
import { Sparkles, Save, ShieldAlert, LogOut, Heart, Target, Send, Zap } from 'lucide-react'
import { useMascotStore } from '../stores/mascotStore'

export const SettingsPage: React.FC = () => {
  const { user, signOut, isBypassed, disableBypass } = useAuthStore()
  const { data: goals, isLoading: goalsLoading } = useGoals()
  const updateGoalsMutation = useUpdateGoals()

  // Telegram linking
  const { data: telegramStatus } = useTelegramLinkStatus()
  const generateLinkCodeMutation = useGenerateTelegramLinkCode()
  const disconnectTelegramMutation = useDisconnectTelegram()
  const [linkCode, setLinkCode] = useState<{ code: string; bot_username: string } | null>(null)

  const handleGenerateCode = () => {
    generateLinkCodeMutation.mutate(undefined, {
      onSuccess: (data) => setLinkCode({ code: data.code, bot_username: data.bot_username }),
    })
  }

  // Local state for settings form
  const [kcalGoal, setKcalGoal] = useState(2000)
  const [proteinGoal, setProteinGoal] = useState(120)
  const [fiberGoal, setFiberGoal] = useState(30)
  const [dietaryPrefs, setDietaryPrefs] = useState<string[]>([])
  const [saveSuccess, setSaveSuccess] = useState(false)
  const { enabled: mascotEnabled, setEnabled: setMascotEnabled } = useMascotStore()
  const navigate = useNavigate()
  const { data: quota } = useQuota()
  const quotaPct = quota ? Math.min(100, Math.round((quota.used / quota.limit) * 100)) : 0

  // Seed form from fetched goals (React "adjust state during render")
  const [seededFrom, setSeededFrom] = useState<typeof goals | null>(null)
  if (goals && seededFrom !== goals) {
    setSeededFrom(goals)
    setKcalGoal(goals.kcal_goal ?? 2000)
    setProteinGoal(goals.protein_goal ?? 120)
    setFiberGoal(goals.fiber_goal ?? 30)
    setDietaryPrefs(
      Object.keys(goals.dietary_prefs || {}).filter((key) => goals.dietary_prefs[key] === true)
    )
  }

  const currentMode = goals?.tracking_mode ?? 'goals'

  const prefsObject = (): Record<string, boolean> => {
    const obj: Record<string, boolean> = {}
    dietaryPrefs.forEach((p) => {
      obj[p] = true
    })
    return obj
  }

  const switchMode = () => {
    const toMindful = currentMode === 'goals'
    updateGoalsMutation.mutate({
      tracking_mode: toMindful ? 'mindful' : 'goals',
      kcal_goal: toMindful ? null : kcalGoal,
      protein_goal: toMindful ? null : proteinGoal,
      fiber_goal: toMindful ? null : fiberGoal,
      dietary_prefs: prefsObject(),
    })
  }

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    setSaveSuccess(false)

    updateGoalsMutation.mutate(
      {
        tracking_mode: currentMode,
        kcal_goal: currentMode === 'mindful' ? null : kcalGoal,
        protein_goal: currentMode === 'mindful' ? null : proteinGoal,
        fiber_goal: currentMode === 'mindful' ? null : fiberGoal,
        dietary_prefs: prefsObject(),
      },
      {
        onSuccess: () => {
          setSaveSuccess(true)
          // Hide success message after 3 seconds
          setTimeout(() => setSaveSuccess(false), 3000)
        },
      }
    )
  }

  const preferenceOptions = [
    { label: 'Vegan', value: 'vegan' },
    { label: 'Vegetarian', value: 'vegetarian' },
    { label: 'Keto / Ketogenic', value: 'keto' },
    { label: 'Paleo', value: 'paleo' },
    { label: 'Gluten-Free', value: 'gluten_free' },
    { label: 'Dairy-Free', value: 'dairy_free' },
    { label: 'Low-Carb', value: 'low_carb' },
    { label: 'High-Protein Focus', value: 'high_protein' },
  ]

  if (goalsLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface">
        <div className="flex flex-col items-center gap-3">
          <span className="w-8 h-8 border-2 border-t-transparent border-sage rounded-full animate-spin"></span>
          <span className="text-sm text-muted">Loading settings...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto bg-surface p-4 md:p-8">
      <div className="max-w-2xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-sand-border pb-5">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-container border border-sand-border text-sage-deep flex items-center justify-center">
              <Target className="w-5 h-5" />
            </div>
            <div>
              <h1 className="font-display font-bold text-xl text-ink">Settings</h1>
              <p className="text-xs text-muted">Configure your daily nutrition targets and profile</p>
            </div>
          </div>
        </div>

        {/* Settings Form */}
        <form onSubmit={handleSave} className="space-y-6">
          {saveSuccess && (
            <div className="bg-container border border-sage/30 text-sage-deep text-xs p-3 rounded-xl flex items-center gap-2">
              <Sparkles className="w-4 h-4 animate-pulse" />
              Settings saved successfully!
            </div>
          )}

          {/* Tracking Mode Card */}
          <Card className="border border-sand-border bg-sand backdrop-blur-md">
            <CardHeader>
              <CardTitle>Tracking mode</CardTitle>
              <CardDescription>
                {currentMode === 'mindful'
                  ? 'Mindful Eating — you see amounts consumed with no targets, plus safety alerts.'
                  : 'Goal tracking — daily calorie, protein and fiber targets with progress rings.'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button
                type="button"
                variant="outline"
                onClick={switchMode}
                isLoading={updateGoalsMutation.isPending}
              >
                {currentMode === 'mindful'
                  ? 'Switch to Goal Tracking'
                  : 'Switch to Mindful Eating'}
              </Button>
            </CardContent>
          </Card>

          {/* Caloric & Macronutrient Targets Card (goal mode only) */}
          {currentMode === 'goals' && (
          <Card className="border border-sand-border bg-sand backdrop-blur-md">
            <CardHeader>
              <CardTitle>Daily Nutrient Goals</CardTitle>
              <CardDescription>Adjust your caloric intake limits and macro ratios.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <GoalSlider
                label="Calorie Goal"
                min={1000}
                max={5000}
                step={50}
                value={kcalGoal}
                unit="kcal"
                onChange={setKcalGoal}
              />

              <GoalSlider
                label="Protein Goal"
                min={40}
                max={300}
                step={5}
                value={proteinGoal}
                unit="g"
                onChange={setProteinGoal}
              />

              <GoalSlider
                label="Fiber Goal"
                min={10}
                max={80}
                step={1}
                value={fiberGoal}
                unit="g"
                onChange={setFiberGoal}
              />
            </CardContent>
          </Card>
          )}

          {/* Dietary Preferences Card */}
          <Card className="border border-sand-border bg-sand backdrop-blur-md">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Heart className="w-4 h-4 text-sage-deep" />
                Dietary Focus
              </CardTitle>
              <CardDescription>Dietary styles that should guide your coaching responses.</CardDescription>
            </CardHeader>
            <CardContent>
              <PreferenceChips
                options={preferenceOptions}
                selectedValues={dietaryPrefs}
                onChange={setDietaryPrefs}
              />
            </CardContent>
          </Card>

          {/* Action Buttons */}
          <div className="flex items-center justify-end">
            <Button
              type="submit"
              variant="primary"
              className="flex items-center gap-2 px-6 py-3"
              isLoading={updateGoalsMutation.isPending}
            >
              <Save className="w-4 h-4" />
              Save Settings
            </Button>
          </div>
        </form>

        {/* Telegram Linking Card */}
        <Card className="border border-sand-border bg-sand backdrop-blur-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Send className="w-4 h-4 text-sage-deep" />
              Telegram Bot
            </CardTitle>
            <CardDescription>
              Log meals and ask coaching questions from Telegram.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-xs">
            {telegramStatus?.linked ? (
              <div className="flex items-center justify-between">
                <span className="text-ink-soft">Telegram is connected to your account.</span>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => disconnectTelegramMutation.mutate()}
                  isLoading={disconnectTelegramMutation.isPending}
                  className="border-sand-border hover:bg-danger/5 hover:text-danger hover:border-danger/20"
                >
                  Disconnect
                </Button>
              </div>
            ) : (
              <div className="space-y-3">
                {linkCode ? (
                  <div className="bg-container border border-sage/30 rounded-xl p-3 space-y-1">
                    <p className="text-ink-soft">
                      Send this to{' '}
                      <span className="font-semibold">@{linkCode.bot_username || 'the bot'}</span> within
                      10 minutes:
                    </p>
                    <p className="font-mono text-lg font-bold text-sage-deep">
                      /link {linkCode.code}
                    </p>
                  </div>
                ) : (
                  <p className="text-muted">Not connected yet.</p>
                )}
                <Button
                  type="button"
                  variant="primary"
                  onClick={handleGenerateCode}
                  isLoading={generateLinkCodeMutation.isPending}
                >
                  {linkCode ? 'Generate new code' : 'Connect Telegram'}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Plan & Usage Card */}
        {quota && (
          <Card className="border border-sand-border bg-sand backdrop-blur-md">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="w-4 h-4 text-sage-deep" />
                Plan & Usage
              </CardTitle>
              <CardDescription>
                {quota.tier === 'paid' ? 'Pro plan' : 'Free plan'}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between text-xs text-muted">
                <span>{quota.used} / {quota.limit} AI requests</span>
                <span>{quotaPct}% used</span>
              </div>
              <div
                role="progressbar"
                aria-valuenow={quotaPct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`Quota usage: ${quota.used} of ${quota.limit} AI requests`}
                className="w-full h-2 bg-container rounded-full overflow-hidden"
              >
                <div
                  className={`h-full rounded-full transition-all duration-300 ${
                    quota.exhausted
                      ? 'bg-danger'
                      : quotaPct >= 80
                      ? 'bg-warn'
                      : 'bg-sage'
                  }`}
                  style={{ width: `${quotaPct}%` }}
                />
              </div>
              {quota.tier === 'paid' ? (
                <p className="text-xs text-sage-deep font-medium">
                  You're on the Pro plan
                </p>
              ) : (
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={() => navigate('/upgrade')}
                  className="w-full mt-1"
                >
                  {quota.exhausted ? 'Upgrade to unlock more' : 'Upgrade →'}
                </Button>
              )}
            </CardContent>
          </Card>
        )}

        {/* Appearance Card */}
        <Card className="border border-sand-border bg-sand backdrop-blur-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-sage-deep" />
              Appearance
            </CardTitle>
            <CardDescription>Customise visual flair.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between py-1">
              <div>
                <p className="text-sm font-medium text-ink">Pixel companion</p>
                <p className="text-xs text-muted mt-0.5">
                  A small creature appears while things load
                </p>
              </div>
              <button
                type="button"
                onClick={() => setMascotEnabled(!mascotEnabled)}
                role="switch"
                aria-checked={mascotEnabled}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sage ${
                  mascotEnabled ? 'bg-sage' : 'bg-sand-border'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                    mascotEnabled ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </CardContent>
        </Card>

        {/* Profile / Account Settings Section */}
        <Card className="border border-sand-border bg-sand backdrop-blur-md mt-4">
          <CardHeader>
            <CardTitle>Account Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-xs">
            <div className="flex justify-between py-2 border-b border-sand-border">
              <span className="text-muted">Account Email</span>
              <span className="text-ink font-semibold">{user?.email}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-sand-border">
              <span className="text-muted">User ID</span>
              <span className="text-ink font-mono text-[10px]">{user?.id}</span>
            </div>
            
            {isBypassed ? (
              <div className="bg-warn/10 border border-warn/30 p-3.5 rounded-xl flex flex-col gap-2">
                <div className="flex items-center gap-1.5 text-ink-soft font-semibold">
                  <ShieldAlert className="w-4 h-4" />
                  Offline Developer Mode is Active
                </div>
                <p className="text-[11px] text-muted leading-normal">
                  All requests bypass live Supabase session authorization checks. Useful for offline code edits.
                </p>
                <button
                  type="button"
                  onClick={disableBypass}
                  className="text-ink-soft hover:text-ink font-semibold underline text-left w-fit self-start"
                >
                  Switch back to Supabase Authentication
                </button>
              </div>
            ) : (
              <div className="text-muted leading-normal">
                Connected securely via Supabase Auth services.
              </div>
            )}

            <Button
              type="button"
              variant="outline"
              onClick={signOut}
              className="w-full flex items-center justify-center gap-2 py-2.5 mt-2 border-sand-border hover:bg-danger/5 hover:text-danger hover:border-danger/20 text-muted"
            >
              <LogOut className="w-4 h-4" />
              Sign Out from Account
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
