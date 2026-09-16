import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const signOut = vi.fn()
const mutate = vi.fn()

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    user: { id: 'user-1', email: 'eater@mealsy.local' },
    signOut,
  }),
}))

vi.mock('../api/hooks', () => ({
  useDeleteAccount: () => ({
    mutate,
    isPending: false,
  }),
}))

const { DeleteAccountPage } = await import('./DeleteAccountPage')

describe('DeleteAccountPage confirmation gating', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    cleanup()
  })

  function renderPage() {
    render(
      <MemoryRouter>
        <DeleteAccountPage />
      </MemoryRouter>
    )
  }

  it('disables the delete button until DELETE is typed exactly', () => {
    renderPage()
    const button = screen.getByRole('button', { name: /delete my account forever/i })
    expect(button).toBeDisabled()

    const input = screen.getByLabelText(/type delete to confirm/i)
    fireEvent.change(input, { target: { value: 'delete' } })
    expect(button).toBeDisabled()

    fireEvent.change(input, { target: { value: 'DELETe' } })
    expect(button).toBeDisabled()
  })

  it('enables the delete button once DELETE is typed exactly', () => {
    renderPage()
    const input = screen.getByLabelText(/type delete to confirm/i)
    fireEvent.change(input, { target: { value: 'DELETE' } })

    const button = screen.getByRole('button', { name: /delete my account forever/i })
    expect(button).not.toBeDisabled()
  })

  it('does not call the mutation while the button is disabled', () => {
    renderPage()
    const button = screen.getByRole('button', { name: /delete my account forever/i })
    fireEvent.click(button)
    expect(mutate).not.toHaveBeenCalled()
  })

  it('calls the mutation once confirmed and the button is clicked', () => {
    renderPage()
    const input = screen.getByLabelText(/type delete to confirm/i)
    fireEvent.change(input, { target: { value: 'DELETE' } })

    const button = screen.getByRole('button', { name: /delete my account forever/i })
    fireEvent.click(button)
    expect(mutate).toHaveBeenCalledOnce()
  })
})
