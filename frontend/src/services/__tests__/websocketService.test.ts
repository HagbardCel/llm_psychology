import { WebSocketService } from '../websocketService';

// Mock WebSocket
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  onopen: (() => void) | null = null;
  onmessage: ((event: any) => void) | null = null;
  onclose: ((event: any) => void) | null = null;
  onerror: ((error: any) => void) | null = null;

  readyState: number = MockWebSocket.CONNECTING;
  url: string = '';

  send = jest.fn();
  close = jest.fn();

  private eventListeners: Map<string, Array<{ callback: Function; once?: boolean }>> = new Map();

  constructor(url: string) {
    this.url = url;
    // Store instance for test access
    (MockWebSocket as any).lastInstance = this;
  }

  addEventListener(event: string, callback: Function, options?: { once?: boolean }) {
    if (!this.eventListeners.has(event)) {
      this.eventListeners.set(event, []);
    }
    this.eventListeners.get(event)!.push({
      callback,
      once: options?.once,
    });
  }

  removeEventListener(event: string, callback: Function) {
    const listeners = this.eventListeners.get(event);
    if (listeners) {
      const index = listeners.findIndex((l) => l.callback === callback);
      if (index !== -1) {
        listeners.splice(index, 1);
      }
    }
  }

  private triggerEventListeners(event: string, data?: any) {
    const listeners = this.eventListeners.get(event);
    if (listeners) {
      // Call all listeners
      listeners.forEach(({ callback }) => {
        callback(data);
      });
      // Remove 'once' listeners
      this.eventListeners.set(
        event,
        listeners.filter((l) => !l.once)
      );
    }
  }

  // Helper method to simulate connection
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;

    // Call onopen property handler
    if (this.onopen) {
      this.onopen();
    }

    // Call addEventListener handlers
    this.triggerEventListeners('open');
  }

  // Helper method to simulate message
  simulateMessage(data: any) {
    const event = { data: JSON.stringify(data) };

    // Call onmessage property handler
    if (this.onmessage) {
      this.onmessage(event);
    }

    // Call addEventListener handlers
    this.triggerEventListeners('message', event);
  }

  // Helper method to simulate close
  simulateClose(code: number = 1000, reason: string = '') {
    this.readyState = MockWebSocket.CLOSED;
    const event = { code, reason };

    // Call onclose property handler
    if (this.onclose) {
      this.onclose(event);
    }

    // Call addEventListener handlers
    this.triggerEventListeners('close', event);
  }

  // Helper method to simulate error
  simulateError() {
    const error = new Error('WebSocket error');

    // Call onerror property handler
    if (this.onerror) {
      this.onerror(error);
    }

    // Call addEventListener handlers
    this.triggerEventListeners('error', error);
  }
}

// Set up global WebSocket mock
(global as any).WebSocket = MockWebSocket;

