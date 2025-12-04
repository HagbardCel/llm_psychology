import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type { Session } from '../types';

/**
 * Session data structure from backend
 */
interface SessionResponse {
  session_id: string;
  user_id: string;
  agent_type: string;
  therapy_style?: string;
  status: string;
  start_time: string;
  end_time?: string;
  transcript?: Array<{
    role: string;
    content: string;
    timestamp: string;
  }>;
  topics?: Array<{
    name: string;
    status: string;
  }>;
  metadata?: Record<string, any>;
}

/**
 * Transform backend session response to frontend Session type
 */
function transformSession(data: SessionResponse): Session {
  return {
    id: data.session_id,
    userId: data.user_id,
    agentType: data.agent_type as any, // AgentType enum
    therapyStyle: data.therapy_style as any, // TherapyStyle enum
    status: data.status as any, // SessionStatus enum
    startTime: new Date(data.start_time),
    endTime: data.end_time ? new Date(data.end_time) : undefined,
    transcript: data.transcript?.map((msg) => ({
      id: `${data.session_id}-${msg.timestamp}`,
      content: msg.content,
      role: msg.role as 'user' | 'assistant',
      timestamp: new Date(msg.timestamp),
      sessionId: data.session_id,
    })) || [],
    topics: data.topics?.map((topic) => ({
      name: topic.name,
      status: topic.status as 'pending' | 'covered' | 'partially_covered',
    })) || [],
    metadata: data.metadata,
  };
}

/**
 * Hook to fetch session history for a user
 * @param userId - User ID to fetch sessions for
 * @returns React Query result with session array
 */
export function useSessionHistory(userId: string) {
  return useQuery({
    queryKey: ['sessions', userId],
    queryFn: async () => {
      const response = await apiClient.get<SessionResponse[]>(
        `/api/sessions?user_id=${userId}`
      );
      return response.map(transformSession);
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
      const response = await apiClient.get<SessionResponse>(
        `/api/sessions/${sessionId}`
      );
      return transformSession(response);
    },
    enabled: !!sessionId, // Only fetch if sessionId is provided
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}
