import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ActivityLevel, BiologicalSex, DietGoal } from '../lib/tdee'
import { calculateTDEE } from '../lib/tdee'
import { useCreateGoals } from '../api/hooks'
import { GoalSlider } from '../components/onboarding/GoalSlider'
import { PreferenceChips } from '../components/onboarding/PreferenceChips'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import type { TrackingMode } from '../api/types'
import { Flame, Target, Heart, Dumbbell, Leaf } from 'lucide-react'

export const OnboardingPage: React.FC = () => {
  const navigate = useNavigate()
  const createGoalsMutation = useCreateGoals()
  const [step, setStep] = useState(0)
  const [trackingMode, setTrackingMode] = useState<TrackingMode>('goals')

  // Step 1: Profile State
  const [weight, setWeight] = useState(70)
  const [height, setHeight] = useState(170)
  const [age, setAge] = useState(28)
  const [sex, setSex] = useState<BiologicalSex>('female')
  const [activity, setActivity] = useState<ActivityLevel>('moderately_active')
  const [dietGoal, setDietGoal] = useState<DietGoal>('lose')

  // Step 2: Goal State (Customizable)
  const [kcalGoal, setKcalGoal] = useState(2000)
  const [proteinGoal, setProteinGoal] = useState(120)
  const [fiberGoal, setFiberGoal] = useState(30)

  // Step 3: Preferences State
  const [dietaryPrefs, setDietaryPrefs] = useState<string[]>([])

  // Recompute default goals when entering step 2 ("adjust state during render")
  const [prevStep, setPrevStep] = useState(step)
  if (step !== prevStep) {
    setPrevStep(step)
    if (step === 2) {
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
    }
  }

  const handleNextStep = () => {
    if (step < 3) {
      setStep((s) => s + 1)
    } else {
      handleSubmit()
    }
  }

  const handlePrevStep = () => {
    // Mindful flow is Step 0 → Step 3; goal flow is 0 → 1 → 2 → 3.
    if (trackingMode === 'mindful' && step === 3) {
      setStep(0)
    } else if (step > 0) {
      setStep((s) => s - 1)
    }
  }

  const chooseMode = (mode: TrackingMode) => {
    setTrackingMode(mode)
    setStep(mode === 'mindful' ? 3 : 1)
  }

  const handleSubmit = () => {
    const prefsObject: Record<string, boolean> = {}
    dietaryPrefs.forEach((p) => {
      prefsObject[p] = true
    })

    createGoalsMutation.mutate(
      {
        tracking_mode: trackingMode,
        kcal_goal: trackingMode === 'mindful' ? null : kcalGoal,
        protein_goal: trackingMode === 'mindful' ? null : proteinGoal,
        fiber_goal: trackingMode === 'mindful' ? null : fiberGoal,
        dietary_prefs: prefsObject,
      },
      {
        onSuccess: () => {
          navigate('/chat')
        },
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

  const dietGoalOptions = [
    { label: 'Weight Loss (Calorie Deficit)', value: 'lose', desc: 'Accelerate fat loss with a healthy deficit' },
    { label: 'Weight Maintenance', value: 'maintain', desc: 'Keep your current weight and improve body composition' },
    { label: 'Weight Gain / Bulking', value: 'gain', desc: 'Support muscle synthesis with a safe surplus' },
  ]

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

  return (
    <div className="min-height-screen w-full bg-surface flex flex-col items-center justify-center p-4 md:p-8">
      <div className="w-full max-w-2xl">
        {/* Header branding */}
        <div className="flex flex-col items-center mb-8">
          <h1 className="font-display text-3xl text-sage-deep">
            Welcome to NutriChat
          </h1>
          <p className="text-sm text-muted mt-1">Let's calculate your custom nutrition goals</p>
        </div>

        {/* Progress Bar (goal-setting flow only) */}
        {step >= 1 && (
        <div className="flex items-center justify-between mb-8 px-4">
          <div className="flex-1 flex items-center">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold border transition-colors duration-200 ${
              step >= 1 ? 'bg-sage border-sage text-white' : 'bg-sand border-sand-border text-muted'
            }`}>1</div>
            <div className={`flex-1 h-0.5 mx-2 transition-colors duration-200 ${step >= 2 ? 'bg-sage' : 'bg-container'}`}></div>
          </div>
          <div className="flex-1 flex items-center">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold border transition-colors duration-200 ${
              step >= 2 ? 'bg-sage border-sage text-white' : 'bg-sand border-sand-border text-muted'
            }`}>2</div>
            <div className={`flex-1 h-0.5 mx-2 transition-colors duration-200 ${step >= 3 ? 'bg-sage' : 'bg-container'}`}></div>
          </div>
          <div className="flex-0">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold border transition-colors duration-200 ${
              step >= 3 ? 'bg-sage border-sage text-white' : 'bg-sand border-sand-border text-muted'
            }`}>3</div>
          </div>
        </div>
        )}

        {/* STEP 0: TRACKING MODE CHOICE */}
        {step === 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <button
              type="button"
              onClick={() => chooseMode('goals')}
              className="press text-left p-6 rounded-2xl border border-sand-border bg-sand hover:border-sage shadow-lg flex flex-col gap-3"
            >
              <div className="w-11 h-11 rounded-xl bg-gradient-to-tr from-sage to-sage-deep flex items-center justify-center">
                <Target className="w-5 h-5 text-white" />
              </div>
              <h3 className="font-display text-lg text-ink">Set goals</h3>
              <p className="text-[13px] text-muted leading-relaxed">
                I want daily targets for calories, protein & fiber, with progress
                rings and streaks.
              </p>
            </button>
            <button
              type="button"
              onClick={() => chooseMode('mindful')}
              className="press text-left p-6 rounded-2xl border border-sand-border bg-sand hover:border-sage shadow-lg flex flex-col gap-3"
            >
              <div className="w-11 h-11 rounded-xl bg-gradient-to-tr from-fiber to-warn flex items-center justify-center">
                <Leaf className="w-5 h-5 text-white" />
              </div>
              <h3 className="font-display text-lg text-ink">Mindful eating</h3>
              <p className="text-[13px] text-muted leading-relaxed">
                I want to track what I eat with no targets — just the amounts, plus
                safety alerts if I go over a healthy limit.
              </p>
            </button>
          </div>
        )}

        {step >= 1 && (
        <Card className="border border-sand-border shadow-2xl overflow-hidden bg-sand backdrop-blur-md">
          {/* STEP 1: PHYSICAL PROFILE */}
          {step === 1 && (
            <>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Dumbbell className="w-5 h-5 text-sage-deep" />
                  Step 1: Your Profile
                </CardTitle>
                <CardDescription>We use this to calculate your base metabolic rate and energy targets.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-muted mb-2">Biological Sex</label>
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
                      value={age}
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
                      value={weight}
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
                      value={height}
                      onChange={(e) => setHeight(Number(e.target.value))}
                      className="w-full bg-sand border border-sand-border rounded-xl px-4 py-2.5 text-sm text-ink focus:outline-none focus:ring-1 focus:ring-sage/30"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-muted mb-2">Daily Activity Level</label>
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

                <div>
                  <label className="block text-xs font-medium text-muted mb-2">Your Weight Goal</label>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {dietGoalOptions.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setDietGoal(opt.value as DietGoal)}
                        className={`p-3 rounded-xl border text-left flex flex-col gap-1 transition-all ${
                          dietGoal === opt.value
                            ? 'bg-container border-sage text-ink shadow-md'
                            : 'bg-sand border-sand-border text-muted hover:border-sand-border'
                        }`}
                      >
                        <span className="text-xs font-semibold text-ink">{opt.label}</span>
                        <span className="text-[10px] text-muted leading-normal">{opt.desc}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </CardContent>
            </>
          )}

          {/* STEP 2: GOAL CUSTOMIZATION */}
          {step === 2 && (
            <>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Flame className="w-5 h-5 text-sage-deep" />
                  Step 2: Recommended Goals
                </CardTitle>
                <CardDescription>Based on your profile, here are your calculated goals. Adjust as you see fit.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <GoalSlider
                  label="Daily Calories"
                  min={1000}
                  max={5000}
                  step={50}
                  value={kcalGoal}
                  unit="kcal"
                  onChange={setKcalGoal}
                  description="Your daily target for energy intake"
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
              </CardContent>
            </>
          )}

          {/* STEP 3: PREFERENCES & DIETARY CHIPS */}
          {step === 3 && (
            <>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Heart className="w-5 h-5 text-sage-deep" />
                  Step 3: Dietary Preferences
                </CardTitle>
                <CardDescription>Select any exclusions or dietary patterns to help personalize our coaching agent.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div>
                  <label className="block text-xs font-medium text-muted mb-3">Diet Types & Preferences</label>
                  <PreferenceChips
                    options={preferenceOptions}
                    selectedValues={dietaryPrefs}
                    onChange={setDietaryPrefs}
                  />
                </div>
                
                <div className="p-4 bg-surface/30 border border-sand-border rounded-2xl flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-container flex items-center justify-center flex-shrink-0 text-sage-deep font-bold text-sm">✓</div>
                  <div>
                    <h4 className="text-xs font-semibold text-ink">You are all set!</h4>
                    <p className="text-[11px] text-muted leading-normal mt-0.5">
                      Submitting will finalize your profile and direct you to the chat interface. You can adjust your targets at any time in settings.
                    </p>
                  </div>
                </div>
              </CardContent>
            </>
          )}

          {/* Card Actions */}
          <div className="px-6 py-4 bg-surface/50 border-t border-sand-border flex items-center justify-between">
            <Button
              type="button"
              variant="outline"
              onClick={handlePrevStep}
              disabled={step === 1}
              className={step === 1 ? 'opacity-0' : ''}
            >
              Back
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={handleNextStep}
              isLoading={createGoalsMutation.isPending}
            >
              {step === 3 ? 'Complete Setup' : 'Continue'}
            </Button>
          </div>
        </Card>
        )}
      </div>
    </div>
  )
}
