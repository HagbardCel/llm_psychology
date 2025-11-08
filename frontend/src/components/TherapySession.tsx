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
import { useWebSocket } from '../hooks/useWebSocket';
import { useTypingIndicator } from '../hooks/useTypingIndicator';
import { Message, Session, AgentType, SessionStatus } from '../types';

interface TherapySessionProps {
  sessionId?: string;
}

export function TherapySession({ sessionId }: TherapySessionProps) {
  const { state, actions } = useAppContext();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingMessage, setStreamingMessage] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);

  const currentSession = state.currentSession;
  const messages = currentSession?.messages || [];

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
        sender: 'agent',
        timestamp: new Date(),
        sessionId: currentSession.id,
      };

      const updatedSession: Session = {
        ...currentSession,
        messages: [...currentSession.messages, agentMessage],
      };

      actions.updateSession(updatedSession);

      // Reset streaming state
      setStreamingMessage('');
      setIsStreaming(false);
      setIsLoading(false);
    }
  };

  // Callback for session started event
  const handleSessionStarted = (event: any) => {
    console.log('Therapy session started:', event);
    // TODO: Update session state with session_id from event
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
    userId: state.user?.id || 'default_user',
    authToken: 'temp_token', // TODO: Use real auth token
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
      requestSession('therapy');
    }
  }, [isConnected, currentSession?.agentType]);

  const handleWebSocketMessage = (message: any) => {
    try {
      if (message.type === 'chat_response' && currentSession) {
        const agentMessage: Message = {
          id: generateMessageId(),
          content: message.message,
          sender: 'agent',
          timestamp: new Date(message.timestamp),
          sessionId: currentSession.id,
        };

        const updatedSession: Session = {
          ...currentSession,
          messages: [...currentSession.messages, agentMessage],
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
        sender: 'user',
        timestamp: new Date(),
        sessionId: currentSession.id,
      };

      // Update session with user message immediately
      const updatedSession: Session = {
        ...currentSession,
        messages: [...currentSession.messages, userMessage],
      };

      actions.updateSession(updatedSession);

      // Send message via WebSocket if connected
      if (isConnected) {
        sendChatMessage(content);
      } else {
        // Fallback to simulated response if not connected
        setTimeout(() => {
          const agentMessage: Message = {
            id: generateMessageId(),
            content: getSimulatedResponse(currentSession.agentType, content),
            sender: 'agent',
            timestamp: new Date(),
            sessionId: currentSession.id,
          };

          const finalSession: Session = {
            ...updatedSession,
            messages: [...updatedSession.messages, agentMessage],
          };

          actions.updateSession(finalSession);
          setIsLoading(false);
        }, 1500);
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
        therapyStyle={state.therapyPlan?.therapyStyle}
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
          disabled={!currentSession || currentSession.status !== SessionStatus.ACTIVE || !isConnected}
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
    case AgentType.REFLECTION:
      return 'How did this session feel for you?';
    default:
      return 'Type your message...';
  }
}

function getSimulatedResponse(agentType: AgentType, _userMessage: string): string {
  // This is temporary simulation - will be replaced with actual API calls
  const responses = {
    [AgentType.INTAKE]: [
      "Thank you for sharing that. Can you tell me more about what brought you here today?",
      "I appreciate you opening up. What are your main concerns or goals?",
      "That's helpful information. How long have you been experiencing this?",
    ],
    [AgentType.ASSESSMENT]: [
      "Based on what you've shared, I'm getting a sense of your needs. What therapy approach resonates with you?",
      "Your goals are clear. Have you had any previous therapy experience?",
      "I'm hearing some important themes. What feels most urgent to address?",
    ],
    [AgentType.PSYCHOANALYST]: [
      "That's a profound observation. What feelings come up when you think about that?",
      "I notice you mentioned... Can we explore that deeper?",
      "What associations come to mind when you reflect on that experience?",
    ],
    [AgentType.REFLECTION]: [
      "Thank you for that feedback. What stood out most in our session today?",
      "How are you feeling about the insights we explored?",
      "What would you like to focus on in our next session?",
    ],
  };

  const agentResponses = responses[agentType] || responses[AgentType.PSYCHOANALYST];
  return agentResponses[Math.floor(Math.random() * agentResponses.length)];
}