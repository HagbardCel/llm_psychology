/**
 * React hook for WebSocket communication
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { WebSocketService } from '../services/websocketService';
import {
  ConnectionStatus,
  WebSocketResponse,
  WebSocketConfig,
  SessionStartedEvent,
  UserStatusEvent,
  StreamingChunkCallback,
  SessionStartedCallback,
  UserStatusCallback
} from '../types/websocket';

interface UseWebSocketOptions {
  url?: string;
  userId: string;
  authToken: string;
  autoConnect?: boolean;
  reconnectAttempts?: number;
  reconnectDelay?: number;
  onStreamingChunk?: StreamingChunkCallback;
  onSessionStarted?: SessionStartedCallback;
  onUserStatus?: UserStatusCallback;
}

interface UseWebSocketReturn {
  connectionStatus: ConnectionStatus;
  lastMessage: WebSocketResponse | null;
  sendMessage: (type: string, data?: Record<string, any>) => void;
  sendChatMessage: (message: string) => void;
  startTyping: () => void;
  stopTyping: () => void;
  connect: () => Promise<boolean>;
  disconnect: () => void;
  requestSession: (sessionType?: string) => void;
  ping: () => void;
  isConnected: boolean;
}

export const useWebSocket = (options: UseWebSocketOptions): UseWebSocketReturn => {
  const {
    url = 'http://localhost:8000',
    userId,
    authToken,
    autoConnect = true,
    reconnectAttempts = 5,
    reconnectDelay = 1000,
    onStreamingChunk,
    onSessionStarted,
    onUserStatus
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
      authToken,
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
    if (onUserStatus) {
      serviceRef.current.onUserStatus(onUserStatus);
    }

    return () => {
      if (serviceRef.current) {
        serviceRef.current.disconnect();
        serviceRef.current = null;
      }
    };
  }, [url, userId, authToken, reconnectAttempts, reconnectDelay, onStreamingChunk, onSessionStarted, onUserStatus]);

  // Auto-connect if enabled
  useEffect(() => {
    if (autoConnect && serviceRef.current) {
      serviceRef.current.connect();
    }
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

  const startTyping = useCallback((): void => {
    if (serviceRef.current) {
      serviceRef.current.startTyping();
    }
  }, []);

  const stopTyping = useCallback((): void => {
    if (serviceRef.current) {
      serviceRef.current.stopTyping();
    }
  }, []);

  const requestSession = useCallback((sessionType: string = 'therapy'): void => {
    if (serviceRef.current) {
      serviceRef.current.requestSession(sessionType);
    }
  }, []);

  const ping = useCallback((): void => {
    if (serviceRef.current) {
      serviceRef.current.ping();
    }
  }, []);

  return {
    connectionStatus,
    lastMessage,
    sendMessage,
    sendChatMessage,
    startTyping,
    stopTyping,
    connect,
    disconnect,
    requestSession,
    ping,
    isConnected: connectionStatus.isConnected
  };
};