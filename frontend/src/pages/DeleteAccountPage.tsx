import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { useDeleteAccount } from '../api/hooks'
import { ApiError } from '../api/client'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
import { ShieldAlert, Trash2 } from 'lucide-react'

const CONFIRM_WORD = 'DELETE'

const DELETED_ITEMS = [
  'Every meal you have logged',
  'Your daily and weekly nutrition goals',
  'Any meals you have saved for quick logging',
  'Coaching memories the assistant has stored about you',
  'Linked devices and push notification tokens',
  'Your login and account itself',
]

/**
 * Public account-deletion page, reachable at /account/delete without auth so
 * it can serve as the deletion URL required by Google Play's data-safety
 * form. Branches internally on the auth store instead of being wrapped in
 * the protected-route layout, since an unauthenticated visitor must still
 * see an explanation and a path to sign in.
 */
export const DeleteAccountPage: React.FC = () => {
  const { user, signOut } = useAuthStore()
  const deleteAccountMutation = useDeleteAccount()
  const [confirmText, setConfirmText] = useState('')
  const [deleted, setDeleted] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const isConfirmed = confirmText === CONFIRM_WORD

  const handleDelete = () => {
    if (!isConfirmed || deleteAccountMutation.isPending) return
    setErrorMessage(null)
    deleteAccountMutation.mutate(undefined, {
      onSuccess: () => {
        // Set the terminal "deleted" state before signing out. signOut()
        // synchronously clears `user` in the auth store, and the `deleted`
        // branch is checked before the `!user` branch below — flipping the
        // order would let the component briefly render the unauthenticated
        // "sign in to delete" card right after the account was deleted.
        // The account is already gone at this point regardless of whether
        // signOut() itself succeeds, so its outcome must not affect this
        // confirmation state or surface as an unhandled rejection.
        setDeleted(true)
        void signOut().catch((error) => {
          console.error('Sign out after account deletion failed', error)
        })
      },
      onError: (error) => {
        if (error instanceof ApiError && error.status === 502) {
          setErrorMessage(
            'Account deletion is temporarily unavailable — no data was deleted. Please try again later or contact support.'
          )
        } else {
          setErrorMessage('Something went wrong while deleting your account. Please try again.')
        }
        // Keep confirmText as-is so the user can retry without retyping DELETE.
      },
    })
  }

  if (deleted) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface p-4 min-h-screen">
        <Card className="max-w-md w-full border border-sand-border bg-sand backdrop-blur-md">
          <CardHeader>
            <CardTitle>Your account has been deleted</CardTitle>
            <CardDescription>
              All of your Mealsy data has been permanently removed. We're sorry to see you go.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link to="/login" className="text-sage-deep font-semibold underline">
              Return to sign in
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface p-4 min-h-screen">
        <Card className="max-w-md w-full border border-sand-border bg-sand backdrop-blur-md">
          <CardHeader>
            <CardTitle>Delete your Mealsy account</CardTitle>
            <CardDescription>
              Deleting your Mealsy account permanently removes your logged meals, nutrition
              goals, saved meals, coaching memories, linked devices, and your login itself. This
              cannot be undone.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted mb-4">
              Sign in to your account to request deletion.
            </p>
            <Link to="/login">
              <Button type="button" variant="primary" className="w-full">
                Sign in to delete your account
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex-1 flex items-center justify-center bg-surface p-4 min-h-screen">
      <Card className="max-w-md w-full border border-sand-border bg-sand backdrop-blur-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-danger">
            <ShieldAlert className="w-5 h-5" />
            Delete your account
          </CardTitle>
          <CardDescription>
            This permanently and irreversibly deletes the following for {user.email}:
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-xs">
          <ul className="list-disc list-inside space-y-1 text-ink-soft">
            {DELETED_ITEMS.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>

          {errorMessage && (
            <div className="bg-danger/10 border border-danger/30 text-danger p-3 rounded-xl">
              {errorMessage}
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="confirm-delete" className="block font-medium text-ink">
              Type {CONFIRM_WORD} to confirm
            </label>
            <input
              id="confirm-delete"
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="w-full rounded-xl border border-sand-border bg-container px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-danger/30"
              placeholder={CONFIRM_WORD}
              autoComplete="off"
            />
          </div>

          <Button
            type="button"
            variant="danger"
            className="w-full flex items-center justify-center gap-2"
            disabled={!isConfirmed}
            isLoading={deleteAccountMutation.isPending}
            onClick={handleDelete}
          >
            <Trash2 className="w-4 h-4" />
            Delete my account forever
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
