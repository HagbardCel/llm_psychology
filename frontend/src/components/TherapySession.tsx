import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Box,
  Container,
  Alert,
  Snackbar,
} from '@mui/material';
import { useParams } from 'react-router-dom';
import { SessionHeader } from './SessionHeader';
import { MessageHistory } from './MessageHistory';
import { MessageInput } from './MessageInput';
import { ConnectionStatus } from './ConnectionStatus';
import { useCurrentUserId } from '../contexts/AppContext';
import { useAuth } from '../contexts/AuthContext';
import { useWebSocket } from '../hooks/useWebSocket';
import { useTypingIndicator } from '../hooks/useTypingIndicator';
import { apiClient } from '../services/apiClient';
import { Message, Session, AgentType, SessionStatus } from '../types';
import type { SessionStartedEvent } from '../types/websocket';

interface TherapySessionProps {
  sessionId?: string;
}

export function TherapySession({ sessionId }: TherapySessionProps) {
  const { token, user: authUser } = useAuth();
  const currentUserId = useCurrentUserId();
  const params = useParams<{ sessionId?: string }>();
  const effectiveSessionId = sessionId ?? params.sessionId;
  const isReadOnly = !!effectiveSessionId;

  const userId = authUser?.userId || currentUserId || 'guest';

  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingMessage, setStreamingMessage] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isSessionReady, setIsSessionReady] = useState(false);

  const streamBufferRef = useRef<string>('');
  const sessionRequestedRef = useRef(false);

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

      setSession((prev) => {
        if (!prev) return prev;

        const agentMessage: Message = {
          id: generateMessageId(),
          content: finalContent,
          role: 'assistant',
          timestamp: new Date(),
          sessionId: prev.id,
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
    sessionRequestedRef.current = true;

    const startedSession: Session = {
      id: event.session_id,
      userId: event.user_id,
      agentType: event.agent_type as AgentType,
      status: SessionStatus.ACTIVE,
      startTime: new Date(event.created_at),
      transcript: [],
      topics: [],
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
    startTyping,
    stopTyping,
    requestSession,
    isConnected
  } = useWebSocket({
    userId,
    authToken: token || '',
    autoConnect: !isReadOnly,
    onStreamingChunk: handleStreamingChunk,
    onSessionStarted: handleSessionStarted
  });

  // Typing indicator
  const typingIndicator = useTypingIndicator({
    onTypingStart: startTyping,
    onTypingStop: stopTyping,
    typingTimeout: 1000
  });

  // Handle WebSocket messages
  useEffect(() => {
    if (lastMessage) {
      handleWebSocketMessage(lastMessage);
    }
  }, [lastMessage]);

  useEffect(() => {
    if (!effectiveSessionId) return;

    let cancelled = false;
    const load = async () => {
      try {
        setIsLoading(true);
        setError(null);
        setIsSessionReady(false);

        const response = await apiClient.get<any>(`/api/sessions/${effectiveSessionId}`);

        if (cancelled) return;

        const loadedSession: Session = {
          id: response.session_id,
          userId: response.user_id,
          startTime: response.timestamp ? new Date(response.timestamp) : undefined,
          transcript: (response.transcript || []).map((m: any) => ({
            id: `${response.session_id}-${m.timestamp}-${m.role}`,
            role: m.role,
            content: m.content,
            timestamp: new Date(m.timestamp),
            sessionId: response.session_id,
          })),
          topics: response.topics || [],
          status: SessionStatus.COMPLETED,
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
  }, [effectiveSessionId]);

  // Request session once per connection (new sessions only).
  useEffect(() => {
    if (isReadOnly) return;
    if (!isConnected) return;
    if (isSessionReady) return;
    if (sessionRequestedRef.current) return;

    sessionRequestedRef.current = true;
    setIsLoading(true);
    setIsSessionReady(false);
    requestSession('therapy');
  }, [isConnected, isReadOnly, isSessionReady, requestSession]);

  // If we disconnect, allow re-requesting a session on reconnect.
  useEffect(() => {
    if (isReadOnly) return;
    if (isConnected) return;
    sessionRequestedRef.current = false;
    setIsSessionReady(false);
  }, [isConnected, isReadOnly]);

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
  }, [isConnected, isSessionReady]);

  const handleWebSocketMessage = (message: any) => {
    try {
      if (message.error) {
        setError(message.error);
        setIsLoading(false);
      }
    } catch (err) {
      console.error('Error handling WebSocket message:', err);
      setError('Failed to process server response');
      setIsLoading(false);
    }
  };

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
        timestamp: new Date(),
        sessionId: session.id,
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
    // TODO: Implement navigation drawer
    console.log('Menu clicked');
  };

  const handleSettingsClick = () => {
    // TODO: Implement settings modal
    console.log('Settings clicked');
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
            !isSessionReady
          }
          isLoading={isLoading}
          placeholder={getInputPlaceholder(session?.agentType)}
          onTypingChange={typingIndicator.handleInputChange}
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
