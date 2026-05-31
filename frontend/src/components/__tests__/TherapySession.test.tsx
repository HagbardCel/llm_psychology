import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { BrowserRouter } from 'react-router';

import { TherapySession } from '../TherapySession';
import { AppProvider } from '../../contexts/AppContext';
import type { SessionStartedEvent } from '../../types/websocket';

const mockSendChatMessage = vi.fn();
const mockSendEndSession = vi.fn();
const mockRegisterStreamingChunkHandler = vi.fn();
const mockRegisterSessionStartedHandler = vi.fn();
const mockRegisterSessionEndedHandler = vi.fn();
const mockRegisterWorkflowNextActionHandler = vi.fn();

let mockIsConnected = true;
let mockConnectionStatus = { isConnected: true, isConnecting: false };
let mockLastMessage: any = null;
let streamingHandler: ((chunk: string, isComplete: boolean, fullResponse?: string) => void) | null = null;
let sessionStartedHandler: ((event: SessionStartedEvent) => void) | null = null;
let sessionEndedHandler: (() => void) | null = null;

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocketContext: vi.fn(() => {
    return {
      connectionStatus: mockConnectionStatus,
      lastMessage: mockLastMessage,
      sendChatMessage: mockSendChatMessage,
      sendEndSession: mockSendEndSession,
      isConnected: mockIsConnected,
      registerStreamingChunkHandler: mockRegisterStreamingChunkHandler,
      registerSessionStartedHandler: mockRegisterSessionStartedHandler,
      registerSessionEndedHandler: mockRegisterSessionEndedHandler,
      registerWorkflowNextActionHandler: mockRegisterWorkflowNextActionHandler,
    };
  }),
}));

vi.mock('../SessionHeader', () => ({
  SessionHeader: ({ onEndSession }: any) => (
    <div data-testid="session-header">
      <button onClick={onEndSession} data-testid="end-session-btn">
        End Session
      </button>
    </div>
  ),
}));

vi.mock('../MessageHistory', () => ({
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

vi.mock('../MessageInput', () => ({
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

vi.mock('../ConnectionStatus', () => ({
  ConnectionStatus: ({ status }: any) => (
    <div data-testid="connection-status">
      {status.isConnected ? 'Connected' : 'Disconnected'}
    </div>
  ),
}));

describe('TherapySession', () => {
  const TestWrapper = ({ children }: { children: React.ReactNode }) => (
    <BrowserRouter>
      <AppProvider>{children}</AppProvider>
    </BrowserRouter>
  );

  beforeEach(() => {
    vi.clearAllMocks();
    mockIsConnected = true;
    mockConnectionStatus = { isConnected: true, isConnecting: false };
    mockLastMessage = null;
    streamingHandler = null;
    sessionStartedHandler = null;
    sessionEndedHandler = null;
    mockRegisterStreamingChunkHandler.mockImplementation((handler) => {
      streamingHandler = handler;
      return () => {
        streamingHandler = null;
      };
    });
    mockRegisterSessionStartedHandler.mockImplementation((handler) => {
      sessionStartedHandler = handler;
      return () => {
        sessionStartedHandler = null;
      };
    });
    mockRegisterSessionEndedHandler.mockImplementation((handler) => {
      sessionEndedHandler = handler;
      return () => {
        sessionEndedHandler = null;
      };
    });
    mockRegisterWorkflowNextActionHandler.mockImplementation(() => () => {});
    localStorage.setItem('current_user_id', 'test-user-id');
  });

  function emitSessionStarted(overrides?: Partial<SessionStartedEvent>) {
    const event: SessionStartedEvent = {
      session_id: 'server-session-id',
      agent_type: 'THERAPIST',
      workflow_state: 'therapy_in_progress',
      created_at: new Date().toISOString(),
      user_id: 'test-user-id',
      session_type: 'therapy',
      selected_therapy_style: 'cbt',
      ...overrides,
    };

    act(() => {
      sessionStartedHandler?.(event);
    });
  }

  function emitStreamingChunk(chunk: string, isComplete: boolean, fullResponse?: string) {
    act(() => {
      streamingHandler?.(chunk, isComplete, fullResponse);
    });
  }

  it('renders header, history, input, and connection status', () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    expect(screen.getByTestId('session-header')).toBeInTheDocument();
    expect(screen.getByTestId('message-history')).toBeInTheDocument();
    expect(screen.getByTestId('message-input')).toBeInTheDocument();
    expect(screen.getByTestId('connection-status')).toBeInTheDocument();
  });

  it('disables input until the initial greeting completes', () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    expect(screen.getByTestId('send-message-btn')).toBeDisabled();
  });

  it('enables input after the initial greeting completes', async () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    emitSessionStarted();
    emitStreamingChunk('Hello', false);
    emitStreamingChunk('', true, 'Hello');

    await waitFor(() => {
      expect(screen.getByTestId('send-message-btn')).not.toBeDisabled();
    });
  });

  it('sends a chat message over the WebSocket', async () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    emitSessionStarted();
    emitStreamingChunk('Hello', false);
    emitStreamingChunk('', true, 'Hello');

    await waitFor(() => {
      expect(screen.getByTestId('send-message-btn')).not.toBeDisabled();
    });

    fireEvent.click(screen.getByTestId('send-message-btn'));

    await waitFor(() => {
      expect(mockSendChatMessage).toHaveBeenCalledWith('Test message');
    });
  });

  it('shows the agent-type placeholder after session_started', async () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    emitSessionStarted({ agent_type: 'INTAKE' });

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText('Share some information about yourself...')
      ).toBeInTheDocument();
    });
  });

  it('accumulates streaming chunks and shows them in the UI', async () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    emitSessionStarted();

    emitStreamingChunk('Hello', false);
    await waitFor(() => {
      expect(screen.getByTestId('streaming-message')).toHaveTextContent('Hello');
    });

    emitStreamingChunk(' world', false);
    await waitFor(() => {
      expect(screen.getByTestId('streaming-message')).toHaveTextContent('Hello world');
    });
  });

  it('adds the final assistant message when streaming completes', async () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    emitSessionStarted();

    emitStreamingChunk('', true, 'Complete response from agent');

    await waitFor(() => {
      expect(screen.getByTestId('message-0')).toHaveTextContent('Complete response from agent');
    });
  });

  it('ends the session and disables input', async () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    emitSessionStarted();
    emitStreamingChunk('Hello', false);
    emitStreamingChunk('', true, 'Hello');

    await waitFor(() => {
      expect(screen.getByTestId('send-message-btn')).not.toBeDisabled();
    });

    fireEvent.click(screen.getByTestId('end-session-btn'));
    act(() => {
      sessionEndedHandler?.();
    });

    await waitFor(() => {
      expect(mockSendEndSession).toHaveBeenCalledWith('User ended session');
      expect(screen.getByTestId('send-message-btn')).toBeDisabled();
    });
  });

  it('renders disconnected status when socket is down', async () => {
    mockIsConnected = false;
    mockConnectionStatus = { isConnected: false, isConnecting: false };

    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(screen.getByText('Disconnected')).toBeInTheDocument();
    });
  });
});
