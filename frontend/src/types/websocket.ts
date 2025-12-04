/**
 * WebSocket types for real-time communication
 */

/**
 * WebSocket Protocol Version
 * Matches backend protocol version in trio_server.py
 */
export const WS_PROTOCOL_VERSION = '1.0' as const;

/**
 * WebSocket Message Types
 * These constants ensure type safety and consistency with backend protocol
 */
export const WS_MESSAGE_TYPES = {
  // Client → Server messages
  SESSION_REQUEST: 'session_request',
  CHAT_MESSAGE: 'chat_message',
  PING: 'ping',

  // Server → Client messages
  CONNECTED: 'connected',
  SESSION_STARTED: 'session_started',
  CHAT_RESPONSE_CHUNK: 'chat_response_chunk',
  TYPING_START: 'typing_start',
  TYPING_STOP: 'typing_stop',
  USER_STATUS: 'user_status',
  STYLE_SELECTED: 'style_selected',
  SESSION_EXTENDED: 'session_extended',
  ERROR: 'error',
  PONG: 'pong',
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
  UNAUTHORIZED: 'unauthorized',
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

export interface ChatMessage {
  message: string;
  role: 'user' | 'assistant';
  timestamp: string;
  id?: string;
}

export interface ConnectionStatus {
  isConnected: boolean;
  isConnecting: boolean;
  lastConnected?: Date;
  connectionError?: string;
}

export interface TypingStatus {
  isTyping: boolean;
  userId?: string;
}

export interface WebSocketConfig {
  url: string;
  authToken: string;
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

export interface SessionStartResponse {
  type: 'session_started';
  session_type: string;
  message: string;
  timestamp: string;
}

export interface ChatResponse {
  type: 'chat_response';
  message: string;
  timestamp: string;
}

export interface ErrorResponse {
  error: string;
  timestamp?: string;
}

export interface ConnectionEvent {
  status: 'connected' | 'disconnected' | 'reconnecting' | 'error';
  user_id?: string;
  timestamp: number;
  error?: string;
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
  has_initial_message: boolean;
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
  user_status: UserStatusEvent;
  typing_start: undefined;
  typing_stop: undefined;
  pong: { timestamp: number };
}

export interface UserStatusEvent {
  user_id: string;
  workflow_state: string;
  next_agent: string;
}

export interface StyleSelectedEvent {
  selected_style: string;
  message: string;
}

export interface SessionExtendedEvent {
  session_id: string;
  additional_minutes: number;
  message: string;
}

// Callback types
export type StreamingChunkCallback = (chunk: string, isComplete: boolean, fullResponse?: string) => void;
export type SessionStartedCallback = (event: SessionStartedEvent) => void;
export type UserStatusCallback = (event: UserStatusEvent) => void;