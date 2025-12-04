import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type { WorkflowNextAction } from '../types';

/**
 * Hook to fetch the next workflow action from backend
 * This is the core of backend-driven navigation - the backend tells
 * the frontend what to display and where to navigate next.
 *
 * @param userId - User ID to get workflow action for
 * @param currentRoute - Current route the user is on
 * @returns React Query result with next action instructions
 */
export function useWorkflowNextAction(userId: string, currentRoute: string) {
  return useQuery({
    queryKey: ['workflow', 'next-action', userId, currentRoute],
    queryFn: async () => {
      const response = await apiClient.post<WorkflowNextAction>(
        '/api/workflow/next-action',
        {
          user_id: userId,
          current_route: currentRoute,
        }
      );
      return response;
    },
    enabled: !!userId, // Only fetch if userId is provided
    staleTime: 0, // Always check for workflow changes - no caching
    gcTime: 1000 * 60, // Keep in memory for 1 minute after becoming inactive
    refetchOnMount: true, // Always refetch when component mounts
    refetchOnWindowFocus: true, // Refetch when user returns to tab
  });
}
