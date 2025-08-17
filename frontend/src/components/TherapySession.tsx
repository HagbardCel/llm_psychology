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
import { useAppContext } from '../contexts/AppContext';
import { Message, Session, AgentType, SessionStatus } from '../types';

interface TherapySessionProps {
  sessionId?: string;
}

export function TherapySession({ sessionId }: TherapySessionProps) {
  const { state, actions } = useAppContext();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentSession = state.currentSession;
  const messages = currentSession?.messages || [];

  useEffect(() => {
    if (sessionId && sessionId !== currentSession?.id) {
      loadSession(sessionId);
    }
  }, [sessionId, currentSession?.id]);

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
      const _userMessage: Message = {
        id: generateMessageId(),
        content,
        sender: 'user',
        timestamp: new Date(),
        sessionId: currentSession.id,
      };

      // Update session with user message
      const updatedSession: Session = {
        ...currentSession,
        messages: [...currentSession.messages, _userMessage],
      };

      actions.updateSession(updatedSession);

      // TODO: Send message to backend API and get agent response
      // For now, simulate agent response
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
          />
        </Box>

        <MessageInput
          onSendMessage={handleSendMessage}
          disabled={!currentSession || currentSession.status !== SessionStatus.ACTIVE}
          isLoading={isLoading}
          placeholder={getInputPlaceholder(currentSession?.agentType)}
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