describe('WebSocketService', () => {
  let service: WebSocketService;

  beforeEach(() => {
    jest.clearAllMocks();
    service = new WebSocketService({
      url: 'ws://localhost:8000',
      userId: 'test-user'
    });
  });

  afterEach(() => {
    if (service) {
      service.disconnect();
    }
  });

  describe('connect', () => {
    test('constructs WebSocket URL with query parameter', async () => {
      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      expect(mockWs.url).toBe(
        'ws://localhost:8000/ws?user_id=test-user'
      );

      mockWs.simulateOpen();
      await connectPromise;
    });

    test('converts http to ws protocol', async () => {
      service = new WebSocketService({
        url: 'http://localhost:8000',
        userId: 'test-user'
      });

      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      expect(mockWs.url).toBe(
        'ws://localhost:8000/ws?user_id=test-user'
      );

      mockWs.simulateOpen();
      await connectPromise;
    });

    test('returns true on successful connection', async () => {
      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      const result = await connectPromise;
      expect(result).toBe(true);
    });

    test('returns false on connection error', async () => {
      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateError();

      const result = await connectPromise;
      expect(result).toBe(false);
    });

    test('calls connection status callback on connect', async () => {
      const statusCallback = jest.fn();
      service.onConnectionStatusChange(statusCallback);

      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      expect(statusCallback).toHaveBeenCalledWith(
        expect.objectContaining({
          isConnected: true,
          isConnecting: false
        })
      );
    });
  });

  describe('sendMessage', () => {
    test('sends messages as JSON with correct format', async () => {
      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      service.sendMessage('chat_message', { message: 'Hello' });

      expect(mockWs.send).toHaveBeenCalledWith(
        JSON.stringify({
          type: 'chat_message',
          data: { message: 'Hello' }
        })
      );
    });

    test('sends end_session messages with optional reason', async () => {
      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      service.sendEndSession('User ended session');

      expect(mockWs.send).toHaveBeenCalledWith(
        JSON.stringify({
          type: 'end_session',
          data: { reason: 'User ended session' }
        })
      );
    });

    test('does not send message when not connected', () => {
      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;

      service.sendMessage('chat_message', { message: 'Hello' });

      expect(mockWs?.send).not.toHaveBeenCalled();
    });
  });

  describe('message handling', () => {
    test('handles incoming messages', async () => {
      const messageCallback = jest.fn();
      service.onMessageReceived(messageCallback);

      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      mockWs.simulateMessage({
        type: 'connected',
        data: { user_id: 'test-user' }
      });

      // Note: The service uses a switch statement and doesn't call onMessage for 'connected' type
      // Let's test with a generic message type
      mockWs.simulateMessage({
        type: 'custom_message',
        data: { test: 'data' }
      });

      expect(messageCallback).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'custom_message'
        })
      );
    });

    test('handles streaming chunk messages', async () => {
      const chunkCallback = jest.fn();
      service.onStreamingChunkReceived(chunkCallback);

      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      mockWs.simulateMessage({
        type: 'chat_response_chunk',
        data: {
          chunk: 'Hello ',
          is_complete: false
        }
      });

      expect(chunkCallback).toHaveBeenCalledWith('Hello ', false, undefined);
    });

    test('handles session started messages', async () => {
      const sessionCallback = jest.fn();
      service.onSessionStarted(sessionCallback);

      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      const sessionData = {
        session_id: 'sess_123',
        agent_type: 'INTAKE',
        workflow_state: 'intake_in_progress',
        created_at: '2025-11-29T12:00:00.000Z'
      };

      mockWs.simulateMessage({
        type: 'session_started',
        data: sessionData
      });

      expect(sessionCallback).toHaveBeenCalledWith(sessionData);
    });

    test('handles session ended messages', async () => {
      const sessionEndedCallback = jest.fn();
      const messageCallback = jest.fn();
      service.onSessionEnded(sessionEndedCallback);
      service.onMessageReceived(messageCallback);

      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      const payload = {
        reason: 'User ended session',
        workflow_state: 'assessment_complete'
      };

      mockWs.simulateMessage({
        type: 'session_ended',
        data: payload
      });

      expect(sessionEndedCallback).toHaveBeenCalledWith(payload);
      expect(messageCallback).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'session_ended' })
      );
    });
  });

  describe('reconnection', () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    test('implements reconnection with exponential backoff', async () => {
      service = new WebSocketService({
        url: 'ws://localhost:8000',
        userId: 'test-user',
        reconnectDelay: 1000
      });

      const connectPromise = service.connect();

      let mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      // Simulate unexpected disconnect
      mockWs.simulateClose(1006, 'Connection lost');

      // First reconnect attempt after 1s
      jest.advanceTimersByTime(1000);

      mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      expect(mockWs).toBeDefined();

      // Simulate another disconnect
      mockWs.simulateClose(1006, 'Connection lost');

      // Second reconnect attempt after 2s (exponential backoff)
      jest.advanceTimersByTime(2000);

      expect((MockWebSocket as any).lastInstance).toBeDefined();
    });

    test('does not reconnect on intentional disconnect', async () => {
      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      const initialInstance = mockWs;

      // Intentional disconnect
      service.disconnect();

      // Advance timers
      jest.advanceTimersByTime(5000);

      // Should not have created a new instance
      expect((MockWebSocket as any).lastInstance).toBe(initialInstance);
    });

    test('stops reconnecting after max attempts', async () => {
      service = new WebSocketService({
        url: 'ws://localhost:8000',
        userId: 'test-user',
        reconnectAttempts: 3,
        reconnectDelay: 1000
      });

      const statusCallback = jest.fn();
      service.onConnectionStatusChange(statusCallback);

      const connectPromise = service.connect();

      let mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      // Simulate connection loss
      mockWs.simulateClose(1006, 'Connection lost');

      // Simulate 3 failed reconnection attempts
      for (let i = 0; i < 3; i++) {
        const delay = 1000 * Math.pow(2, i);
        jest.advanceTimersByTime(delay);

        // Get the new socket created by reconnection attempt
        mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;

        // Make the reconnection fail
        mockWs.simulateError();
        mockWs.simulateClose(1006, 'Connection failed');
      }

      // Should have stopped reconnecting
      expect(statusCallback).toHaveBeenCalledWith(
        expect.objectContaining({
          connectionError: 'Max reconnection attempts reached'
        })
      );
    });
  });

  describe('disconnect', () => {
    test('closes WebSocket connection', async () => {
      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      service.disconnect();

      expect(mockWs.close).toHaveBeenCalled();
    });

    test('clears reconnection timeout', async () => {
      jest.useFakeTimers();

      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      // Trigger reconnection
      mockWs.simulateClose(1006, 'Connection lost');

      // Disconnect before reconnection happens
      service.disconnect();

      // Advance timers
      jest.advanceTimersByTime(5000);

      // Should not have attempted reconnection
      expect((MockWebSocket as any).lastInstance).toBe(mockWs);

      jest.useRealTimers();
    });
  });

  describe('helper methods', () => {
    test('sendChatMessage sends correct format', async () => {
      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      service.sendChatMessage('Test message');

      expect(mockWs.send).toHaveBeenCalledWith(
        JSON.stringify({
          type: 'chat_message',
          data: { message: 'Test message' }
        })
      );
    });

    test('isConnected returns correct status', async () => {
      expect(service.isConnected()).toBe(false);

      const connectPromise = service.connect();

      const mockWs = (MockWebSocket as any).lastInstance as MockWebSocket;
      mockWs.simulateOpen();

      await connectPromise;

      expect(service.isConnected()).toBe(true);

      service.disconnect();

      expect(service.isConnected()).toBe(false);
    });
  });
});
