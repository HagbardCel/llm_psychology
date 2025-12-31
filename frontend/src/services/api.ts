/**
 * Type-safe API methods for all backend endpoints
 * Uses the underlying apiClient for actual HTTP calls
 */

import { apiClient } from './apiClient';
import {
  CreateSessionRequest,
  WorkflowCompleteProfileRequest,
  HealthCheckResponse,
  PatchUserProfileRequest,
  Session,
  StatusMessageResponse,
  TherapyPlan,
  TherapyStyleInfo,
  User,
  UserRegisterResponse,
  UserStatusResponse,
  WorkflowNextAction,
  WorkflowSelectTherapyStyleRequest
} from '../types';

/**
 * User API
 */
export const userApi = {
  async register(data: CreateUserProfileRequest): Promise<UserRegisterResponse> {
    return apiClient.post('/api/user/register', data);
  },

  async getStatus(userId: string, sessionId: string): Promise<UserStatusResponse> {
    return apiClient.get(
      `/api/user/status?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
    );
  },

  async createProfile(data: WorkflowCompleteProfileRequest): Promise<WorkflowNextAction> {
    return apiClient.post('/api/workflow/complete_profile', data);
  },

  async updateProfile(data: PatchUserProfileRequest): Promise<User> {
    return apiClient.patch('/api/user/profile', data);
  }
};

/**
 * Session API
 */
export const sessionApi = {
  async getSessions(userId: string, sessionId: string): Promise<Session[]> {
    return apiClient.get(
      `/api/sessions?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
    );
  },

  async getSession(sessionId: string, userId: string, activeSessionId: string): Promise<Session> {
    return apiClient.get(
      `/api/sessions/${sessionId}?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(activeSessionId)}`
    );
  },

  async createSession(data: CreateSessionRequest): Promise<Session> {
    return apiClient.post('/api/sessions', data);
  },

  async extendSession(
    sessionId: string,
    userId: string,
    activeSessionId: string
  ): Promise<StatusMessageResponse> {
    return apiClient.post(
      `/api/sessions/${sessionId}/extend?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(activeSessionId)}`
    );
  }
};

/**
 * Therapy API
 */
export const therapyApi = {
  async getStyles(userId: string, sessionId: string): Promise<TherapyStyleInfo[]> {
    return apiClient.get(
      `/api/therapy/styles?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
    );
  },

  async getPlan(userId: string, sessionId: string): Promise<TherapyPlan | null> {
    return apiClient.get(
      `/api/therapy/plan?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
    );
  },

  async selectStyle(data: WorkflowSelectTherapyStyleRequest): Promise<WorkflowNextAction> {
    return apiClient.post('/api/workflow/select_therapy_style', data);
  }
};

/**
 * Workflow API (NEW - Phase 1)
 */
export const workflowApi = {
  async getNextAction(userId: string, sessionId: string): Promise<WorkflowNextAction> {
    return apiClient.get(
      `/api/workflow/next?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`
    );
  }
};

/**
 * Health check API
 */
export const healthApi = {
  async check(): Promise<HealthCheckResponse> {
    return apiClient.get('/health');
  }
};

// Export combined API object
export const api = {
  user: userApi,
  session: sessionApi,
  therapy: therapyApi,
  workflow: workflowApi,
  health: healthApi
};
