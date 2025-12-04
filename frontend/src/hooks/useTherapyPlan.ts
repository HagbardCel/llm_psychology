import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type { TherapyPlan, TherapyStyle } from '../types';

/**
 * Therapy plan data structure from backend
 */
interface TherapyPlanResponse {
  plan_id: string;
  user_id: string;
  therapy_style: string;
  goals: string[];
  session_count: number;
  created_at: string;
  updated_at: string;
}

/**
 * Therapy plan creation payload
 */
export interface CreateTherapyPlanRequest {
  user_id: string;
  therapy_style: string;
}

/**
 * Transform backend therapy plan response to frontend TherapyPlan type
 */
function transformTherapyPlan(data: TherapyPlanResponse): TherapyPlan {
  return {
    id: data.plan_id,
    userId: data.user_id,
    therapyStyle: data.therapy_style as TherapyStyle,
    goals: data.goals,
    sessionCount: data.session_count,
    createdAt: new Date(data.created_at),
    updatedAt: new Date(data.updated_at),
  };
}

/**
 * Hook to fetch therapy plan for a user
 * @param userId - User ID to fetch therapy plan for
 * @returns React Query result with therapy plan data
 */
export function useTherapyPlan(userId: string) {
  return useQuery({
    queryKey: ['therapyPlan', userId],
    queryFn: async () => {
      const response = await apiClient.get<TherapyPlanResponse>(
        `/api/therapy/plan?user_id=${userId}`
      );
      return transformTherapyPlan(response);
    },
    enabled: !!userId, // Only fetch if userId is provided
    staleTime: 1000 * 60 * 10, // 10 minutes - therapy plans change infrequently
  });
}

/**
 * Hook to create a new therapy plan
 * Automatically invalidates user and therapy plan queries after successful creation
 */
export function useCreateTherapyPlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateTherapyPlanRequest) => {
      const response = await apiClient.post<TherapyPlanResponse>(
        '/api/therapy/plan',
        {
          user_id: data.user_id,
          therapy_style: data.therapy_style,
        }
      );
      return transformTherapyPlan(response);
    },
    onSuccess: (data, variables) => {
      // Update cache with new therapy plan
      queryClient.setQueryData(['therapyPlan', variables.user_id], data);

      // Invalidate user query to refetch updated user status
      queryClient.invalidateQueries({ queryKey: ['user', variables.user_id] });

      // Invalidate workflow query to get updated navigation
      queryClient.invalidateQueries({
        queryKey: ['workflow', 'next-action', variables.user_id]
      });
    },
  });
}
