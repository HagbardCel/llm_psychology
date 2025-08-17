/**
 * WebSocket service for real-time communication with therapy backend
 */

import { io, Socket } from 'socket.io-client';
import {
  WebSocketConfig,
  WebSocketMessage,
  WebSocketResponse,
  ConnectionStatus,
  ConnectionEvent
} from '../types/websocket';

export class WebSocketService {
  private socket: Socket | null = null;
  private config: WebSocketConfig;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private currentReconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  
  // Event callbacks
  private onConnectionChange: ((status: ConnectionStatus) => void) | null = null;
  private onMessage: ((message: WebSocketResponse) => void) | null = null;

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
      this.updateConnectionStatus({ isConnected: false, isConnecting: true });

      this.socket = io(this.config.url, {
        auth: {
          user_id: this.config.userId,
          token: this.config.authToken
        },
        autoConnect: false,
        reconnection: false // We'll handle reconnection manually
      });

      this.setupEventHandlers();
      this.socket.connect();

      return new Promise((resolve) => {
        if (!this.socket) {
          resolve(false);
          return;
        }

        this.socket.on('connect', () => {
          this.currentReconnectAttempts = 0;
          this.updateConnectionStatus({ 
            isConnected: true, 
            isConnecting: false,
            lastConnected: new Date()
          });
          resolve(true);
        });

        this.socket.on('connect_error', (error) => {
          this.updateConnectionStatus({ 
            isConnected: false, 
            isConnecting: false,
            connectionError: error.message
          });
          resolve(false);
        });
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
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }

    this.updateConnectionStatus({ isConnected: false, isConnecting: false });
  }

  /**
   * Send a message to the server
   */
  sendMessage(type: string, data: Record<string, any> = {}): void {
    if (!this.socket || !this.socket.connected) {
      console.warn('Cannot send message: not connected');
      return;
    }

    const message: WebSocketMessage = {
      type,
      data,
      timestamp: new Date().toISOString()
    };

    this.socket.emit('message', message);
  }

  /**
   * Send a chat message
   */
  sendChatMessage(message: string): void {
    this.sendMessage('chat_message', { message });
  }

  /**
   * Send typing start indicator
   */
  startTyping(): void {
    if (this.socket && this.socket.connected) {
      this.socket.emit('typing_start', {});
    }
  }

  /**
   * Send typing stop indicator
   */
  stopTyping(): void {
    if (this.socket && this.socket.connected) {
      this.socket.emit('typing_stop', {});
    }
  }

  /**
   * Send ping for connection testing
   */
  ping(): void {
    if (this.socket && this.socket.connected) {
      this.socket.emit('ping', { timestamp: Date.now() });
    }
  }

  /**
   * Request to start a therapy session
   */
  requestSession(sessionType: string = 'therapy'): void {
    this.sendMessage('session_request', { session_type: sessionType });
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
   * Get current connection status
   */
  isConnected(): boolean {
    return this.socket?.connected || false;
  }

  private setupEventHandlers(): void {
    if (!this.socket) return;

    this.socket.on('connect', () => {
      console.log('Connected to WebSocket server');
    });

    this.socket.on('disconnect', (reason) => {
      console.log('Disconnected from WebSocket server:', reason);
      this.updateConnectionStatus({ isConnected: false, isConnecting: false });
      
      // Attempt to reconnect if disconnection was not intentional
      if (reason === 'io server disconnect') {
        // Server initiated disconnect, don't reconnect
        return;
      }
      
      this.attemptReconnect();
    });

    this.socket.on('response', (data: WebSocketResponse) => {
      if (this.onMessage) {
        this.onMessage(data);
      }
    });

    this.socket.on('error', (error: any) => {
      console.error('WebSocket error:', error);
      this.updateConnectionStatus({ 
        isConnected: false, 
        isConnecting: false,
        connectionError: error.message || 'WebSocket error'
      });
    });

    this.socket.on('connected', (data: ConnectionEvent) => {
      console.log('Connection confirmed:', data);
    });

    this.socket.on('pong', (data: any) => {
      console.log('Received pong:', data);
    });
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

    this.reconnectTimeout = setTimeout(() => {
      if (this.socket) {
        this.socket.connect();
      }
    }, delay);
  }
}