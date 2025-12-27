import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type { TherapyPlan } from '../types';

/**
 * Therapy plan creation payload
 */
export interface CreateTherapyPlanRequest {
  user_id: string;
  therapy_style: string;
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
      const response = await apiClient.get<TherapyPlan | null>(
        `/api/therapy/plan?user_id=${userId}`
      );
      return response;
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
      const response = await apiClient.post<TherapyPlan>(
        '/api/therapy/plan',
        {
          user_id: data.user_id,
          therapy_style: data.therapy_style,
        }
      );
      return response;
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
