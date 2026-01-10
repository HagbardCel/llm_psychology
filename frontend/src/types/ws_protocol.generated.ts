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
