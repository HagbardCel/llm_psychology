/**
 * WebSocket types for real-time communication
 */

/**
 * WebSocket Protocol Version
 * Matches backend protocol version in trio_server.py
 */
export const WS_PROTOCOL_VERSION = '1.2.3' as const;

/**
 * WebSocket Message Types
 * These constants ensure type safety and consistency with backend protocol
 */
export const WS_MESSAGE_TYPES = {
  // Client → Server messages
  CHAT_MESSAGE: 'chat_message',
  END_SESSION: 'end_session',

  // Server → Client messages
  CONNECTED: 'connected',
  SESSION_STARTED: 'session_started',
  CHAT_RESPONSE_CHUNK: 'chat_response_chunk',
  TYPING_START: 'typing_start',
  TYPING_STOP: 'typing_stop',
  WORKFLOW_NEXT_ACTION: 'workflow_next_action',
  ASSESSMENT_RECOMMENDATIONS: 'assessment_recommendations',
  SESSION_ENDED: 'session_ended',
  ERROR: 'error',
} as const;

/**
 * WebSocket Connection States
 */
export const WS_CONNECTION_STATES = {
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected',
  RECONNECTING: 'reconnecting',
  ERROR: 'error',
} as const;

/**
 * WebSocket Error Codes
 * Matches backend error handling in trio_server.py
 */
export const WS_ERROR_CODES = {
  INVALID_MESSAGE_FORMAT: 'invalid_message_format',
  MISSING_REQUIRED_FIELD: 'missing_required_field',
  SESSION_NOT_FOUND: 'session_not_found',
  INTERNAL_ERROR: 'internal_error',
  RATE_LIMIT_EXCEEDED: 'rate_limit_exceeded',
} as const;

/**
 * Type helpers for const assertions
 */
export type WSMessageType = typeof WS_MESSAGE_TYPES[keyof typeof WS_MESSAGE_TYPES];
export type WSConnectionState = typeof WS_CONNECTION_STATES[keyof typeof WS_CONNECTION_STATES];
export type WSErrorCode = typeof WS_ERROR_CODES[keyof typeof WS_ERROR_CODES];

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
  agent_type: 'INTAKE' | 'ASSESSMENT' | 'PSYCHOANALYST' | 'PLANNING' | 'REFLECTION';
  workflow_state: string;  // WorkflowState value
  created_at: string;      // ISO 8601 timestamp
  user_id: string;
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
