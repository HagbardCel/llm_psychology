import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type { Session } from '../types';

/**
 * Hook to fetch session history for a user
 * @param userId - User ID to fetch sessions for
 * @returns React Query result with session array
 */
export function useSessionHistory(userId: string, sessionId: string) {
  return useQuery({
    queryKey: ['sessions', userId, sessionId],
    queryFn: async () => {
      const response = await apiClient.get<Session[]>(
        `/api/sessions?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
      );
      return response;
    },
    enabled: !!userId && !!sessionId, // Only fetch if userId/sessionId are provided
    staleTime: 1000 * 60 * 2, // 2 minutes - sessions change less frequently
  });
}

/**
 * Hook to fetch a single session by ID
 * @param sessionId - Session ID to fetch
 * @returns React Query result with session data
 */
export function useSession(sessionId: string, userId: string, activeSessionId: string) {
  return useQuery({
    queryKey: ['session', sessionId, userId, activeSessionId],
    queryFn: async () => {
      const response = await apiClient.get<Session>(
        `/api/sessions/${sessionId}?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(activeSessionId)}`
      );
      return response;
    },
    enabled: !!sessionId && !!userId && !!activeSessionId, // Only fetch if all IDs are provided
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}
