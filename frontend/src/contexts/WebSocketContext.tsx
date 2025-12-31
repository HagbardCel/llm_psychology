import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAppContext } from './AppContext';
import { useWebSocket } from '../hooks/useWebSocket';
import type {
  AssessmentRecommendationsEvent,
  ConnectionStatus,
  WebSocketResponse,
  StreamingChunkCallback,
  SessionStartedEvent,
  WorkflowNextActionEvent
} from '../types/websocket';
import { WS_MESSAGE_TYPES } from '../types/websocket';

interface WebSocketContextValue {
  connectionStatus: ConnectionStatus;
  lastMessage: WebSocketResponse | null;
  assessmentRecommendations: AssessmentRecommendationsEvent | null;
  sendMessage: (type: string, data?: Record<string, any>) => void;
  sendChatMessage: (message: string) => void;
  connect: () => Promise<boolean>;
  disconnect: () => void;
  isConnected: boolean;
  registerStreamingChunkHandler: (handler: StreamingChunkCallback) => () => void;
  registerSessionStartedHandler: (handler: (event: SessionStartedEvent) => void) => () => void;
  registerWorkflowNextActionHandler: (handler: (event: WorkflowNextActionEvent) => void) => () => void;
}

const WebSocketContext = createContext<WebSocketContextValue | undefined>(undefined);

interface WebSocketProviderProps {
  children: ReactNode;
}

export function WebSocketProvider({ children }: WebSocketProviderProps) {
  const { currentUserId, currentSessionId, setCurrentSessionId } = useAppContext();
  const queryClient = useQueryClient();
  const [assessmentRecommendations, setAssessmentRecommendations] =
    useState<AssessmentRecommendationsEvent | null>(null);

  const streamingHandlers = useRef<StreamingChunkCallback[]>([]);
  const sessionStartedHandlers = useRef<Array<(event: SessionStartedEvent) => void>>([]);
  const workflowHandlers = useRef<Array<(event: WorkflowNextActionEvent) => void>>([]);

  const handleStreamingChunk = useCallback<StreamingChunkCallback>(
    (chunk, isComplete, fullResponse) => {
      streamingHandlers.current.forEach((handler) => {
        handler(chunk, isComplete, fullResponse);
      });
    },
    []
  );

  const handleSessionStarted = useCallback((event: SessionStartedEvent) => {
    setCurrentSessionId(event.session_id);
    sessionStartedHandlers.current.forEach((handler) => {
      handler(event);
    });
  }, [setCurrentSessionId]);

  const handleWorkflowNextAction = useCallback((event: WorkflowNextActionEvent) => {
    if (event.user_id && currentSessionId) {
      queryClient.setQueryData(['workflow', 'next', event.user_id, currentSessionId], event);
    }
    workflowHandlers.current.forEach((handler) => {
      handler(event);
    });
  }, [currentSessionId, queryClient]);

  const {
    connectionStatus,
    lastMessage,
    sendMessage,
    sendChatMessage,
    connect,
    disconnect,
    isConnected
  } = useWebSocket({
    userId: currentUserId || '',
    autoConnect: !!currentUserId && !!currentSessionId,
    onStreamingChunk: handleStreamingChunk,
    onSessionStarted: handleSessionStarted,
    onWorkflowNextAction: handleWorkflowNextAction,
  });

  useEffect(() => {
    if (!lastMessage || lastMessage.type !== WS_MESSAGE_TYPES.ASSESSMENT_RECOMMENDATIONS) {
      return;
    }
    setAssessmentRecommendations(lastMessage.data as AssessmentRecommendationsEvent);
  }, [lastMessage]);

  const registerStreamingChunkHandler = useCallback((handler: StreamingChunkCallback) => {
    streamingHandlers.current = [...streamingHandlers.current, handler];
    return () => {
      streamingHandlers.current = streamingHandlers.current.filter(
        (candidate) => candidate !== handler
      );
    };
  }, []);

  const registerSessionStartedHandler = useCallback((handler: (event: SessionStartedEvent) => void) => {
    sessionStartedHandlers.current = [...sessionStartedHandlers.current, handler];
    return () => {
      sessionStartedHandlers.current = sessionStartedHandlers.current.filter(
        (candidate) => candidate !== handler
      );
    };
  }, []);

  const registerWorkflowNextActionHandler = useCallback(
    (handler: (event: WorkflowNextActionEvent) => void) => {
      workflowHandlers.current = [...workflowHandlers.current, handler];
      return () => {
        workflowHandlers.current = workflowHandlers.current.filter(
          (candidate) => candidate !== handler
        );
      };
    },
    []
  );

  return (
    <WebSocketContext.Provider
      value={{
        connectionStatus,
        lastMessage,
        assessmentRecommendations,
        sendMessage,
        sendChatMessage,
        connect,
        disconnect,
        isConnected,
        registerStreamingChunkHandler,
        registerSessionStartedHandler,
        registerWorkflowNextActionHandler,
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocketContext() {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocketContext must be used within WebSocketProvider');
  }
  return context;
}
