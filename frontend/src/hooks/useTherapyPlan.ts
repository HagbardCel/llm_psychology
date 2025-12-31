import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type { TherapyPlan, WorkflowNextAction } from '../types';

/**
 * Therapy plan creation payload
 */
export interface SelectTherapyStyleRequest {
  user_id: string;
  session_id: string;
  selected_therapy_style: string;
}

/**
 * Hook to fetch therapy plan for a user
 * @param userId - User ID to fetch therapy plan for
 * @returns React Query result with therapy plan data
 */
export function useTherapyPlan(userId: string, sessionId: string) {
  return useQuery({
    queryKey: ['therapyPlan', userId, sessionId],
    queryFn: async () => {
      const response = await apiClient.get<TherapyPlan | null>(
        `/api/therapy/plan?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
      );
      return response;
    },
    enabled: !!userId && !!sessionId, // Only fetch if userId/sessionId are provided
    staleTime: 1000 * 60 * 10, // 10 minutes - therapy plans change infrequently
  });
}

/**
 * Hook to create a new therapy plan
 * Automatically invalidates user and therapy plan queries after successful creation
 */
export function useSelectTherapyStyle() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: SelectTherapyStyleRequest) => {
      if (!data.session_id) {
        throw new Error('Session ID is required to select therapy style');
      }
      const response = await apiClient.post<WorkflowNextAction>(
        '/api/workflow/select_therapy_style',
        data
      );
      return response;
    },
    onSuccess: (_data, variables) => {
      // Therapy plan is created server-side; refetch after selection.
      queryClient.invalidateQueries({
        queryKey: ['therapyPlan', variables.user_id, variables.session_id],
      });

      // Invalidate user query to refetch updated user status
      queryClient.invalidateQueries({ queryKey: ['user', variables.user_id] });

      // Invalidate workflow query to get updated navigation
      queryClient.invalidateQueries({
        queryKey: ['workflow', 'next', variables.user_id, variables.session_id]
      });
    },
  });
}
