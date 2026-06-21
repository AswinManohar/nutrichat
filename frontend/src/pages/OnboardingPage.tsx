import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ActivityLevel, BiologicalSex, DietGoal } from '../lib/tdee'
import { calculateTDEE } from '../lib/tdee'
import { useCreateGoals } from '../api/hooks'
import { enablePushReminders, isPushSupported, type PushResult } from '../lib/push'
import { GoalSlider } from '../components/onboarding/GoalSlider'
import { PreferenceChips } from '../components/onboarding/PreferenceChips'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import type { TrackingMode } from '../api/types'
import {
  Flame,
  Target,
  Heart,
  Dumbbell,
  Leaf,
  TrendingDown,
  Scale,
  Bell,
  Clock,
  Check,
} from 'lucide-react'

/** Ordered screens per tracking path. Focus is always first. */
const GOAL_SCREENS = ['focus', 'biometrics', 'blueprint', 'prefs', 'reminders'] as const
const MINDFUL_SCREENS = ['focus', 'prefs', 'reminders'] as const
type ScreenName = (typeof GOAL_SCREENS)[number]

export const OnboardingPage: React.FC = () => {
  const navigate = useNavigate()
  const createGoalsMutation = useCreateGoals()

  // null until the user picks a focus on the first screen.
  const [trackingMode, setTrackingMode] = useState<TrackingMode | null>(null)
  const [screen, setScreen] = useState(0)

  // Biometrics
  const [weight, setWeight] = useState(70)
  const [height, setHeight] = useState(170)
  const [age, setAge] = useState(28)
  const [sex, setSex] = useState<BiologicalSex>('female')
  const [activity, setActivity] = useState<ActivityLevel>('moderately_active')
  const [dietGoal, setDietGoal] = useState<DietGoal>('lose')

  // Blueprint (computed defaults, optionally adjusted)
  const [kcalGoal, setKcalGoal] = useState(2000)
  const [proteinGoal, setProteinGoal] = useState(120)
  const [fiberGoal, setFiberGoal] = useState(30)
  const [showAdjust, setShowAdjust] = useState(false)

  // Preferences
  const [dietaryPrefs, setDietaryPrefs] = useState<string[]>([])

  // Implementation intention (Q5)
  const [mealTime, setMealTime] = useState('08:00')
  const [pushResult, setPushResult] = useState<PushResult | null>(null)
  const [pushBusy, setPushBusy] = useState(false)

  const screens: readonly ScreenName[] =
    trackingMode === 'mindful' ? MINDFUL_SCREENS : GOAL_SCREENS
  const current: ScreenName = screens[screen]

  // Recompute smart-default targets when entering the blueprint screen
  // ("adjust state during render" pattern).
  const [prevScreen, setPrevScreen] = useState<ScreenName>('focus')
  if (current !== prevScreen) {
    setPrevScreen(current)
    if (current === 'blueprint') {
      const targets = calculateTDEE({
        weightKg: weight,
        heightCm: height,
        ageYears: age,
        sex,
        activityLevel: activity,
        dietGoal,
      })
      setKcalGoal(targets.kcalGoal)
      setProteinGoal(Math.round(targets.proteinGoal))
      setFiberGoal(Math.round(targets.fiberGoal))
      setShowAdjust(false)
    }
  }

  const chooseFocus = (goal: DietGoal | null, mode: TrackingMode) => {
    setTrackingMode(mode)
    if (goal) setDietGoal(goal)
    setScreen(1)
  }

  const handleNext = () => {
    if (screen < screens.length - 1) {
      setScreen((s) => s + 1)
    } else {
      handleSubmit(true)
    }
  }

  const handleBack = () => {
    if (screen > 0) setScreen((s) => s - 1)
  }

  const handleEnablePush = async () => {
    setPushBusy(true)
    const result = await enablePushReminders()
    setPushResult(result)
    setPushBusy(false)
  }

  const handleSubmit = (withMealTime: boolean) => {
    const prefsObject: Record<string, boolean> = {}
    dietaryPrefs.forEach((p) => {
      prefsObject[p] = true
    })
    const mindful = trackingMode === 'mindful'

    createGoalsMutation.mutate(
      {
        tracking_mode: trackingMode ?? 'goals',
        kcal_goal: mindful ? null : kcalGoal,
        protein_goal: mindful ? null : proteinGoal,
        fiber_goal: mindful ? null : fiberGoal,
        dietary_prefs: prefsObject,
        first_meal_time: withMealTime ? mealTime : null,
      },
      {
        onSuccess: () => navigate('/chat'),
      }
    )
  }

  const activityOptions = [
    { label: 'Sedentary (desk job, minimal exercise)', value: 'sedentary' },
    { label: 'Lightly Active (light exercise 1-3 days/week)', value: 'lightly_active' },
    { label: 'Moderately Active (moderate exercise 3-5 days/week)', value: 'moderately_active' },
    { label: 'Very Active (hard exercise 6-7 days/week)', value: 'very_active' },
    { label: 'Extra Active (athletic job or physical training)', value: 'extra_active' },
  ]

  const focusOptions = [
    {
      label: 'Lose fat',
      desc: 'Track toward a healthy calorie deficit.',
      icon: TrendingDown,
      goal: 'lose' as DietGoal,
      mode: 'goals' as TrackingMode,
      accent: 'from-sage to-sage-deep',
    },
    {
      label: 'Maintain health',
      desc: 'Hold your weight and improve composition.',
      icon: Scale,
      goal: 'maintain' as DietGoal,
      mode: 'goals' as TrackingMode,
      accent: 'from-sage to-sage-deep',
    },
    {
      label: 'Build muscle',
      desc: 'Support growth with a safe surplus.',
      icon: Dumbbell,
      goal: 'gain' as DietGoal,
      mode: 'goals' as TrackingMode,
      accent: 'from-sage to-sage-deep',
    },
    {
      label: 'Just track mindfully',
      desc: 'No targets — log what you eat, with safety alerts only.',
      icon: Leaf,
      goal: null,
      mode: 'mindful' as TrackingMode,
      accent: 'from-fiber to-warn',
    },
  ]

  const preferenceOptions = [
    { label: 'Vegan', value: 'vegan' },
    { label: 'Vegetarian', value: 'vegetarian' },
    { label: 'Pescetarian', value: 'pescetarian' },
    { label: 'Keto / Ketogenic', value: 'keto' },
    { label: 'Paleo', value: 'paleo' },
    { label: 'Gluten-Free', value: 'gluten_free' },
    { label: 'Dairy-Free', value: 'dairy_free' },
    { label: 'Low-Carb', value: 'low_carb' },
    { label: 'High-Protein Focus', value: 'high_protein' },
  ]

  const pushMessages: Record<PushResult, string> = {
    subscribed: "You're all set — we'll nudge you at this time.",
    denied: 'Notifications are blocked. You can enable them later in settings.',
    unsupported: "This browser doesn't support reminders yet.",
    'not-configured': "Reminders aren't available right now — your time is still saved.",
    error: "Couldn't set up reminders. You can try again later.",
  }

  return (
    <div className="min-height-screen w-full bg-surface flex flex-col items-center justify-center p-4 md:p-8">
      <div className="w-full max-w-2xl">
        {/* Header logo / branding */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 bg-gradient-to-tr from-sage to-sage-deep rounded-2xl flex items-center justify-center shadow-lg shadow-black/5 mb-3">
            <Target className="w-6 h-6 text-white" />
          </div>
          <h1 className="font-display text-3xl text-sage-deep">Welcome to NutriChat</h1>
          <p className="text-sm text-muted mt-1">Let's set you up in a few quick steps</p>
        </div>

        {/* Progress bar (after focus is chosen) */}
        {screen >= 1 && (
          <div className="flex items-center gap-2 mb-8 px-4">
            {screens.slice(1).map((name, i) => {
              const stepIndex = i + 1
              const done = screen >= stepIndex
              return (
                <div
                  key={name}
                  className={`h-1.5 flex-1 rounded-full transition-colors duration-200 ${
                    done ? 'bg-sage' : 'bg-container'
                  }`}
                />
              )
            })}
          </div>
        )}

        {/* SCREEN: FOCUS (also picks tracking mode) */}
        {current === 'focus' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="md:col-span-2 text-center mb-2">
              <h2 className="font-display text-xl text-ink">What's your primary focus right now?</h2>
              <p className="text-sm text-muted mt-1">This shapes everything that follows.</p>
            </div>
            {focusOptions.map((opt) => {
              const Icon = opt.icon
              return (
                <button
                  key={opt.label}
                  type="button"
                  onClick={() => chooseFocus(opt.goal, opt.mode)}
                  className="press text-left p-6 rounded-2xl border border-sand-border bg-sand hover:border-sage shadow-lg flex flex-col gap-3"
                >
                  <div
                    className={`w-11 h-11 rounded-xl bg-gradient-to-tr ${opt.accent} flex items-center justify-center`}
                  >
                    <Icon className="w-5 h-5 text-white" />
                  </div>
                  <h3 className="font-display text-lg text-ink">{opt.label}</h3>
                  <p className="text-[13px] text-muted leading-relaxed">{opt.desc}</p>
                </button>
              )
            })}
          </div>
        )}

        {current !== 'focus' && (
          <Card className="border border-sand-border shadow-2xl overflow-hidden bg-sand backdrop-blur-md">
            {/* SCREEN: BIOMETRICS */}
            {current === 'biometrics' && (
              <>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Dumbbell className="w-5 h-5 text-sage-deep" />
                    Your profile
                  </CardTitle>
                  <CardDescription>
                    We use this to calculate your base metabolic rate and energy targets.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-muted mb-2">
                        Sex (for metabolic calculation)
                      </label>
                      <div className="grid grid-cols-2 gap-2">
                        <button
                          type="button"
                          onClick={() => setSex('female')}
                          className={`py-2 rounded-xl text-sm font-medium border transition-all ${
                            sex === 'female'
                              ? 'bg-sage border-sage text-white'
                              : 'bg-sand border-sand-border text-muted hover:border-sand-border'
                          }`}
                        >
                          Female
                        </button>
                        <button
                          type="button"
                          onClick={() => setSex('male')}
                          className={`py-2 rounded-xl text-sm font-medium border transition-all ${
                            sex === 'male'
                              ? 'bg-sage border-sage text-white'
                              : 'bg-sand border-sand-border text-muted hover:border-sand-border'
                          }`}
                        >
                          Male
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted mb-2">Age (years)</label>
                      <input
                        type="number"
                        min="10"
                        max="100"
                        value={age || ''}
                        onChange={(e) => setAge(Number(e.target.value))}
                        className="w-full bg-sand border border-sand-border rounded-xl px-4 py-2.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-sage/30"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-medium text-muted mb-2">Weight (kg)</label>
                      <input
                        type="number"
                        min="30"
                        max="250"
                        value={weight || ''}
                        onChange={(e) => setWeight(Number(e.target.value))}
                        className="w-full bg-sand border border-sand-border rounded-xl px-4 py-2.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-sage/30"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted mb-2">Height (cm)</label>
                      <input
                        type="number"
                        min="100"
                        max="250"
                        value={height || ''}
                        onChange={(e) => setHeight(Number(e.target.value))}
                        className="w-full bg-sand border border-sand-border rounded-xl px-4 py-2.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-sage/30"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-muted mb-2">
                      Daily activity level
                    </label>
                    <select
                      value={activity}
                      onChange={(e) => setActivity(e.target.value as ActivityLevel)}
                      className="w-full bg-sand border border-sand-border rounded-xl px-4 py-2.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-sage/30"
                    >
                      {activityOptions.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </CardContent>
              </>
            )}

            {/* SCREEN: BLUEPRINT (smart defaults, accept or adjust) */}
            {current === 'blueprint' && (
              <>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Flame className="w-5 h-5 text-sage-deep" />
                    Your daily blueprint
                  </CardTitle>
                  <CardDescription>
                    Based on your biology and goal, here's what you have available each day.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  {!showAdjust ? (
                    <>
                      <div className="grid grid-cols-3 gap-3">
                        {[
                          { label: 'Calories', value: kcalGoal, unit: 'kcal' },
                          { label: 'Protein', value: proteinGoal, unit: 'g' },
                          { label: 'Fiber', value: fiberGoal, unit: 'g' },
                        ].map((m) => (
                          <div
                            key={m.label}
                            className="p-4 bg-container border border-sand-border rounded-xl text-center"
                          >
                            <div className="font-display font-bold text-2xl text-sage-deep">
                              {m.value.toLocaleString()}
                            </div>
                            <div className="text-[11px] text-muted mt-0.5">
                              {m.unit} {m.label.toLowerCase()} available
                            </div>
                          </div>
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() => setShowAdjust(true)}
                        className="text-xs font-medium text-sage-deep hover:underline"
                      >
                        Adjust targets manually
                      </button>
                    </>
                  ) : (
                    <>
                      <GoalSlider
                        label="Daily Calories"
                        min={1000}
                        max={5000}
                        step={50}
                        value={kcalGoal}
                        unit="kcal"
                        onChange={setKcalGoal}
                        description="Your daily energy available"
                      />
                      <GoalSlider
                        label="Daily Protein"
                        min={40}
                        max={300}
                        step={5}
                        value={proteinGoal}
                        unit="g"
                        onChange={setProteinGoal}
                        description="Essential for lean tissue preservation and repair"
                      />
                      <GoalSlider
                        label="Daily Fiber"
                        min={10}
                        max={80}
                        step={1}
                        value={fiberGoal}
                        unit="g"
                        onChange={setFiberGoal}
                        description="Critical for digestion and metabolic health"
                      />
                    </>
                  )}
                </CardContent>
              </>
            )}

            {/* SCREEN: PREFERENCES */}
            {current === 'prefs' && (
              <>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Heart className="w-5 h-5 text-sage-deep" />
                    Dietary preferences
                  </CardTitle>
                  <CardDescription>
                    Select any patterns or exclusions so we can personalize and error-check your logs.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <PreferenceChips
                    options={preferenceOptions}
                    selectedValues={dietaryPrefs}
                    onChange={setDietaryPrefs}
                  />
                </CardContent>
              </>
            )}

            {/* SCREEN: REMINDERS (implementation intention + push) */}
            {current === 'reminders' && (
              <>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Clock className="w-5 h-5 text-sage-deep" />
                    When do you eat first?
                  </CardTitle>
                  <CardDescription>
                    Pick the time you usually have your first meal — we'll gently remind you to log it.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div>
                    <label className="block text-xs font-medium text-muted mb-2">
                      Typical first meal
                    </label>
                    <input
                      type="time"
                      value={mealTime}
                      onChange={(e) => setMealTime(e.target.value)}
                      className="w-full bg-sand border border-sand-border rounded-xl px-4 py-2.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-sage/30"
                    />
                  </div>

                  {isPushSupported() ? (
                    <div className="flex flex-col gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={handleEnablePush}
                        isLoading={pushBusy}
                        disabled={pushResult === 'subscribed'}
                        className="self-start"
                      >
                        {pushResult === 'subscribed' ? (
                          <>
                            <Check className="w-4 h-4 mr-1.5" /> Reminders on
                          </>
                        ) : (
                          <>
                            <Bell className="w-4 h-4 mr-1.5" /> Enable reminders
                          </>
                        )}
                      </Button>
                      {pushResult && (
                        <p className="text-[11px] text-muted">{pushMessages[pushResult]}</p>
                      )}
                    </div>
                  ) : (
                    <p className="text-[11px] text-muted">
                      Reminders aren't supported in this browser yet — your time is still saved.
                    </p>
                  )}
                </CardContent>
              </>
            )}

            {/* Card footer actions */}
            <div className="px-6 py-4 bg-surface/50 border-t border-sand-border flex items-center justify-between">
              <Button type="button" variant="outline" onClick={handleBack}>
                Back
              </Button>

              {current === 'reminders' ? (
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => handleSubmit(false)}
                    disabled={createGoalsMutation.isPending}
                  >
                    Skip for now
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    onClick={() => handleSubmit(true)}
                    isLoading={createGoalsMutation.isPending}
                  >
                    Complete setup
                  </Button>
                </div>
              ) : (
                <Button type="button" variant="primary" onClick={handleNext}>
                  {current === 'blueprint' ? 'Accept & Continue' : 'Continue'}
                </Button>
              )}
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
