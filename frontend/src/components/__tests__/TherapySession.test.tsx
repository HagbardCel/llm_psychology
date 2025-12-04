import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { TherapySession } from '../TherapySession';
import { AppProvider } from '../../contexts/AppContext';
import { BrowserRouter } from 'react-router-dom';
import { Session, AgentType, SessionStatus, UserStatus } from '../../types';
import { SessionStartedEvent } from '../../types/websocket';

// Mock dependencies
const mockSendChatMessage = jest.fn();
const mockStartTyping = jest.fn();
const mockStopTyping = jest.fn();
const mockRequestSession = jest.fn();
const mockOnStreamingChunk = jest.fn();
const mockOnSessionStarted = jest.fn();

let mockIsConnected = true;
let mockConnectionStatus = { isConnected: true, isConnecting: false };
let mockLastMessage: any = null;

jest.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: jest.fn((config) => {
    // Store callbacks for later triggering
    mockOnStreamingChunk.mockImplementation(config.onStreamingChunk);
    mockOnSessionStarted.mockImplementation(config.onSessionStarted);

    return {
      connectionStatus: mockConnectionStatus,
      lastMessage: mockLastMessage,
      sendChatMessage: mockSendChatMessage,
      startTyping: mockStartTyping,
      stopTyping: mockStopTyping,
      requestSession: mockRequestSession,
      isConnected: mockIsConnected,
    };
  }),
}));

jest.mock('../../hooks/useTypingIndicator', () => ({
  useTypingIndicator: jest.fn(() => ({
    handleInputChange: jest.fn(),
  })),
}));

// Mock child components to simplify testing
jest.mock('../SessionHeader', () => ({
  SessionHeader: ({ onEndSession }: any) => (
    <div data-testid="session-header">
      <button onClick={onEndSession} data-testid="end-session-btn">
        End Session
      </button>
    </div>
  ),
}));

jest.mock('../MessageHistory', () => ({
  MessageHistory: ({ messages, isLoading, streamingMessage, isStreaming }: any) => (
    <div data-testid="message-history">
      {messages.map((msg: any, i: number) => (
        <div key={i} data-testid={`message-${i}`}>
          {msg.content}
        </div>
      ))}
      {isStreaming && <div data-testid="streaming-message">{streamingMessage}</div>}
      {isLoading && <div data-testid="loading-indicator">Loading...</div>}
    </div>
  ),
}));

jest.mock('../MessageInput', () => ({
  MessageInput: ({ onSendMessage, disabled, placeholder }: any) => (
    <div data-testid="message-input">
      <input
        data-testid="message-input-field"
        placeholder={placeholder}
        disabled={disabled}
        onChange={(_e) => {}}
      />
      <button
        data-testid="send-message-btn"
        onClick={() => onSendMessage('Test message')}
        disabled={disabled}
      >
        Send
      </button>
    </div>
  ),
}));

jest.mock('../ConnectionStatus', () => ({
  ConnectionStatus: ({ status }: any) => (
    <div data-testid="connection-status">
      {status.isConnected ? 'Connected' : 'Disconnected'}
    </div>
  ),
}));

