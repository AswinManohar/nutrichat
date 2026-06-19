import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, ApiError } from './client'
import type {
  CategoryStat,
  DayTrend,
  LogMealRequest,
  LogMealResponse,
  LogMyMealRequest,
  LogMyMealResponse,
  MindfulDay,
  MyMealDetail,
  MyMealSummary,
  SaveMealRequest,
  TodayTotals,
  GoalData,
  NutrientCheckupResponse,
  PendingNudgeResponse,
  TelegramLinkCode,
  TelegramLinkStatus,
} from './types'

export const useMyMeals = () => {
  return useQuery<MyMealSummary[], Error>({
    queryKey: ['my-meals'],
    queryFn: () => apiClient.get<MyMealSummary[]>('/my-meals'),
    staleTime: 30_000,
  })
}

export const useSaveMeal = () => {
  const queryClient = useQueryClient()
  return useMutation<MyMealDetail, ApiError, SaveMealRequest>({
    mutationFn: (req) => apiClient.post<MyMealDetail>('/my-meals', req),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['my-meals'] }),
  })
}

export const useDeleteMeal = () => {
  const queryClient = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: (id) => apiClient.delete<void>(`/my-meals/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['my-meals'] }),
  })
}

/** Fetch a saved meal's full ingredient breakdown (for the Customize editor). */
export const useMyMeal = (id: string, enabled: boolean) => {
  return useQuery<MyMealDetail, Error>({
    queryKey: ['my-meals', id],
    queryFn: () => apiClient.get<MyMealDetail>(`/my-meals/${id}`),
    enabled,
    staleTime: 30_000,
  })
}

/** Log a saved meal directly (quick-log at 1x, or customized). */
export const useLogMyMeal = (mealId: string) => {
  const queryClient = useQueryClient()
  return useMutation<LogMyMealResponse, ApiError, LogMyMealRequest>({
    mutationFn: (req) =>
      apiClient.post<LogMyMealResponse>(`/my-meals/${mealId}/log`, req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'today'] })
      queryClient.invalidateQueries({ queryKey: ['trends'] })
      queryClient.invalidateQueries({ queryKey: ['meal-categories'] })
    },
  })
}

export const useMindfulToday = () => {
  return useQuery<MindfulDay, Error>({
    queryKey: ['mindful-today'],
    queryFn: () => apiClient.get<MindfulDay>('/mindful/today'),
    staleTime: 30_000,
  })
}

export const useTrends = (days = 91) => {
  return useQuery<DayTrend[], Error>({
    queryKey: ['trends', days],
    queryFn: () => apiClient.get<DayTrend[]>(`/meals/trends?days=${days}`),
    staleTime: 60_000,
  })
}

export const useCategoryBreakdown = (days = 30) => {
  return useQuery<CategoryStat[], Error>({
    queryKey: ['meal-categories', days],
    queryFn: () => apiClient.get<CategoryStat[]>(`/meals/categories?days=${days}`),
    staleTime: 60_000,
  })
}

export const useNutrientCheckup = () => {
  return useQuery<NutrientCheckupResponse, ApiError>({
    queryKey: ['nutrient-checkup'],
    queryFn: () => apiClient.get<NutrientCheckupResponse>('/nutrient-checkup'),
    staleTime: 60_000,
    retry: (failureCount, error) => {
      // 404 means build_nutrient_checkup hasn't run for this user yet
      if (error.status === 404) return false
      return failureCount < 3
    },
  })
}

export const usePendingNudge = () => {
  return useQuery<PendingNudgeResponse, ApiError>({
    queryKey: ['nutrient-checkup', 'pending-nudge'],
    queryFn: () => apiClient.get<PendingNudgeResponse>('/nutrient-checkup/pending-nudge'),
    staleTime: Infinity,
    retry: (failureCount, error) => {
      if (error.status === 404) return false
      return failureCount < 3
    },
  })
}

export const useAckPendingNudge = () => {
  return useMutation<void, Error, void>({
    mutationFn: () => apiClient.post<void>('/nutrient-checkup/pending-nudge/ack'),
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

export const useTelegramLinkStatus = () => {
  return useQuery<TelegramLinkStatus, ApiError>({
    queryKey: ['telegram', 'link'],
    queryFn: () => apiClient.get<TelegramLinkStatus>('/telegram/link'),
  })
}

export const useGenerateTelegramLinkCode = () => {
  return useMutation<TelegramLinkCode, Error, void>({
    mutationFn: () => apiClient.post<TelegramLinkCode>('/telegram/link-code'),
  })
}

export const useDisconnectTelegram = () => {
  const queryClient = useQueryClient()
  return useMutation<void, Error, void>({
    mutationFn: () => apiClient.delete<void>('/telegram/link'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['telegram', 'link'] })
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
