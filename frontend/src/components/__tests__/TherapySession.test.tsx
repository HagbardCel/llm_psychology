import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';

import { TherapySession } from '../TherapySession';
import { AppProvider } from '../../contexts/AppContext';
import type { SessionStartedEvent } from '../../types/websocket';
import { useWebSocket } from '../../hooks/useWebSocket';

const mockSendChatMessage = jest.fn();
const mockRequestSession = jest.fn();

let mockIsConnected = true;
let mockConnectionStatus = { isConnected: true, isConnecting: false };
let mockLastMessage: any = null;

jest.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: jest.fn((_config) => {
    return {
      connectionStatus: mockConnectionStatus,
      lastMessage: mockLastMessage,
      sendChatMessage: mockSendChatMessage,
      requestSession: mockRequestSession,
      isConnected: mockIsConnected,
    };
  }),
}));

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
    localStorage.setItem('current_user_id', 'test-user-id');
  });

  function emitSessionStarted(overrides?: Partial<SessionStartedEvent>) {
    const useWebSocketCall = (useWebSocket as jest.MockedFunction<typeof useWebSocket>).mock.calls[0][0];
    const onSessionStarted = useWebSocketCall.onSessionStarted;

    const event: SessionStartedEvent = {
      session_id: 'server-session-id',
      agent_type: 'PSYCHOANALYST',
      workflow_state: 'therapy_in_progress',
      created_at: new Date().toISOString(),
      user_id: 'test-user-id',
      has_initial_message: false,
      ...overrides,
    };

    act(() => {
      onSessionStarted(event);
    });
  }

  function emitStreamingChunk(chunk: string, isComplete: boolean, fullResponse?: string) {
    const useWebSocketCall = (useWebSocket as jest.MockedFunction<typeof useWebSocket>).mock.calls[0][0];
    const onStreamingChunk = useWebSocketCall.onStreamingChunk;

    act(() => {
      onStreamingChunk(chunk, isComplete, fullResponse);
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

  it('requests a session when connected', async () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(mockRequestSession).toHaveBeenCalledWith('therapy');
    });
  });

  it('disables input until session_started is received', () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    expect(screen.getByTestId('send-message-btn')).toBeDisabled();
  });

  it('enables input after session_started', async () => {
    render(
      <TestWrapper>
        <TherapySession />
      </TestWrapper>
    );

    emitSessionStarted();

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

    await waitFor(() => {
      expect(screen.getByTestId('send-message-btn')).not.toBeDisabled();
    });

    fireEvent.click(screen.getByTestId('end-session-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('send-message-btn')).toBeDisabled();
    });
  });

  it('does not request a session when disconnected', async () => {
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

    expect(mockRequestSession).not.toHaveBeenCalled();
  });
});
