import { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Alert,
  Snackbar,
} from '@mui/material';
import { SessionHeader } from './SessionHeader';
import { MessageHistory } from './MessageHistory';
import { MessageInput } from './MessageInput';
import { ConnectionStatus } from './ConnectionStatus';
import { useAppContext } from '../contexts/AppContext';
import { useAuth } from '../contexts/AuthContext';
import { useWebSocket } from '../hooks/useWebSocket';
import { useTypingIndicator } from '../hooks/useTypingIndicator';
import { Message, Session, AgentType, SessionStatus, TherapyStyle } from '../types';
import type { SessionStartedEvent } from '../types/websocket';

interface TherapySessionProps {
  sessionId?: string;
}

export function TherapySession({ sessionId }: TherapySessionProps) {
  const { state, actions } = useAppContext();
  const { token, user: authUser } = useAuth();
  const user = state.user;
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingMessage, setStreamingMessage] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isSessionReady, setIsSessionReady] = useState(false);

  const currentSession = state.currentSession;
  const messages = currentSession?.transcript || [];

  // Callback for handling streaming chunks
  const handleStreamingChunk = (chunk: string, isComplete: boolean, fullResponse?: string) => {
    if (!currentSession) return;

    if (!isComplete) {
      // Accumulate chunks
      setStreamingMessage(prev => prev + chunk);
      setIsStreaming(true);
    } else {
      // Streaming complete - create final message
      const finalContent = fullResponse || streamingMessage;

      const agentMessage: Message = {
        id: generateMessageId(),
        content: finalContent,
        role: 'assistant',
        timestamp: new Date(),
        sessionId: currentSession.id,
      };

      const updatedSession: Session = {
        ...currentSession,
        transcript: [...currentSession.transcript, agentMessage],
      };

      actions.updateSession(updatedSession);

      // Reset streaming state
      setStreamingMessage('');
      setIsStreaming(false);
      setIsLoading(false);
    }
  };

  // Callback for session started event
  const handleSessionStarted = (event: SessionStartedEvent) => {
    console.log('Therapy session started:', event);

    if (!currentSession) {
      console.error('No current session to update with server session ID');
      return;
    }

    // Update session with server-assigned ID
    const updatedSession: Session = {
      ...currentSession,
      id: event.session_id,
      agentType: event.agent_type as AgentType,
      startTime: new Date(event.created_at),
    };

    actions.updateSession(updatedSession);
    actions.setCurrentSession(updatedSession);
    setIsSessionReady(true);

    console.log(`Session synchronized: ${event.session_id} (${event.agent_type})`);
  };

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
    userId: authUser?.userId || user?.id || 'guest',
    authToken: token || '',
    autoConnect: true,
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
    if (sessionId && sessionId !== currentSession?.id) {
      loadSession(sessionId);
    }
  }, [sessionId, currentSession?.id]);

  // Request therapy session when connected
  useEffect(() => {
    if (isConnected && currentSession?.agentType === AgentType.PSYCHOANALYST) {
      setIsSessionReady(false);
      requestSession('therapy');
    }
  }, [isConnected, currentSession?.agentType]);

  // Session initialization timeout
  useEffect(() => {
    if (!isConnected || isSessionReady) {
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
      if (message.type === 'chat_response' && currentSession) {
        const agentMessage: Message = {
          id: generateMessageId(),
          content: message.message,
          role: 'assistant',
          timestamp: new Date(message.timestamp),
          sessionId: currentSession.id,
        };

        const updatedSession: Session = {
          ...currentSession,
          transcript: [...currentSession.transcript, agentMessage],
        };

        actions.updateSession(updatedSession);
        setIsLoading(false);
      } else if (message.type === 'session_started') {
        console.log('Therapy session started:', message);
      } else if (message.error) {
        setError(message.error);
        setIsLoading(false);
      }
    } catch (err) {
      console.error('Error handling WebSocket message:', err);
      setError('Failed to process server response');
      setIsLoading(false);
    }
  };

  const loadSession = async (id: string) => {
    try {
      setIsLoading(true);
      const session = state.sessions.find(s => s.id === id);
      if (session) {
        actions.setCurrentSession(session);
      } else {
        throw new Error('Session not found');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load session');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendMessage = async (content: string) => {
    if (!currentSession || !state.user) {
      setError('No active session or user');
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
        sessionId: currentSession.id,
      };

      // Update session with user message immediately
      const updatedSession: Session = {
        ...currentSession,
        transcript: [...currentSession.transcript, userMessage],
      };

      actions.updateSession(updatedSession);

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
    if (!currentSession) return;

    try {
      const endedSession: Session = {
        ...currentSession,
        status: SessionStatus.COMPLETED,
        endTime: new Date(),
      };

      actions.updateSession(endedSession);
      actions.setCurrentSession(null);
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
        session={currentSession}
        therapyStyle={state.therapyPlan?.therapyStyle as TherapyStyle | undefined}
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
          disabled={!currentSession || currentSession.status !== SessionStatus.ACTIVE || !isConnected || !isSessionReady}
          isLoading={isLoading}
          placeholder={getInputPlaceholder(currentSession?.agentType)}
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
