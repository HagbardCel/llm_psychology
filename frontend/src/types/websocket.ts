/**
 * WebSocket types for real-time communication
 */

import {
  WS_CONNECTION_STATES as GENERATED_WS_CONNECTION_STATES,
  WS_ERROR_CODES as GENERATED_WS_ERROR_CODES,
  WS_MESSAGE_TYPES as GENERATED_WS_MESSAGE_TYPES,
  WS_PROTOCOL_VERSION as GENERATED_WS_PROTOCOL_VERSION,
  type WSConnectionState as GeneratedWSConnectionState,
  type WSMessageType as GeneratedWSMessageType,
  type WSErrorCode as GeneratedWSErrorCode,
} from './ws_protocol.generated';

/**
 * WebSocket Protocol Version
 * Auto-generated from schemas/ws_protocol.json.
 */
export const WS_PROTOCOL_VERSION = GENERATED_WS_PROTOCOL_VERSION;

/**
 * WebSocket Message Types
 * Auto-generated from schemas/ws_protocol.json.
 */
export const WS_MESSAGE_TYPES = GENERATED_WS_MESSAGE_TYPES;

/**
 * WebSocket Connection States
 */
export const WS_CONNECTION_STATES = GENERATED_WS_CONNECTION_STATES;

/**
 * WebSocket Error Codes
 * Auto-generated from schemas/ws_protocol.json.
 */
export const WS_ERROR_CODES = GENERATED_WS_ERROR_CODES;

/**
 * Type helpers for const assertions
 */
export type WSMessageType = GeneratedWSMessageType;
export type WSConnectionState = GeneratedWSConnectionState;
export type WSErrorCode = GeneratedWSErrorCode;

export interface WebSocketMessage {
  type: string;
  data: Record<string, any>;
  timestamp?: string;
}

export interface ConnectionStatus {
  isConnected: boolean;
  isConnecting: boolean;
  lastConnected?: Date;
  connectionError?: string;
}

export interface WebSocketConfig {
  url: string;
  userId: string;
  reconnectAttempts?: number;
  reconnectDelay?: number;
}

export interface WebSocketResponse {
  type: string;
  message?: string;
  error?: string;
  data?: Record<string, any>;
  timestamp: string;
}

export interface ErrorResponse {
  error: string;
  timestamp?: string;
}

// Streaming response types
export interface ChatResponseChunk {
  chunk: string;
  is_complete: boolean;
  full_response?: string;
}

/**
 * Session started event from backend
 * Matches SessionInfo.to_dict() from orchestration/models.py
 */
export interface SessionStartedEvent {
  session_id: string;
  agent_type: 'INTAKE' | 'ASSESSMENT' | 'THERAPIST' | 'PLANNING' | 'REFLECTION';
  workflow_state: string;  // WorkflowState value
  created_at: string;      // ISO 8601 timestamp
  user_id: string;
  session_type: 'intake' | 'therapy';
  selected_therapy_style: 'cbt' | 'freud' | 'jung' | null;
}

/**
 * Connected event from backend
 * Sent immediately after WebSocket connection
 */
export interface ConnectedEvent {
  user_id: string;
  name: string;
  status: string;  // UserStatus value
}

export interface SessionEndedEvent {
  reason: string;
  workflow_state: string;
}

export interface WorkflowNextActionEvent {
  user_id: string;
  workflow_state: string;
  required_action: string;
  required_fields: string[];
  defaults?: Record<string, string> | null;
  prompt?: string | null;
  blocking: boolean;
  timestamp: string;
  session_id?: string | null;
  state_signature: string;
  emission_source?: string | null;
}

/**
 * Type-safe WebSocket message wrapper
 */
export interface TypedWebSocketMessage<T = any> {
  type: string;
  data?: T;
}

/**
 * WebSocket event type map for type-safe handling
 */
export interface WebSocketEventMap {
  connected: ConnectedEvent;
  session_started: SessionStartedEvent;
  chat_response_chunk: ChatResponseChunk;
  workflow_next_action: WorkflowNextActionEvent;
  assessment_recommendations: AssessmentRecommendationsEvent;
  session_ended: SessionEndedEvent;
  typing_start: undefined;
  typing_stop: undefined;
}

export interface AssessmentRecommendationsEvent {
  session_id: string;
  user_id: string;
  recommendations: Array<{
    style_id: string;
    explanation: string;
    score?: number;
  }>;
}

// Callback types
export type StreamingChunkCallback = (chunk: string, isComplete: boolean, fullResponse?: string) => void;
export type SessionStartedCallback = (event: SessionStartedEvent) => void;
