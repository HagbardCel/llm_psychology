/**
 * WebSocket service for real-time communication with therapy backend
 * Uses native WebSocket API (not Socket.IO)
 */

import {
  WebSocketConfig,
  WebSocketResponse,
  ConnectionStatus,
  SessionStartedEvent,
  UserStatusEvent,
  StreamingChunkCallback,
  SessionStartedCallback,
  UserStatusCallback,
  WS_MESSAGE_TYPES
} from '../types/websocket';

export class WebSocketService {
  private socket: WebSocket | null = null;
  private config: WebSocketConfig;
  private reconnectTimeout: number | null = null;
  private currentReconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private intentionalDisconnect = false;

  // Event callbacks
  private onConnectionChange: ((status: ConnectionStatus) => void) | null = null;
  private onMessage: ((message: WebSocketResponse) => void) | null = null;
  private onStreamingChunk: StreamingChunkCallback | null = null;
  private onSessionStartedEvent: SessionStartedCallback | null = null;
  private onUserStatusEvent: UserStatusCallback | null = null;

  constructor(config: WebSocketConfig) {
    this.config = config;
    this.maxReconnectAttempts = config.reconnectAttempts || 5;
    this.reconnectDelay = config.reconnectDelay || 1000;
  }

  /**
   * Connect to WebSocket server
   */
  async connect(): Promise<boolean> {
    try {
      this.intentionalDisconnect = false;
      this.updateConnectionStatus({ isConnected: false, isConnecting: true });

      // Construct WebSocket URL with query parameters (user_id and token)
      let wsUrl = `${this.config.url.replace(/^http/, 'ws')}/ws?user_id=${encodeURIComponent(this.config.userId)}`;

      // Add token if available
      if (this.config.authToken) {
        wsUrl += `&token=${encodeURIComponent(this.config.authToken)}`;
      }

      this.socket = new WebSocket(wsUrl);
      this.setupEventHandlers();

      return new Promise((resolve) => {
        if (!this.socket) {
          resolve(false);
          return;
        }

        // Set up one-time handlers for connection result
        const handleOpen = () => {
          this.currentReconnectAttempts = 0;
          this.updateConnectionStatus({
            isConnected: true,
            isConnecting: false,
            lastConnected: new Date()
          });
          resolve(true);
        };

        const handleError = () => {
          this.updateConnectionStatus({
            isConnected: false,
            isConnecting: false,
            connectionError: 'Connection failed'
          });
          resolve(false);
        };

        // Add temporary listeners
        this.socket.addEventListener('open', handleOpen, { once: true });
        this.socket.addEventListener('error', handleError, { once: true });
      });
    } catch (error) {
      console.error('Failed to connect:', error);
      this.updateConnectionStatus({
        isConnected: false,
        isConnecting: false,
        connectionError: error instanceof Error ? error.message : 'Connection failed'
      });
      return false;
    }
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void {
    this.intentionalDisconnect = true;

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }

    this.updateConnectionStatus({ isConnected: false, isConnecting: false });
  }

