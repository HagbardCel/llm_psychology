import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiRequestError } from '../services/apiClient';
import type { CreateUserProfileRequest, User, UserRegisterResponse, WorkflowNextAction } from '../types';

/**
 * User profile update payload
 */
export interface UserProfileUpdate {
  user_id: string;
  session_id: string;
  name?: string;
  data_of_birth?: string;
  profession?: string;
  primary_language?: string;
  session_mode?: string;
}

export interface WorkflowProfileRequest extends UserProfileUpdate {
  session_id: string;
}

/**
 * Hook to fetch user profile from backend
 * @param userId - User ID to fetch profile for
 * @returns React Query result with user data
 */
export function useUserProfile(userId: string, sessionId: string) {
  return useQuery({
    queryKey: ['user', userId, sessionId],
    queryFn: async () => {
      try {
        const response = await apiClient.get<User>(
          `/api/user/profile?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
        );
        return response;
      } catch (error) {
        if (error instanceof ApiRequestError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },
    enabled: !!userId && !!sessionId, // Only fetch if userId/sessionId are provided
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}

/**
 * Hook to create user profile
 */
export function useCreateUserProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: WorkflowProfileRequest) => {
      if (!data.session_id) {
        throw new Error('Session ID is required to complete profile');
      }
      const response = await apiClient.post<WorkflowNextAction>(
        '/api/workflow/complete_profile',
        data
      );
      return response;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['user', variables.user_id] });
      queryClient.invalidateQueries({
        queryKey: ['workflow', 'next', variables.user_id, variables.session_id],
      });
    },
  });
}

/**
 * Hook to register a user profile and receive session info.
 */
export function useRegisterUserProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: CreateUserProfileRequest) => {
      const response = await apiClient.post<UserRegisterResponse>(
        '/api/user/register',
        data
      );
      return response;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['user', data.session.user_id] });
    },
  });
}

/**
 * Hook to update user profile
 * Automatically invalidates and refetches user data after successful update
 */
export function useUpdateUserProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: UserProfileUpdate) => {
      if (!data.session_id) {
        throw new Error('Session ID is required to update profile');
      }
      const response = await apiClient.patch<User>(
        '/api/user/profile',
        data
      );
      return response;
    },
    onSuccess: (data) => {
      // Update cache with new data
      queryClient.setQueryData(['user', data.user_id, data.session_id], data);

      // Invalidate all user-related queries to refetch
      queryClient.invalidateQueries({ queryKey: ['user'] });

      // Invalidate workflow navigation for this user (profile completion changes state)
      queryClient.invalidateQueries({
        queryKey: ['workflow', 'next', data.user_id, data.session_id],
      });
    },
  });
}
