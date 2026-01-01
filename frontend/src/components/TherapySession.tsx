import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box,
  Container,
  Alert,
  Snackbar,
} from '@mui/material';
import { useNavigate, useParams } from 'react-router-dom';
import { SessionHeader } from './SessionHeader';
import { MessageHistory } from './MessageHistory';
import { MessageInput } from './MessageInput';
import { ConnectionStatus } from './ConnectionStatus';
import { useAppContext, useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useWebSocketContext } from '../contexts/WebSocketContext';
import { apiClient } from '../services/apiClient';
import { Message, Session, AgentType, SessionStatus } from '../types';
import type {
  AssessmentRecommendationsEvent,
  SessionStartedEvent,
  WebSocketResponse,
} from '../types/websocket';
import { WS_MESSAGE_TYPES } from '../types/websocket';

interface TherapySessionProps {
  sessionId?: string;
  onAssessmentRecommendations?: (
    payload: AssessmentRecommendationsEvent
  ) => void;
}

export function TherapySession({
  sessionId,
  onAssessmentRecommendations
}: TherapySessionProps) {
  const currentUserId = useCurrentUserId();
  const { setSidebarOpen } = useAppContext();
  const navigate = useNavigate();
  const params = useParams<{ sessionId?: string }>();
  const effectiveSessionId = sessionId ?? params.sessionId;
  const isReadOnly = !!effectiveSessionId;

  const userId = currentUserId || 'guest';
  const activeSessionId = useCurrentSessionId();

  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingMessage, setStreamingMessage] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isSessionReady, setIsSessionReady] = useState(false);
  const [waitPrompt, setWaitPrompt] = useState<string | null>(null);

  const streamBufferRef = useRef<string>('');
  const hasReceivedInitialMessageRef = useRef(false);

  const messages = session?.transcript || [];

  // Callback for handling streaming chunks
  const handleStreamingChunk = useCallback(
    (chunk: string, isComplete: boolean, fullResponse?: string) => {
      if (isReadOnly) return;

      if (!isComplete) {
        streamBufferRef.current += chunk;
        setStreamingMessage(streamBufferRef.current);
        setIsStreaming(true);
        return;
      }

      const finalContent = fullResponse || streamBufferRef.current;
      streamBufferRef.current = '';

      setIsStreaming(false);
      setStreamingMessage('');
      setIsLoading(false);

      if (!finalContent) return;

      if (!hasReceivedInitialMessageRef.current) {
        hasReceivedInitialMessageRef.current = true;
        setIsSessionReady(true);
      }

      setSession((prev) => {
        if (!prev) return prev;

        const agentMessage: Message = {
          id: generateMessageId(),
          content: finalContent,
          role: 'assistant',
          timestamp: new Date().toISOString(),
          sessionId: prev.session_id,
        };

        return {
          ...prev,
          transcript: [...(prev.transcript || []), agentMessage],
        };
      });
    },
    [isReadOnly]
  );

  // Callback for session started event
  const handleSessionStarted = useCallback((event: SessionStartedEvent) => {
    if (isReadOnly) return;

    streamBufferRef.current = '';
    hasReceivedInitialMessageRef.current = false;

    const startedSession: Session = {
      session_id: event.session_id,
      user_id: event.user_id,
      timestamp: event.created_at,
      transcript: [],
      topics: [],
      psychological_summary: null,
      dominant_affects: [],
      key_themes: [],
      notable_interactions: null,
      interpretations: null,
      patient_reactions: null,
      enriched: false,
      agentType: event.agent_type as AgentType,
      status: SessionStatus.ACTIVE,
      startTime: new Date(event.created_at),
    };

    setSession(startedSession);
    setIsSessionReady(true);
    setIsLoading(false);
  }, [isReadOnly]);

  // WebSocket integration
  const {
    connectionStatus,
    lastMessage,
    sendChatMessage,
    isConnected,
    registerStreamingChunkHandler,
    registerSessionStartedHandler,
    registerWorkflowNextActionHandler,
  } = useWebSocketContext();

  // Handle WebSocket messages
  const handleWebSocketMessage = useCallback(
    (message: WebSocketResponse | null) => {
      if (!message) return;

      if (message.type === WS_MESSAGE_TYPES.ASSESSMENT_RECOMMENDATIONS) {
        if (onAssessmentRecommendations && message.data) {
          onAssessmentRecommendations(message.data as AssessmentRecommendationsEvent);
        }
        return;
      }

      if (message.type === WS_MESSAGE_TYPES.SESSION_STARTED && message.data) {
        handleSessionStarted(message.data as SessionStartedEvent);
        return;
      }

      if (message.type === WS_MESSAGE_TYPES.ERROR || message.error) {
        const errorMessage =
          message.error ||
          (typeof message.data === 'object' && message.data
            ? (message.data as Record<string, any>).message
            : undefined);
        if (errorMessage) {
          setError(errorMessage);
        }
        setIsLoading(false);
      }
    },
    [handleSessionStarted, onAssessmentRecommendations]
  );

  useEffect(() => {
    if (lastMessage) {
      handleWebSocketMessage(lastMessage);
    }
  }, [lastMessage, handleWebSocketMessage]);

  useEffect(() => {
    if (isReadOnly) return;
    const unsubscribeStreaming = registerStreamingChunkHandler(handleStreamingChunk);
    const unsubscribeSession = registerSessionStartedHandler(handleSessionStarted);
    const unsubscribeWorkflow = registerWorkflowNextActionHandler((event) => {
      if (event.required_action === 'wait') {
        setWaitPrompt(event.prompt || 'Assessment in progress. Please wait.');
      } else {
        setWaitPrompt(null);
      }
    });
    return () => {
      unsubscribeStreaming();
      unsubscribeSession();
      unsubscribeWorkflow();
    };
  }, [
    handleSessionStarted,
    handleStreamingChunk,
    isReadOnly,
    registerSessionStartedHandler,
    registerStreamingChunkHandler,
    registerWorkflowNextActionHandler
  ]);

  useEffect(() => {
    if (isReadOnly) return;
    if (!isConnected) {
      setIsSessionReady(false);
      return;
    }
    if (session?.status === SessionStatus.ACTIVE && !waitPrompt) {
      setIsSessionReady(true);
    }
  }, [isConnected, isReadOnly, session, waitPrompt]);

  useEffect(() => {
    if (!effectiveSessionId) return;

    let cancelled = false;
    const load = async () => {
      try {
        setIsLoading(true);
        setError(null);
        setIsSessionReady(false);

        if (!activeSessionId) {
          throw new Error('No active session found. Please reconnect.');
        }
        const response = await apiClient.get<Session>(
          `/api/sessions/${effectiveSessionId}?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(activeSessionId)}`
        );

        if (cancelled) return;

        const loadedSession: Session = {
          ...response,
          transcript: (response.transcript || []).map((m) => ({
            ...m,
            id: `${response.session_id}-${m.timestamp}-${m.role}`,
            sessionId: response.session_id,
          })),
          topics: response.topics || [],
          status: SessionStatus.COMPLETED,
          startTime: response.timestamp ? new Date(response.timestamp) : undefined,
        };

        setSession(loadedSession);
        setIsSessionReady(true);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load session');
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [activeSessionId, effectiveSessionId, userId]);

  // Session initialization timeout
  useEffect(() => {
    if (isReadOnly || !isConnected || isSessionReady) {
      return;
    }

    const timeout = setTimeout(() => {
      if (!isSessionReady) {
        setError('Session initialization timeout. Please refresh and try again.');
        console.error('Session failed to initialize within 10 seconds');
      }
    }, 10000);

    return () => clearTimeout(timeout);
  }, [isConnected, isReadOnly, isSessionReady]);

  const handleSendMessage = async (content: string) => {
    if (isReadOnly) return;
    if (!session || !userId) {
      setError('No active session');
      return;
    }

    try {
      setIsLoading(true);

      // Create user message
      const userMessage: Message = {
        id: generateMessageId(),
        content,
        role: 'user',
        timestamp: new Date().toISOString(),
        sessionId: session.session_id,
      };

      // Update transcript immediately for responsive UI
      setSession((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          transcript: [...(prev.transcript || []), userMessage],
        };
      });

      // Send message via WebSocket if connected
      if (isConnected) {
        sendChatMessage(content);
      } else {
        setError('Not connected to server. Please try again.');
        setIsLoading(false);
      }

    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message');
      setIsLoading(false);
    }
  };

  const handleEndSession = async () => {
    if (!session) return;

    try {
      const endedSession: Session = {
        ...session,
        status: SessionStatus.COMPLETED,
        endTime: new Date(),
      };

      setSession(endedSession);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to end session');
    }
  };

  const handleMenuClick = () => {
    setSidebarOpen(true);
  };

  const handleSettingsClick = () => {
    navigate('/settings');
  };

  return (
    <Box sx={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <SessionHeader
        session={session}
        therapyStyle={undefined}
        onMenuClick={handleMenuClick}
        onSettingsClick={handleSettingsClick}
        onEndSession={handleEndSession}
      />

      {/* Connection Status */}
      <Box sx={{ p: 1, borderBottom: 1, borderColor: 'divider' }}>
        <ConnectionStatus status={connectionStatus} variant="chip" />
      </Box>
      {waitPrompt && (
        <Box sx={{ p: 1 }}>
          <Alert severity="info">{waitPrompt}</Alert>
        </Box>
      )}

      <Container 
        maxWidth="md" 
        sx={{ 
          flexGrow: 1, 
          display: 'flex', 
          flexDirection: 'column',
          p: 0,
          height: 'calc(100vh - 64px)', // Subtract AppBar height
        }}
      >
        <Box sx={{ flexGrow: 1, minHeight: 0 }}>
          <MessageHistory
            messages={messages}
            isLoading={isLoading}
            streamingMessage={streamingMessage}
            isStreaming={isStreaming}
          />
        </Box>

        <MessageInput
          onSendMessage={handleSendMessage}
          disabled={
            isReadOnly ||
            !session ||
            session.status !== SessionStatus.ACTIVE ||
            !isConnected ||
            !isSessionReady ||
            !!waitPrompt
          }
          isLoading={isLoading}
          placeholder={getInputPlaceholder(session?.agentType)}
        />
      </Container>

      <Snackbar
        open={!!error}
        autoHideDuration={6000}
        onClose={() => setError(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      </Snackbar>
    </Box>
  );
}

function generateMessageId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

function getInputPlaceholder(agentType?: AgentType): string {
  switch (agentType) {
    case AgentType.INTAKE:
      return 'Share some information about yourself...';
    case AgentType.ASSESSMENT:
      return 'Tell me about your goals and preferences...';
    case AgentType.PSYCHOANALYST:
      return 'What would you like to explore today?';
    case AgentType.PLANNING:
      return 'Share your thoughts on the treatment plan...';
    case AgentType.REFLECTION:
      return 'How did this session feel for you?';
    default:
      return 'Type your message...';
  }
}
