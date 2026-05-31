/**
 * Frontend Type Definitions
 *
 * API DTOs remain snake_case to mirror the backend contract. Client-only
 * state uses camelCase fields and is defined alongside the generated types.
 */

import type {
  CreateSessionRequest as GeneratedCreateSessionRequest,
  CreateUserProfileRequest as GeneratedCreateUserProfileRequest,
  HealthCheckResponse as GeneratedHealthCheckResponse,
  PatchUserProfileRequest as GeneratedPatchUserProfileRequest,
  RequiredWorkflowAction as GeneratedRequiredWorkflowAction,
  SelectTherapyStyleRequest as GeneratedSelectTherapyStyleRequest,
  StartTherapyRequest as GeneratedStartTherapyRequest,
  StartTherapyResponse as GeneratedStartTherapyResponse,
  UserProfile as GeneratedUserProfile,
  UserStatus as GeneratedUserStatus,
  Message as GeneratedMessage,
  Session as GeneratedSession,
  Topic as GeneratedTopic,
  TherapyPlan as GeneratedTherapyPlan,
  TherapyStyleDTO as GeneratedTherapyStyleInfo,
  UpdateUserProfileRequest as GeneratedUpdateUserProfileRequest,
  UserStatusResponse as GeneratedUserStatusResponse,
  StatusMessageResponse as GeneratedStatusMessageResponse,
  WorkflowCompleteProfileRequest as GeneratedWorkflowCompleteProfileRequest,
  WorkflowNextAction as GeneratedWorkflowNextAction,
} from './generated/api';

// ============================================================================
// API MODELS (Generated from Backend)
// ============================================================================

/** User profile returned by the API */
export type User = GeneratedUserProfile;

/** User status enum (directly from backend) */
export type UserStatus = GeneratedUserStatus;

/** Convenience constants for user status comparisons */
export const UserStatus = {
  PROFILE_ONLY: 'PROFILE_ONLY' as UserStatus,
  INTAKE_IN_PROGRESS: 'INTAKE_IN_PROGRESS' as UserStatus,
  INTAKE_COMPLETE: 'INTAKE_COMPLETE' as UserStatus,
  ASSESSMENT_IN_PROGRESS: 'ASSESSMENT_IN_PROGRESS' as UserStatus,
  ASSESSMENT_COMPLETE: 'ASSESSMENT_COMPLETE' as UserStatus,
  INITIAL_PLAN_COMPLETE: 'INITIAL_PLAN_COMPLETE' as UserStatus,
  THERAPY_IN_PROGRESS: 'THERAPY_IN_PROGRESS' as UserStatus,
  PLAN_UPDATE_IN_PROGRESS: 'PLAN_UPDATE_IN_PROGRESS' as UserStatus,
  REFLECTION_IN_PROGRESS: 'REFLECTION_IN_PROGRESS' as UserStatus,
  PLAN_UPDATE_FAILED: 'PLAN_UPDATE_FAILED' as UserStatus,
  PLAN_UPDATE_COMPLETE: 'PLAN_UPDATE_COMPLETE' as UserStatus,
} as const;

/** Topic (directly from backend) */
export type Topic = GeneratedTopic;

/** Message DTO with UI extensions */
export interface Message extends GeneratedMessage {
  /** Client-generated identifier (UI-only) */
  id?: string;
  /** Associated session ID (UI-only) */
  sessionId?: string;
}

/** Session DTO with UI extensions */
export interface Session extends GeneratedSession {
  /** Agent handling this session (UI-only) */
  agentType?: AgentType;
  /** Selected therapy style (UI-only) */
  therapyStyle?: TherapyStyle;
  /** Session status for UI flow */
  status?: SessionStatus;
  /** Derived start time (UI-only) */
  startTime?: Date;
  /** Derived end time (UI-only) */
  endTime?: Date;
  /** Additional metadata (UI-only) */
  metadata?: Record<string, any>;
}

/** Therapy plan DTO with UI extensions */
export interface TherapyPlan extends GeneratedTherapyPlan {
  /** Client-only summary fields */
  sessionCount?: number;
}

export type RequiredWorkflowAction = GeneratedRequiredWorkflowAction;

/** Workflow next action (from backend) */
export type WorkflowNextAction = GeneratedWorkflowNextAction;

/** User status response (from backend) */
export type UserStatusResponse = GeneratedUserStatusResponse;

/** Health check response (from backend) */
export type HealthCheckResponse = GeneratedHealthCheckResponse;

/** User profile create request (from backend) */
export type CreateUserProfileRequest = GeneratedCreateUserProfileRequest;

/** Workflow profile completion request (backend workflow endpoint) */
export type WorkflowCompleteProfileRequest = GeneratedWorkflowCompleteProfileRequest;

/** User profile update request (from backend) */
export type UpdateUserProfileRequest = GeneratedUpdateUserProfileRequest;

/** User profile patch request (from backend) */
export type PatchUserProfileRequest = GeneratedPatchUserProfileRequest;

/** Session create request (from backend) */
export type CreateSessionRequest = GeneratedCreateSessionRequest;

/** Status message response (from backend) */
export type StatusMessageResponse = GeneratedStatusMessageResponse;

/** Workflow therapy style selection request (backend workflow endpoint) */
export type WorkflowSelectTherapyStyleRequest = GeneratedSelectTherapyStyleRequest;
export type WorkflowStartTherapyRequest = GeneratedStartTherapyRequest;
export type WorkflowStartTherapyResponse = GeneratedStartTherapyResponse;

export interface UserRegisterResponse {
  session: Session;
  workflow_next_action: WorkflowNextAction;
}

export interface UserProfileSummary {
  user_id: string;
  name: string;
  status: UserStatus;
  primary_language: string;
  plan_id?: string | null;
  updated_at: string;
}

export interface UserProfileListResponse {
  profiles: UserProfileSummary[];
}

// ============================================================================
// CLIENT-ONLY TYPES (UI State, Not in Backend)
// ============================================================================

/**
 * Agent types (client-side categorization)
 */
export enum AgentType {
  INTAKE = 'INTAKE',
  ASSESSMENT = 'ASSESSMENT',
  THERAPIST = 'THERAPIST',
  PLANNING = 'PLANNING',
  REFLECTION = 'REFLECTION'
}

/**
 * Therapy style identifiers (client-side)
 */
export enum TherapyStyle {
  FREUD = 'freud',
  JUNG = 'jung',
  CBT = 'cbt'
}

/**
 * Session status (client-side tracking)
 */
export enum SessionStatus {
  ACTIVE = 'ACTIVE',
  COMPLETED = 'COMPLETED',
  PAUSED = 'PAUSED'
}

/**
 * Application-wide state (React context)
 */
export interface AppState {
  user: User | null;
  currentSession: Session | null;
  sessions: Session[];
  therapyPlan: TherapyPlan | null;
  isLoading: boolean;
  error: string | null;
}

/**
 * Generic API response wrapper
 */
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

/**
 * Browser localStorage schema
 */
export interface LocalStorageData {
  user?: User;
  sessions?: Session[];
  therapyPlan?: TherapyPlan;
  preferences?: UserPreferences;
}

/**
 * User preferences (client-side settings)
 */
export interface UserPreferences {
  theme: 'light' | 'dark';
  notifications: boolean;
  autoSave: boolean;
  fontSize: 'small' | 'medium' | 'large';
}

/**
 * Therapy style display information
 */
export type TherapyStyleInfo = GeneratedTherapyStyleInfo;
