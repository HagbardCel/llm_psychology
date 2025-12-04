/**
 * Type-safe API methods for all backend endpoints
 * Uses the underlying apiClient for actual HTTP calls
 */

import { apiClient } from './apiClient';
import {
  User,
  Session,
  TherapyPlan,
  TherapyStyleInfo,
  WorkflowNextAction
} from '../types';

export interface CreateUserProfileRequest {
  user_id: string;
  name: string;
  birthdate?: string;
  profession?: string;
}

export interface CreateSessionRequest {
  user_id: string;
}

export interface CreateTherapyPlanRequest {
  user_id: string;
  therapy_style: string;
}

export interface WorkflowNextActionRequest {
  user_id: string;
  current_route?: string;
}

export interface HealthCheckResponse {
  status: string;
  timestamp: string;
  database: string;
}

/**
 * User API
 */
export const userApi = {
  async getStatus(userId: string): Promise<{ user_id: string; workflow_state: string; timestamp: string }> {
    return apiClient.get(`/api/user/status?user_id=${encodeURIComponent(userId)}`);
  },

  async createProfile(data: CreateUserProfileRequest): Promise<User> {
    return apiClient.post('/api/user/profile', data);
  }
};

/**
 * Session API
 */
export const sessionApi = {
  async getSessions(userId: string): Promise<Session[]> {
    return apiClient.get(`/api/sessions?user_id=${encodeURIComponent(userId)}`);
  },

  async getSession(sessionId: string): Promise<Session> {
    return apiClient.get(`/api/sessions/${sessionId}`);
  },

  async createSession(data: CreateSessionRequest): Promise<Session> {
    return apiClient.post('/api/sessions', data);
  },

  async extendSession(sessionId: string): Promise<void> {
    return apiClient.post(`/api/sessions/${sessionId}/extend`);
  }
};

/**
 * Therapy API
 */
export const therapyApi = {
  async getStyles(): Promise<TherapyStyleInfo[]> {
    return apiClient.get('/api/therapy/styles');
  },

  async getPlan(userId: string): Promise<TherapyPlan | null> {
    return apiClient.get(`/api/therapy/plan?user_id=${encodeURIComponent(userId)}`);
  },

  async createPlan(data: CreateTherapyPlanRequest): Promise<TherapyPlan> {
    return apiClient.post('/api/therapy/plan', data);
  }
};

/**
 * Workflow API (NEW - Phase 1)
 */
export const workflowApi = {
  async getNextAction(data: WorkflowNextActionRequest): Promise<WorkflowNextAction> {
    return apiClient.post('/api/workflow/next-action', data);
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