describe('TherapySession', () => {
  // Test data factories
  const createMockSession = (overrides?: Partial<Session>): Session => ({
    id: 'test-session-id',
    userId: 'test-user-id',
    agentType: AgentType.PSYCHOANALYST,
    status: SessionStatus.ACTIVE,
    startTime: new Date(),
    transcript: [],
    topics: [],
    ...overrides,
  });

  const mockSession: Session = createMockSession();

  const TestWrapper = ({ children }: { children: React.ReactNode }) => (
    <BrowserRouter>
      <AppProvider>{children}</AppProvider>
    </BrowserRouter>
  );

  beforeEach(() => {
    jest.clearAllMocks();
    mockIsConnected = true;
    mockConnectionStatus = { isConnected: true, isConnecting: false };
    mockLastMessage = null;

    // Mock AppContext to provide a current session
    jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
      state: {
        currentSession: mockSession,
        user: {
          id: 'test-user-id',
          name: 'Test User',
          status: UserStatus.PLAN_COMPLETE,
          createdAt: new Date(),
        },
        sessions: [mockSession],
        therapyPlan: null,
        isLoading: false,
        error: null,
      },
      actions: {
        updateSession: jest.fn(),
        setCurrentSession: jest.fn(),
        setError: jest.fn(),
      },
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('Rendering', () => {
    it('should render without crashing', () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByTestId('session-header')).toBeInTheDocument();
      expect(screen.getByTestId('message-history')).toBeInTheDocument();
      expect(screen.getByTestId('message-input')).toBeInTheDocument();
    });

    it('should render connection status', () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByTestId('connection-status')).toBeInTheDocument();
      expect(screen.getByText('Connected')).toBeInTheDocument();
    });

    it('should show disconnected when not connected', () => {
      mockIsConnected = false;
      mockConnectionStatus = { isConnected: false, isConnecting: false };

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByText('Disconnected')).toBeInTheDocument();
    });

    it('should render correct placeholder for PSYCHOANALYST agent', () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByPlaceholderText('What would you like to explore today?')).toBeInTheDocument();
    });
  });

  describe('WebSocket Integration', () => {
    it('should connect to WebSocket on mount', () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      // useWebSocket hook should have been called
      expect(require('../../hooks/useWebSocket').useWebSocket).toHaveBeenCalled();
    });

    it('should use auth credentials from AuthContext', () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      const useWebSocketCall = require('../../hooks/useWebSocket').useWebSocket.mock.calls[0][0];
      // AuthContext provides default user which gets used or falls back to 'guest'
      expect(useWebSocketCall.userId).toBeTruthy();
      expect(useWebSocketCall.authToken).toBeTruthy();
    });

    it('should request therapy session when agent type is PSYCHOANALYST', async () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(mockRequestSession).toHaveBeenCalledWith('therapy');
      });
    });

    it('should handle session_started event', async () => {
      const mockUpdateSession = jest.fn();
      const mockSetCurrentSession = jest.fn();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: mockSession,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: mockUpdateSession,
          setCurrentSession: mockSetCurrentSession,
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      // Get the onSessionStarted callback
      const useWebSocketCall = require('../../hooks/useWebSocket').useWebSocket.mock.calls[0][0];
      const onSessionStarted = useWebSocketCall.onSessionStarted;

      // Trigger session_started event
      const sessionStartedEvent: SessionStartedEvent = {
        session_id: 'server-session-id',
        agent_type: 'PSYCHOANALYST',
        workflow_state: 'THERAPY_IN_PROGRESS',
        created_at: new Date().toISOString(),
        user_id: 'test-user-id',
        has_initial_message: true,
      };

      act(() => {
        onSessionStarted(sessionStartedEvent);
      });

      await waitFor(() => {
        expect(mockUpdateSession).toHaveBeenCalledWith(
          expect.objectContaining({
            id: 'server-session-id',
            agentType: 'PSYCHOANALYST',
          })
        );
        expect(mockSetCurrentSession).toHaveBeenCalled();
      });
    });

    it('should disable input until session ready', () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      const sendButton = screen.getByTestId('send-message-btn');
      expect(sendButton).toBeDisabled();
    });
  });

  describe('Message Sending', () => {
    it('should send message via WebSocket when connected', async () => {
      const mockUpdateSession = jest.fn();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, id: 'ready-session-id' },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: mockUpdateSession,
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      // Enable the session (simulate session_started)
      const useWebSocketCall = require('../../hooks/useWebSocket').useWebSocket.mock.calls[0][0];
      const onSessionStarted = useWebSocketCall.onSessionStarted;

      act(() => {
        onSessionStarted({
          session_id: 'ready-session-id',
          agent_type: 'PSYCHOANALYST',
          workflow_state: 'THERAPY_IN_PROGRESS',
          created_at: new Date().toISOString(),
          user_id: 'test-user-id',
          has_initial_message: false,
        });
      });

      await waitFor(() => {
        const sendButton = screen.getByTestId('send-message-btn');
        expect(sendButton).not.toBeDisabled();
      });

      const sendButton = screen.getByTestId('send-message-btn');
      fireEvent.click(sendButton);

      await waitFor(() => {
        expect(mockSendChatMessage).toHaveBeenCalledWith('Test message');
      });
    });

    it('should add user message to transcript immediately', async () => {
      const mockUpdateSession = jest.fn();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, id: 'ready-session-id' },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: mockUpdateSession,
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      // Enable session
      const useWebSocketCall = require('../../hooks/useWebSocket').useWebSocket.mock.calls[0][0];
      act(() => {
        useWebSocketCall.onSessionStarted({
          session_id: 'ready-session-id',
          agent_type: 'PSYCHOANALYST',
          workflow_state: 'THERAPY_IN_PROGRESS',
          created_at: new Date().toISOString(),
          user_id: 'test-user-id',
          has_initial_message: false,
        });
      });

      await waitFor(() => {
        expect(screen.getByTestId('send-message-btn')).not.toBeDisabled();
      });

      fireEvent.click(screen.getByTestId('send-message-btn'));

      await waitFor(() => {
        expect(mockUpdateSession).toHaveBeenCalledWith(
          expect.objectContaining({
            transcript: expect.arrayContaining([
              expect.objectContaining({
                content: 'Test message',
                role: 'user',
              }),
            ]),
          })
        );
      });
    });
  });

  describe('Streaming Responses', () => {
    it('should accumulate streaming chunks', async () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      const useWebSocketCall = require('../../hooks/useWebSocket').useWebSocket.mock.calls[0][0];
      const onStreamingChunk = useWebSocketCall.onStreamingChunk;

      // Send streaming chunks
      act(() => {
        onStreamingChunk('Hello', false);
      });

      await waitFor(() => {
        expect(screen.getByTestId('streaming-message')).toHaveTextContent('Hello');
      });

      act(() => {
        onStreamingChunk(' world', false);
      });

      await waitFor(() => {
        expect(screen.getByTestId('streaming-message')).toHaveTextContent('Hello world');
      });
    });

    it('should add final message on stream complete', async () => {
      const mockUpdateSession = jest.fn();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: mockSession,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: mockUpdateSession,
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      const useWebSocketCall = require('../../hooks/useWebSocket').useWebSocket.mock.calls[0][0];
      const onStreamingChunk = useWebSocketCall.onStreamingChunk;

      // Send complete message
      act(() => {
        onStreamingChunk('', true, 'Complete response from agent');
      });

      await waitFor(() => {
        expect(mockUpdateSession).toHaveBeenCalledWith(
          expect.objectContaining({
            transcript: expect.arrayContaining([
              expect.objectContaining({
                content: 'Complete response from agent',
                role: 'assistant',
              }),
            ]),
          })
        );
      });
    });

    it('should reset streaming state after completion', async () => {
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      const useWebSocketCall = require('../../hooks/useWebSocket').useWebSocket.mock.calls[0][0];
      const onStreamingChunk = useWebSocketCall.onStreamingChunk;

      // Stream and complete
      act(() => {
        onStreamingChunk('Test', false);
      });

      expect(screen.getByTestId('streaming-message')).toBeInTheDocument();

      act(() => {
        onStreamingChunk('', true, 'Complete');
      });

      await waitFor(() => {
        expect(screen.queryByTestId('streaming-message')).not.toBeInTheDocument();
      });
    });
  });

  describe('Session Management', () => {
    it('should end session and update status', async () => {
      const mockUpdateSession = jest.fn();
      const mockSetCurrentSession = jest.fn();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: mockSession,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: mockUpdateSession,
          setCurrentSession: mockSetCurrentSession,
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      const endSessionBtn = screen.getByTestId('end-session-btn');
      fireEvent.click(endSessionBtn);

      await waitFor(() => {
        expect(mockUpdateSession).toHaveBeenCalledWith(
          expect.objectContaining({
            status: SessionStatus.COMPLETED,
            endTime: expect.any(Date),
          })
        );
        expect(mockSetCurrentSession).toHaveBeenCalledWith(null);
      });
    });
  });

  describe('Error Handling', () => {
    it('should show error when WebSocket disconnected on send', async () => {
      mockIsConnected = false;

      const mockUpdateSession = jest.fn();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, id: 'ready-session-id' },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: mockUpdateSession,
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      // Even though session is ready, button should be disabled when not connected
      await waitFor(() => {
        const sendButton = screen.getByTestId('send-message-btn');
        expect(sendButton).toBeDisabled();
      });
    });

    it('should handle session initialization timeout', async () => {
      jest.useFakeTimers();

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      // Fast-forward time by 10 seconds (timeout threshold)
      act(() => {
        jest.advanceTimersByTime(10000);
      });

      // Note: Error would be set but we can't easily verify it without exposing error state
      // This test mainly ensures timeout logic runs without crashing

      jest.useRealTimers();
    });
  });

  describe('Session Loading', () => {
    it('should load session by ID when sessionId prop provided', async () => {
      const sessionToLoad = createMockSession({ id: 'load-session-id' });

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: null,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [sessionToLoad],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession sessionId="load-session-id" />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(require('../../contexts/AppContext').useAppContext().actions.setCurrentSession).toHaveBeenCalledWith(sessionToLoad);
      });
    });

    it('should handle session not found error', async () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: null,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession sessionId="non-existent-id" />
        </TestWrapper>
      );

      // Component should handle missing session gracefully
      await waitFor(() => {
        expect(screen.getByTestId('session-header')).toBeInTheDocument();
      });
    });

    it('should not reload session if sessionId matches current session', async () => {
      const currentSession = createMockSession({ id: 'same-id' });
      const mockSetCurrentSession = jest.fn();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [currentSession],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: mockSetCurrentSession,
        },
      });

      render(
        <TestWrapper>
          <TherapySession sessionId="same-id" />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getByTestId('session-header')).toBeInTheDocument();
      });

      // Should not call setCurrentSession since session already loaded
      expect(mockSetCurrentSession).not.toHaveBeenCalled();
    });
  });

  describe('Agent Type Placeholders', () => {
    it('should show correct placeholder for INTAKE agent', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, agentType: AgentType.INTAKE },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.INTAKE_IN_PROGRESS, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByPlaceholderText('Share some information about yourself...')).toBeInTheDocument();
    });

    it('should show correct placeholder for ASSESSMENT agent', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, agentType: AgentType.ASSESSMENT },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.ASSESSMENT_IN_PROGRESS, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByPlaceholderText('Tell me about your goals and preferences...')).toBeInTheDocument();
    });

    it('should show correct placeholder for PLANNING agent', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, agentType: AgentType.PLANNING },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByPlaceholderText('Share your thoughts on the treatment plan...')).toBeInTheDocument();
    });

    it('should show correct placeholder for REFLECTION agent', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, agentType: AgentType.REFLECTION },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByPlaceholderText('How did this session feel for you?')).toBeInTheDocument();
    });
  });

  describe('Message Input Disabled States', () => {
    it('should disable input when no current session', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: null,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      const sendButton = screen.getByTestId('send-message-btn');
      expect(sendButton).toBeDisabled();
    });

    it('should disable input when session is not ACTIVE', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, status: SessionStatus.COMPLETED },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      const sendButton = screen.getByTestId('send-message-btn');
      expect(sendButton).toBeDisabled();
    });
  });

  describe('WebSocket Message Handling', () => {
    it('should handle chat_response messages', async () => {
      const mockUpdateSession = jest.fn();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: mockSession,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: mockUpdateSession,
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      // Simulate receiving a message through lastMessage
      mockLastMessage = {
        type: 'chat_response',
        message: 'Response from therapist',
        timestamp: new Date().toISOString(),
      };

      // Re-render to trigger useEffect
      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(mockUpdateSession).toHaveBeenCalledWith(
          expect.objectContaining({
            transcript: expect.arrayContaining([
              expect.objectContaining({
                content: 'Response from therapist',
                role: 'assistant',
              }),
            ]),
          })
        );
      });
    });

    it('should not request session for non-PSYCHOANALYST agents', async () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: { ...mockSession, agentType: AgentType.INTAKE },
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.INTAKE_IN_PROGRESS, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getByTestId('session-header')).toBeInTheDocument();
      });

      // Should not request therapy session for INTAKE agent
      expect(mockRequestSession).not.toHaveBeenCalledWith('therapy');
    });
  });

  describe('Session with existing messages', () => {
    it('should render existing messages from session', () => {
      const sessionWithMessages = {
        ...mockSession,
        transcript: [
          {
            id: 'msg-1',
            content: 'Hello',
            role: 'user' as const,
            timestamp: new Date(),
            sessionId: mockSession.id,
          },
          {
            id: 'msg-2',
            content: 'Hi there',
            role: 'assistant' as const,
            timestamp: new Date(),
            sessionId: mockSession.id,
          },
        ],
      };

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          currentSession: sessionWithMessages,
          user: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE, createdAt: new Date() },
          sessions: [],
          therapyPlan: null,
          isLoading: false,
          error: null,
        },
        actions: {
          updateSession: jest.fn(),
          setCurrentSession: jest.fn(),
        },
      });

      render(
        <TestWrapper>
          <TherapySession />
        </TestWrapper>
      );

      expect(screen.getByText('Hello')).toBeInTheDocument();
      expect(screen.getByText('Hi there')).toBeInTheDocument();
    });
  });
});

// Helper to wrap act calls
function act(callback: () => void): void {
  const { act: reactAct } = require('@testing-library/react');
  reactAct(callback);
}
