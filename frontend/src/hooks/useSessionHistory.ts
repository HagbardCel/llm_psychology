import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type { Session } from '../types';

/**
 * Hook to fetch session history for a user
 * @param userId - User ID to fetch sessions for
 * @returns React Query result with session array
 */
export function useSessionHistory(userId: string) {
  return useQuery({
    queryKey: ['sessions', userId],
    queryFn: async () => {
      const response = await apiClient.get<Session[]>(
        `/api/sessions?user_id=${userId}`
      );
      return response;
    },
    enabled: !!userId, // Only fetch if userId is provided
    staleTime: 1000 * 60 * 2, // 2 minutes - sessions change less frequently
  });
}

/**
 * Hook to fetch a single session by ID
 * @param sessionId - Session ID to fetch
 * @returns React Query result with session data
 */
export function useSession(sessionId: string) {
  return useQuery({
    queryKey: ['session', sessionId],
    queryFn: async () => {
      const response = await apiClient.get<Session>(
        `/api/sessions/${sessionId}`
      );
      return response;
    },
    enabled: !!sessionId, // Only fetch if sessionId is provided
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}
