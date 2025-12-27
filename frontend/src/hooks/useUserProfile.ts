import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, ApiRequestError } from '../services/apiClient';
import type { User } from '../types';

/**
 * User profile update payload
 */
export interface UserProfileUpdate {
  user_id: string;
  name?: string;
  data_of_birth?: string;
  profession?: string;
}

/**
 * Hook to fetch user profile from backend
 * @param userId - User ID to fetch profile for
 * @returns React Query result with user data
 */
export function useUserProfile(userId: string) {
  return useQuery({
    queryKey: ['user', userId],
    queryFn: async () => {
      try {
        const response = await apiClient.get<User>(
          `/api/user/profile?user_id=${userId}`
        );
        return response;
      } catch (error) {
        if (error instanceof ApiRequestError && error.status === 404) {
          return null;
        }
        throw error;
      }
    },
    enabled: !!userId, // Only fetch if userId is provided
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}

/**
 * Hook to create user profile
 */
export function useCreateUserProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: UserProfileUpdate) => {
      const response = await apiClient.post<User>(
        '/api/user/profile',
        data
      );
      return response;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['user', data.user_id], data);
      queryClient.invalidateQueries({ queryKey: ['user'] });
      queryClient.invalidateQueries({
        queryKey: ['workflow', 'next-action', data.user_id],
      });
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
      const response = await apiClient.patch<User>(
        '/api/user/profile',
        data
      );
      return response;
    },
    onSuccess: (data) => {
      // Update cache with new data
      queryClient.setQueryData(['user', data.user_id], data);

      // Invalidate all user-related queries to refetch
      queryClient.invalidateQueries({ queryKey: ['user'] });

      // Invalidate workflow navigation for this user (profile completion changes state)
      queryClient.invalidateQueries({
        queryKey: ['workflow', 'next-action', data.user_id],
      });
    },
  });
}
