/**
 * WebSocket types for real-time communication
 */

export interface WebSocketMessage {
  type: string;
  data: Record<string, any>;
  timestamp?: string;
}

export interface ChatMessage {
  message: string;
  sender: 'user' | 'therapist';
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