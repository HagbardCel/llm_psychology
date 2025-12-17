import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../services/apiClient';
import type { User } from '../types';

/**
 * User profile data structure from backend
 */
interface UserProfileResponse {
  user_id: string;
  name: string;
  email?: string;
  birthdate?: string;
  profession?: string;
  status: string;
  created_at: string;
  updated_at: string;
}

/**
 * User profile update payload
 */
export interface UserProfileUpdate {
  user_id: string;
  name?: string;
  email?: string;
  birthdate?: string;
  profession?: string;
}

/**
 * Transform backend response to frontend User type
 */
function transformUserProfile(data: UserProfileResponse): User {
  return {
    id: data.user_id,
    name: data.name,
    email: data.email,
    birthdate: data.birthdate,
    profession: data.profession,
    status: data.status as any, // UserStatus enum
    createdAt: new Date(data.created_at),
    lastActiveAt: new Date(data.updated_at),
  };
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
      const response = await apiClient.get<UserProfileResponse>(
        `/api/user/profile?user_id=${userId}`
      );
      return transformUserProfile(response);
    },
    enabled: !!userId, // Only fetch if userId is provided
    staleTime: 1000 * 60 * 5, // 5 minutes
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
      const response = await apiClient.post<UserProfileResponse>(
        '/api/user/profile',
        data
      );
      return transformUserProfile(response);
    },
    onSuccess: (data) => {
      // Update cache with new data
      queryClient.setQueryData(['user', data.id], data);

      // Invalidate all user-related queries to refetch
      queryClient.invalidateQueries({ queryKey: ['user'] });

      // Invalidate workflow navigation for this user (profile completion changes state)
      queryClient.invalidateQueries({ queryKey: ['workflow', 'next-action', data.id] });
    },
  });
}
