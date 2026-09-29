import { useMutation } from '@tanstack/react-query'

import { apiClient, ApiError } from '../api/client'

export interface CoachingFeedbackInput {
  responseId: string
  rating: 'up' | 'down'
  comment?: string
}

export interface CoachingFeedbackResponse {
  response_id: string
  rating: 'up' | 'down'
}

/** Rate a coaching reply. Errors are ApiError; callers surface them inline. */
export function useCoachingFeedback() {
  return useMutation<CoachingFeedbackResponse, ApiError, CoachingFeedbackInput>({
    mutationFn: ({ responseId, rating, comment }) =>
      apiClient.post<CoachingFeedbackResponse>(
        `/coaching/${responseId}/feedback`,
        comment ? { rating, comment } : { rating },
      ),
  })
}
