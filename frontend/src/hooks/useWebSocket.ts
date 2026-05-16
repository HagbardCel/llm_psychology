/**
 * React hook for WebSocket communication
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { WebSocketService } from '../services/websocketService';
import { getWebSocketBaseUrl } from '../config/env';
import {
  ConnectionStatus,
  WebSocketResponse,
  WebSocketConfig,
  StreamingChunkCallback,
  SessionStartedCallback,
  SessionEndedEvent,
  WorkflowNextActionEvent
} from '../types/websocket';

interface UseWebSocketOptions {
  url?: string;
  userId: string;
  autoConnect?: boolean;
  reconnectAttempts?: number;
  reconnectDelay?: number;
  onStreamingChunk?: StreamingChunkCallback;
  onSessionStarted?: SessionStartedCallback;
  onSessionEnded?: (event: SessionEndedEvent) => void;
  onWorkflowNextAction?: (event: WorkflowNextActionEvent) => void;
}

interface UseWebSocketReturn {
  connectionStatus: ConnectionStatus;
  lastMessage: WebSocketResponse | null;
  sendMessage: (type: string, data?: Record<string, any>) => void;
  sendChatMessage: (message: string) => void;
  sendEndSession: (reason?: string) => void;
  connect: () => Promise<boolean>;
  disconnect: () => void;
  isConnected: boolean;
}

export const useWebSocket = (options: UseWebSocketOptions): UseWebSocketReturn => {
  const {
    url = getWebSocketBaseUrl(),
    userId,
    autoConnect = true,
    reconnectAttempts = 5,
    reconnectDelay = 1000,
    onStreamingChunk,
    onSessionStarted,
    onSessionEnded,
    onWorkflowNextAction
  } = options;

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({
    isConnected: false,
    isConnecting: false
  });

  const [lastMessage, setLastMessage] = useState<WebSocketResponse | null>(null);
  const serviceRef = useRef<WebSocketService | null>(null);

  // Initialize WebSocket service
  useEffect(() => {
    const config: WebSocketConfig = {
      url,
      userId,
      reconnectAttempts,
      reconnectDelay
    };

    serviceRef.current = new WebSocketService(config);

    // Set up event handlers
    serviceRef.current.onConnectionStatusChange(setConnectionStatus);
    serviceRef.current.onMessageReceived(setLastMessage);

    // Set up streaming event handlers
    if (onStreamingChunk) {
      serviceRef.current.onStreamingChunkReceived(onStreamingChunk);
    }
    if (onSessionStarted) {
      serviceRef.current.onSessionStarted(onSessionStarted);
    }
    if (onSessionEnded) {
      serviceRef.current.onSessionEnded(onSessionEnded);
    }
    if (onWorkflowNextAction) {
      serviceRef.current.onWorkflowNextAction(onWorkflowNextAction);
    }
    return () => {
      if (serviceRef.current) {
        serviceRef.current.disconnect();
        serviceRef.current = null;
      }
    };
  }, [
    url,
    userId,
    reconnectAttempts,
    reconnectDelay,
    onStreamingChunk,
    onSessionStarted,
    onSessionEnded,
    onWorkflowNextAction
  ]);

  // Auto-connect if enabled
  useEffect(() => {
    if (autoConnect && serviceRef.current) {
      serviceRef.current.connect();
    }
  }, [autoConnect]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const handleOffline = () => {
      setConnectionStatus((prev) => ({
        ...prev,
        isConnected: false,
        isConnecting: false,
        connectionError: 'Offline',
      }));
      serviceRef.current?.disconnect();
    };

    const handleOnline = () => {
      if (autoConnect && serviceRef.current) {
        serviceRef.current.connect();
      }
    };

    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);

    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, [autoConnect]);

  const connect = useCallback(async (): Promise<boolean> => {
    if (!serviceRef.current) return false;
    return await serviceRef.current.connect();
  }, []);

  const disconnect = useCallback((): void => {
    if (serviceRef.current) {
      serviceRef.current.disconnect();
    }
  }, []);

  const sendMessage = useCallback((type: string, data: Record<string, any> = {}): void => {
    if (serviceRef.current) {
      serviceRef.current.sendMessage(type, data);
    }
  }, []);

  const sendChatMessage = useCallback((message: string): void => {
    if (serviceRef.current) {
      serviceRef.current.sendChatMessage(message);
    }
  }, []);

  const sendEndSession = useCallback((reason?: string): void => {
    if (serviceRef.current) {
      serviceRef.current.sendEndSession(reason);
    }
  }, []);

  return {
    connectionStatus,
    lastMessage,
    sendMessage,
    sendChatMessage,
    sendEndSession,
    connect,
    disconnect,
    isConnected: connectionStatus.isConnected
  };
};
