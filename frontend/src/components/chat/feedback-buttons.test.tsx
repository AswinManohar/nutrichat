// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mutateAsync = vi.fn()

vi.mock('../../hooks/use-coaching-feedback', () => ({
  useCoachingFeedback: () => ({ mutateAsync, isPending: false }),
}))

const { FeedbackButtons } = await import('./feedback-buttons')

/** Typed accessor so `.disabled` is available without jest-dom matchers. */
const button = (name: string) => screen.getByRole('button', { name }) as HTMLButtonElement

describe('FeedbackButtons', () => {
  beforeEach(() => {
    mutateAsync.mockReset()
    mutateAsync.mockResolvedValue({ response_id: 'r1', rating: 'up' })
  })
  afterEach(cleanup)

  it('posts an up rating and disables both buttons once rated', async () => {
    render(<FeedbackButtons responseId="r1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Helpful' }))

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ responseId: 'r1', rating: 'up' }),
    )
    await waitFor(() => {
      expect(button('Helpful').disabled).toBe(true)
      expect(button('Not helpful').disabled).toBe(true)
    })
    expect(screen.queryByPlaceholderText('What was off? (optional)')).toBeNull()
  })

  it('posts a down rating, reveals the comment box, and posts again with the comment', async () => {
    mutateAsync.mockResolvedValue({ response_id: 'r1', rating: 'down' })
    render(<FeedbackButtons responseId="r1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Not helpful' }))

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ responseId: 'r1', rating: 'down' }),
    )
    const input = await screen.findByPlaceholderText('What was off? (optional)')
    fireEvent.change(input, { target: { value: 'wrong protein number' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenLastCalledWith({
        responseId: 'r1',
        rating: 'down',
        comment: 'wrong protein number',
      }),
    )
    await waitFor(() =>
      expect(screen.queryByPlaceholderText('What was off? (optional)')).toBeNull(),
    )
    expect(screen.getByText('Thanks for the feedback.')).toBeTruthy()
  })

  it('ignores a second Send click while the comment request is in flight', async () => {
    let resolveComment: (value: unknown) => void = () => {}
    mutateAsync
      .mockResolvedValueOnce({ response_id: 'r1', rating: 'down' })
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveComment = resolve
          }),
      )
    render(<FeedbackButtons responseId="r1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Not helpful' }))
    const input = await screen.findByPlaceholderText('What was off? (optional)')
    fireEvent.change(input, { target: { value: 'wrong protein number' } })

    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(button('Send').disabled).toBe(true))
    fireEvent.click(button('Send'))
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(mutateAsync).toHaveBeenCalledTimes(2) // the rating + one comment

    resolveComment({ response_id: 'r1', rating: 'down' })
    await waitFor(() =>
      expect(screen.queryByPlaceholderText('What was off? (optional)')).toBeNull(),
    )
    expect(mutateAsync).toHaveBeenCalledTimes(2)
  })

  it('shows an error and re-enables the buttons when the request fails', async () => {
    mutateAsync.mockRejectedValue(new Error('network'))
    render(<FeedbackButtons responseId="r1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Helpful' }))

    expect(await screen.findByText("Couldn't send feedback. Try again.")).toBeTruthy()
    expect(button('Helpful').disabled).toBe(false)
    expect(button('Not helpful').disabled).toBe(false)
  })
})
