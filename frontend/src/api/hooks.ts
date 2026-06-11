import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, ApiError } from './client'
import type { DayTrend, LogMealRequest, LogMealResponse, TodayTotals, GoalData } from './types'

export const useTrends = (days = 91) => {
  return useQuery<DayTrend[], Error>({
    queryKey: ['trends', days],
    queryFn: () => apiClient.get<DayTrend[]>(`/meals/trends?days=${days}`),
    staleTime: 60_000,
  })
}

export const useDashboard = () => {
  return useQuery<TodayTotals, Error>({
    queryKey: ['dashboard', 'today'],
    queryFn: () => apiClient.get<TodayTotals>('/meals/today'),
    refetchInterval: 30000, // auto refetch every 30 seconds
  })
}

export const useGoals = () => {
  return useQuery<GoalData, ApiError>({
    queryKey: ['goals'],
    queryFn: () => apiClient.get<GoalData>('/goals'),
    retry: (failureCount, error) => {
      // If we get a 404 (not onboarded), don't retry, just fail so we can route to onboarding
      if (error.status === 404 || error.message.includes('not onboarded') || error.message.includes('404')) {
        return false
      }
      return failureCount < 3
    },
  })
}

export const useCreateGoals = () => {
  const queryClient = useQueryClient()
  return useMutation<GoalData, Error, GoalData>({
    mutationFn: (newGoals) => apiClient.post<GoalData>('/goals', newGoals),
    onSuccess: (data) => {
      queryClient.setQueryData(['goals'], data)
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

export const useUpdateGoals = () => {
  const queryClient = useQueryClient()
  return useMutation<GoalData, Error, GoalData>({
    mutationFn: (updatedGoals) => apiClient.put<GoalData>('/goals', updatedGoals),
    onSuccess: (data) => {
      queryClient.setQueryData(['goals'], data)
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

export const useLogMeal = () => {
  const queryClient = useQueryClient()
  return useMutation<LogMealResponse, Error, LogMealRequest>({
    mutationFn: (req) => apiClient.post<LogMealResponse>('/meals/log', req),
    onSuccess: (data) => {
      // If the meal logging succeeded and is NOT paused (confirmed/logged),
      // we invalidate the dashboard data to trigger macro ring updates
      if (!data.paused) {
        queryClient.invalidateQueries({ queryKey: ['dashboard', 'today'] })
      }
    },
  })
}
