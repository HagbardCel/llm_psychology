/**
 * Frontend Type Definitions
 *
 * This file provides a compatibility layer between generated backend types
 * and frontend usage. It re-exports generated types with familiar names and
 * extends them with client-only fields as needed.
 *
 * IMPORTANT: API model types are now imported from generated/api.ts
 * Client-only types (UI state, etc.) are defined here.
 */

import type {
  UserProfile as GeneratedUserProfile,
  UserStatus as GeneratedUserStatus,
  Message as GeneratedMessage,
  Session as GeneratedSession,
  Topic as GeneratedTopic,
  WorkflowNextActionResponse,
} from './generated/api';

// ============================================================================
// API MODELS (Generated from Backend)
// ============================================================================

/**
 * User profile with client extensions
 * Backend type: UserProfile
 */
export interface User extends Omit<GeneratedUserProfile, 'userid'> {
  /** User ID (mapped from userid) */
  id: string;
  /** Email address (client-only, not in backend) */
  email?: string;
  /** Last activity timestamp (client-only) */
  lastActiveAt?: Date;
}

/**
 * User status enum (directly from backend)
 */
export type UserStatus = GeneratedUserStatus;

/**
 * Explicitly re-export UserStatus values for convenience
 */
export const UserStatus = {
  PROFILE_ONLY: 'PROFILE_ONLY' as UserStatus,
  INTAKE_IN_PROGRESS: 'INTAKE_IN_PROGRESS' as UserStatus,
  INTAKE_COMPLETE: 'INTAKE_COMPLETE' as UserStatus,
  ASSESSMENT_IN_PROGRESS: 'ASSESSMENT_IN_PROGRESS' as UserStatus,
  ASSESSMENT_COMPLETE: 'ASSESSMENT_COMPLETE' as UserStatus,
  THERAPY_IN_PROGRESS: 'THERAPY_IN_PROGRESS' as UserStatus,
  REFLECTION_IN_PROGRESS: 'REFLECTION_IN_PROGRESS' as UserStatus,
  PLAN_COMPLETE: 'PLAN_COMPLETE' as UserStatus,
} as const;

/**
 * Topic (directly from backend)
 */
export type Topic = GeneratedTopic;

/**
 * Message with client extensions
 * Backend type: Message
 */
export interface Message extends GeneratedMessage {
  /** Message ID (client-generated) */
  id?: string;
  /** Associated session ID (client-only) */
  sessionId?: string;
}

/**
 * Session with client extensions
 * Backend type: Session
 */
export interface Session extends Omit<GeneratedSession, 'sessionid' | 'userid'> {
  /** Session ID (mapped from sessionid) */
  id: string;
  /** User ID (mapped from userid) */
  userId: string;
  /** Agent type handling this session (client-only) */
  agentType?: AgentType;
  /** Selected therapy style (client-only) */
  therapyStyle?: TherapyStyle;
  /** Session status (client-only) */
  status?: SessionStatus;
  /** Session start time (client-only) */
  startTime?: Date;
  /** Session end time (client-only) */
  endTime?: Date;
  /** Additional metadata (client-only) */
  metadata?: Record<string, any>;
}

/**
 * Therapy plan with client extensions
 * Backend type: TherapyPlan
 */
export interface TherapyPlan {
  /** Plan ID */
  id: string;
  /** User ID */
  userId: string;
  /** Selected therapy style */
  therapyStyle?: string;
  /** Therapy goals (client-only) */
  goals?: string[];
  /** Number of sessions (client-only) */
  sessionCount?: number;
  /** Creation timestamp */
  createdAt: Date;
  /** Last update timestamp */
  updatedAt: Date;
  /** Plan details from backend */
  planDetails?: Record<string, any>;
  /** Plan version */
  version?: number;
}

/**
 * Workflow next action (from backend)
 */
export type WorkflowNextAction = WorkflowNextActionResponse;

// ============================================================================
// CLIENT-ONLY TYPES (UI State, Not in Backend)
// ============================================================================

/**
 * Agent types (client-side categorization)
 */
export enum AgentType {
  INTAKE = 'INTAKE',
  ASSESSMENT = 'ASSESSMENT',
  PSYCHOANALYST = 'PSYCHOANALYST',
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
export interface TherapyStyleInfo {
  style: string;
  name: string;
  description: string;
}