  /**
   * Send a message to the server
   */
  sendMessage(type: string, data: Record<string, any> = {}): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      console.warn('Cannot send message: not connected');
      return;
    }

    const message = {
      type,
      data
    };

    this.socket.send(JSON.stringify(message));
  }

  /**
   * Send a chat message
   */
  sendChatMessage(message: string): void {
    this.sendMessage(WS_MESSAGE_TYPES.CHAT_MESSAGE, { message });
  }

  /**
   * Send typing start indicator
   */
  startTyping(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.sendMessage(WS_MESSAGE_TYPES.TYPING_START);
    }
  }

  /**
   * Send typing stop indicator
   */
  stopTyping(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.sendMessage(WS_MESSAGE_TYPES.TYPING_STOP);
    }
  }

  /**
   * Send ping for connection testing
   */
  ping(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.sendMessage(WS_MESSAGE_TYPES.PING, { timestamp: Date.now() });
    }
  }

  /**
   * Request to start a therapy session
   */
  requestSession(sessionType: string = 'therapy'): void {
    this.sendMessage(WS_MESSAGE_TYPES.SESSION_REQUEST, { session_type: sessionType });
  }

  /**
   * Set connection status change callback
   */
  onConnectionStatusChange(callback: (status: ConnectionStatus) => void): void {
    this.onConnectionChange = callback;
  }

  /**
   * Set message received callback
   */
  onMessageReceived(callback: (message: WebSocketResponse) => void): void {
    this.onMessage = callback;
  }

  /**
   * Set streaming chunk callback
   */
  onStreamingChunkReceived(callback: StreamingChunkCallback): void {
    this.onStreamingChunk = callback;
  }

  /**
   * Set session started event callback
   */
  onSessionStarted(callback: SessionStartedCallback): void {
    this.onSessionStartedEvent = callback;
  }

  /**
   * Set user status event callback
   */
  onUserStatus(callback: UserStatusCallback): void {
    this.onUserStatusEvent = callback;
  }

  /**
   * Get current connection status
   */
  isConnected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  private setupEventHandlers(): void {
    if (!this.socket) return;

    this.socket.onopen = () => {
      console.log('WebSocket connected');
      this.updateConnectionStatus({
        isConnected: true,
        isConnecting: false,
        lastConnected: new Date()
      });
    };

    this.socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        this.handleMessage(message);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    this.socket.onclose = (event) => {
      console.log('WebSocket disconnected:', event.code, event.reason);
      this.updateConnectionStatus({ isConnected: false, isConnecting: false });

      // Attempt to reconnect if disconnection was not intentional
      if (!this.intentionalDisconnect && event.code !== 1000) {
        this.attemptReconnect();
      }
    };

    this.socket.onerror = (error) => {
      console.error('WebSocket error:', error);
      this.updateConnectionStatus({
        isConnected: false,
        isConnecting: false,
        connectionError: 'WebSocket error'
      });
    };
  }

  private handleMessage(message: any): void {
    if (!message.type) {
      console.warn('Received message without type:', message);
      return;
    }

    // Handle specific message types
    switch (message.type) {
      case WS_MESSAGE_TYPES.CONNECTED:
        console.log('Connection confirmed:', message.data);
        break;

      case WS_MESSAGE_TYPES.CHAT_RESPONSE_CHUNK:
        if (this.onStreamingChunk && message.data) {
          this.onStreamingChunk(
            message.data.chunk || '',
            message.data.is_complete || false,
            message.data.full_response
          );
        }
        break;

      case WS_MESSAGE_TYPES.SESSION_STARTED:
        console.log('Session started:', message.data);
        if (this.onSessionStartedEvent && message.data) {
          this.onSessionStartedEvent(message.data as SessionStartedEvent);
        }
        break;

      case WS_MESSAGE_TYPES.USER_STATUS:
        console.log('User status received:', message.data);
        if (this.onUserStatusEvent && message.data) {
          this.onUserStatusEvent(message.data as UserStatusEvent);
        }
        break;

      case WS_MESSAGE_TYPES.TYPING_START:
        console.log('Therapist is typing...');
        break;

      case WS_MESSAGE_TYPES.TYPING_STOP:
        console.log('Therapist stopped typing');
        break;

      case WS_MESSAGE_TYPES.STYLE_SELECTED:
        console.log('Style selected:', message.data);
        break;

      case WS_MESSAGE_TYPES.SESSION_EXTENDED:
        console.log('Session extended:', message.data);
        break;

      case WS_MESSAGE_TYPES.PONG:
        console.log('Received pong:', message.data);
        break;

      default:
        // Pass generic messages to the general message handler
        if (this.onMessage) {
          this.onMessage(message as WebSocketResponse);
        }
    }
  }

  private updateConnectionStatus(status: Partial<ConnectionStatus>): void {
    if (this.onConnectionChange) {
      // Get current status and merge with updates
      const currentStatus: ConnectionStatus = {
        isConnected: false,
        isConnecting: false,
        ...status
      };
      this.onConnectionChange(currentStatus);
    }
  }

  private attemptReconnect(): void {
    if (this.currentReconnectAttempts >= this.maxReconnectAttempts) {
      console.log('Max reconnection attempts reached');
      this.updateConnectionStatus({
        isConnected: false,
        isConnecting: false,
        connectionError: 'Max reconnection attempts reached'
      });
      return;
    }

    this.currentReconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.currentReconnectAttempts - 1); // Exponential backoff

    console.log(`Attempting to reconnect in ${delay}ms (attempt ${this.currentReconnectAttempts}/${this.maxReconnectAttempts})`);

    this.updateConnectionStatus({ isConnected: false, isConnecting: true });

    this.reconnectTimeout = window.setTimeout(() => {
      this.connect();
    }, delay);
  }
}
