import React, { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ArrowLeft, Star, Check } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { useQuota, useUpgradeQuota } from '../api/hooks'

const FREE_FEATURES = ['Meal logging', 'AI coaching', 'Meal history']
const PRO_FEATURES = ['Everything free', '3× more requests', 'Priority access']

export const UpgradePage: React.FC = () => {
  const navigate = useNavigate()
  const { data: quota } = useQuota()
  const upgradeMutation = useUpgradeQuota()
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const isPaid = quota?.tier === 'paid'

  useEffect(() => {
    if (!successMsg) return
    const id = setTimeout(() => navigate('/settings'), 1500)
    return () => clearTimeout(id)
  }, [successMsg, navigate])

  const handleUpgrade = () => {
    setErrorMsg(null)
    upgradeMutation.mutate(undefined, {
      onSuccess: () => setSuccessMsg("You're now on Pro!"),
      onError: () => setErrorMsg('Something went wrong. Try again.'),
    })
  }

  return (
    <div className="flex-1 overflow-y-auto bg-surface p-4 md:p-8">
      <div className="max-w-2xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-sand-border pb-5">
          <Link
            to="/settings"
            className="text-muted hover:text-ink transition-colors flex items-center gap-1.5 text-sm"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Settings
          </Link>
        </div>

        <div>
          <h1 className="font-display font-bold text-xl text-ink">Choose your plan</h1>
          <p className="text-xs text-muted mt-1">Lifetime AI requests — never reset</p>
        </div>

        {/* Status banners */}
        {isPaid && !successMsg && (
          <div className="bg-container border border-sage/30 text-sage-deep text-xs p-3 rounded-xl">
            You're already on the Pro plan.
          </div>
        )}
        {successMsg && (
          <div className="bg-container border border-sage/30 text-sage-deep text-xs p-3 rounded-xl flex items-center gap-2">
            <Star className="w-4 h-4" />
            {successMsg}
          </div>
        )}
        {errorMsg && (
          <div className="bg-danger/10 border border-danger/30 text-danger text-xs p-3 rounded-xl">
            {errorMsg}
          </div>
        )}

        {/* Tier cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Free tier */}
          <Card className="border border-sand-border bg-sand backdrop-blur-md">
            <CardHeader>
              <CardTitle>Free</CardTitle>
              <CardDescription>50 AI requests · lifetime</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <ul className="space-y-2">
                {FREE_FEATURES.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-ink-soft">
                    <Check className="w-3.5 h-3.5 text-sage-deep shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <div>
                <p className="text-2xl font-display font-bold text-ink">
                  — <span className="text-sm font-normal text-muted">/ mo</span>
                </p>
                <p className="text-xs text-muted mt-0.5">Pricing coming soon</p>
              </div>
              <Button
                type="button"
                variant="outline"
                className="w-full"
                disabled
              >
                {isPaid ? 'Free' : 'Current plan'}
              </Button>
            </CardContent>
          </Card>

          {/* Pro tier */}
          <Card className="border border-sage/40 bg-sand backdrop-blur-md">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Pro</CardTitle>
                <span className="flex items-center gap-1 text-xs text-sage-deep font-medium bg-sage/10 px-2 py-0.5 rounded-full">
                  <Star className="w-3 h-3" />
                  {isPaid ? 'Current plan' : 'Best'}
                </span>
              </div>
              <CardDescription>150 AI requests · lifetime</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <ul className="space-y-2">
                {PRO_FEATURES.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-ink-soft">
                    <Check className="w-3.5 h-3.5 text-sage-deep shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <div>
                <p className="text-2xl font-display font-bold text-ink">
                  — <span className="text-sm font-normal text-muted">/ mo</span>
                </p>
                <p className="text-xs text-muted mt-0.5">Pricing coming soon</p>
              </div>
              <Button
                type="button"
                variant="primary"
                className="w-full"
                disabled={!quota || isPaid || upgradeMutation.isPending}
                isLoading={upgradeMutation.isPending}
                onClick={handleUpgrade}
              >
                {isPaid ? 'Current plan' : 'Upgrade now'}
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
