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
interface WorkflowNavigationOptions {
  enabled?: boolean;
}

export function useWorkflowNextAction(
  userId: string,
  sessionId: string,
  _currentRoute?: string,
  options: WorkflowNavigationOptions = {}
) {
  return useQuery({
    queryKey: ['workflow', 'next', userId, sessionId],
    queryFn: async () => {
      const response = await apiClient.get<WorkflowNextAction>(
        `/api/workflow/next?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
      );
      return response;
    },
    enabled: !!userId && !!sessionId && (options.enabled ?? true), // Only fetch if userId/sessionId are provided and gate enabled
    staleTime: 0, // Always check for workflow changes - no caching
    gcTime: 1000 * 60, // Keep in memory for 1 minute after becoming inactive
    refetchOnMount: true, // Always refetch when component mounts
    refetchOnWindowFocus: true, // Refetch when user returns to tab
  });
}
