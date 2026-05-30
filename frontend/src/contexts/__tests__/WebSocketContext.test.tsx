import { act, render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WebSocketProvider, useWebSocketContext } from '../WebSocketContext';
import type {
  SessionEndedEvent,
  SessionStartedEvent,
  StreamingChunkCallback,
  WorkflowNextActionEvent,
} from '../../types/websocket';

const setCurrentSessionId = vi.fn();
let currentSessionId: string | null = 'stale-session';
let useWebSocketOptions: any = null;

vi.mock('../AppContext', () => ({
  useAppContext: () => ({
    currentUserId: 'user-1',
    currentSessionId,
    setCurrentSessionId,
  }),
}));

vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: (options: any) => {
    useWebSocketOptions = options;
    return {
      connectionStatus: { isConnected: true, isConnecting: false },
      lastMessage: null,
      sendMessage: vi.fn(),
      sendChatMessage: vi.fn(),
      sendEndSession: vi.fn(),
      connect: vi.fn(),
      disconnect: vi.fn(),
      isConnected: true,
    };
  },
}));

function Probe({
  onReady,
}: {
  onReady: (context: ReturnType<typeof useWebSocketContext>) => void;
}) {
  const context = useWebSocketContext();
  onReady(context);
  return null;
}

function renderProvider(
  queryClient: QueryClient,
  onReady: (context: ReturnType<typeof useWebSocketContext>) => void = vi.fn()
) {
  return render(
    <QueryClientProvider client={queryClient}>
      <WebSocketProvider>
        <Probe onReady={onReady} />
      </WebSocketProvider>
    </QueryClientProvider>
  );
}

function sessionStarted(overrides: Partial<SessionStartedEvent> = {}): SessionStartedEvent {
  return {
    session_id: 'server-session',
    agent_type: 'PSYCHOANALYST',
    workflow_state: 'therapy_in_progress',
    created_at: new Date().toISOString(),
    user_id: 'user-1',
    ...overrides,
  };
}

function workflowNextAction(
  overrides: Partial<WorkflowNextActionEvent> = {}
): WorkflowNextActionEvent {
  return {
    user_id: 'user-1',
    workflow_state: 'assessment_complete',
    required_action: 'select_therapy_style',
    required_fields: ['selected_therapy_style'],
    defaults: null,
    prompt: 'Select a therapy style.',
    blocking: true,
    timestamp: new Date().toISOString(),
    state_signature: 'assessment-complete-select-style',
    ...overrides,
  };
}

describe('WebSocketProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentSessionId = 'stale-session';
    useWebSocketOptions = null;
  });

  it('stores workflow next action under the server-confirmed session after reconnect', () => {
    const queryClient = new QueryClient();
    renderProvider(queryClient);

    act(() => {
      useWebSocketOptions.onSessionStarted(sessionStarted());
      useWebSocketOptions.onWorkflowNextAction(workflowNextAction());
    });

    expect(setCurrentSessionId).toHaveBeenCalledWith('server-session');
    expect(
      queryClient.getQueryData(['workflow', 'next', 'user-1', 'server-session'])
    ).toMatchObject({ required_action: 'select_therapy_style' });
    expect(
      queryClient.getQueryData(['workflow', 'next', 'user-1', 'stale-session'])
    ).toBeUndefined();
  });

  it('replays the latest session_started event to late subscribers', () => {
    const queryClient = new QueryClient();
    const contextRef: { current: ReturnType<typeof useWebSocketContext> | null } = {
      current: null,
    };
    renderProvider(queryClient, (value: ReturnType<typeof useWebSocketContext>) => {
      contextRef.current = value;
    });

    act(() => {
      useWebSocketOptions.onSessionStarted(sessionStarted());
    });

    const handler = vi.fn();
    act(() => {
      contextRef.current?.registerSessionStartedHandler(handler);
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: 'server-session' })
    );
  });

  it('clears the server-confirmed session on session end', () => {
    const queryClient = new QueryClient();
    renderProvider(queryClient);

    act(() => {
      useWebSocketOptions.onSessionStarted(sessionStarted());
      useWebSocketOptions.onSessionEnded({
        reason: 'done',
        workflow_state: 'plan_update_complete',
      } satisfies SessionEndedEvent);
      useWebSocketOptions.onWorkflowNextAction(workflowNextAction());
    });

    expect(setCurrentSessionId).toHaveBeenLastCalledWith(null);
    expect(
      queryClient.getQueryData(['workflow', 'next', 'user-1', 'server-session'])
    ).toBeUndefined();
  });

  it('exposes handler registration methods', () => {
    const queryClient = new QueryClient();
    const contextRef: { current: ReturnType<typeof useWebSocketContext> | null } = {
      current: null,
    };
    renderProvider(queryClient, (value: ReturnType<typeof useWebSocketContext>) => {
      contextRef.current = value;
    });

    expect(typeof contextRef.current?.registerStreamingChunkHandler).toBe('function');
    expect(typeof contextRef.current?.registerWorkflowNextActionHandler).toBe('function');

    const unsubscribeStreaming = contextRef.current?.registerStreamingChunkHandler(
      vi.fn() as StreamingChunkCallback
    );
    const unsubscribeWorkflow = contextRef.current?.registerWorkflowNextActionHandler(
      vi.fn() as (event: WorkflowNextActionEvent) => void
    );

    expect(typeof unsubscribeStreaming).toBe('function');
    expect(typeof unsubscribeWorkflow).toBe('function');
  });
});
