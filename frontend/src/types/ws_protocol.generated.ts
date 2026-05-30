// Auto-generated from schemas/ws_protocol.json. Do not edit by hand.

export const WS_PROTOCOL_VERSION = '1.2.3' as const;

export const WS_MESSAGE_TYPES = {
  CHAT_MESSAGE: 'chat_message',
  END_SESSION: 'end_session',
  CONNECTED: 'connected',
  SESSION_STARTED: 'session_started',
  WORKFLOW_NEXT_ACTION: 'workflow_next_action',
  CHAT_RESPONSE_CHUNK: 'chat_response_chunk',
  TYPING_START: 'typing_start',
  TYPING_STOP: 'typing_stop',
  ASSESSMENT_RECOMMENDATIONS: 'assessment_recommendations',
  SESSION_ENDED: 'session_ended',
  ERROR: 'error',
} as const;

export type WSMessageType = typeof WS_MESSAGE_TYPES[keyof typeof WS_MESSAGE_TYPES];

export const WS_CONNECTION_STATES = {
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected',
  RECONNECTING: 'reconnecting',
  ERROR: 'error',
} as const;

export type WSConnectionState = typeof WS_CONNECTION_STATES[keyof typeof WS_CONNECTION_STATES];

export const WS_ERROR_CODES = {
  INVALID_MESSAGE_FORMAT: 'invalid_message_format',
  MISSING_REQUIRED_FIELD: 'missing_required_field',
  SESSION_NOT_FOUND: 'session_not_found',
  CHAT_DISABLED_INITIAL_GREETING: 'chat_disabled_initial_greeting',
  CHAT_DISABLED_WORKFLOW_WAIT: 'chat_disabled_workflow_wait',
  INTERNAL_ERROR: 'internal_error',
  RATE_LIMIT_EXCEEDED: 'rate_limit_exceeded',
} as const;

export type WSErrorCode = typeof WS_ERROR_CODES[keyof typeof WS_ERROR_CODES];
