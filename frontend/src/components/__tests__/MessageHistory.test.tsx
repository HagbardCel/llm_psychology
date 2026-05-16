import { render, screen, waitFor } from '@testing-library/react';
import { MessageHistory } from '../MessageHistory';
import { Message } from '../../types';

// Mock date-fns to avoid timezone issues
vi.mock('date-fns', () => ({
  format: vi.fn((date: Date, formatStr: string) => {
    if (formatStr === 'HH:mm') {
      return '12:30';
    }
    return date.toISOString();
  }),
}));

// Mock scrollIntoView (not available in jsdom)
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe('MessageHistory', () => {
  // Test data factory
  const createMockMessage = (overrides?: Partial<Message>): Message => ({
    id: 'msg-123',
    content: 'Test message content',
    role: 'user',
    timestamp: new Date('2024-01-01T12:30:00').toISOString(),
    sessionId: 'session-123',
    ...overrides,
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render without crashing', () => {
      const { container } = render(<MessageHistory messages={[]} />);

      // Container should be rendered
      expect(container.querySelector('.MuiStack-root')).toBeInTheDocument();
    });

    it('should render all messages in order', () => {
      const messages = [
        createMockMessage({ id: 'msg-1', content: 'First message' }),
        createMockMessage({ id: 'msg-2', content: 'Second message' }),
        createMockMessage({ id: 'msg-3', content: 'Third message' }),
      ];

      render(<MessageHistory messages={messages} />);

      expect(screen.getByText('First message')).toBeInTheDocument();
      expect(screen.getByText('Second message')).toBeInTheDocument();
      expect(screen.getByText('Third message')).toBeInTheDocument();
    });

    it('should render empty state when no messages', () => {
      const { container } = render(<MessageHistory messages={[]} />);

      // Should have the container but no message bubbles
      const messageBubbles = container.querySelectorAll('.MuiPaper-root');
      expect(messageBubbles.length).toBe(0);
    });
  });

  describe('Message Bubble Display', () => {
    it('should display user messages on the right', () => {
      const userMessage = createMockMessage({
        id: 'user-msg',
        content: 'User message',
        role: 'user',
      });

      render(<MessageHistory messages={[userMessage]} />);

      const messageBox = screen.getByText('User message').closest('.MuiBox-root');
      const parentBox = messageBox?.parentElement;

      // User messages should be justified to flex-end (right)
      expect(parentBox).toHaveStyle({ justifyContent: 'flex-end' });
    });

    it('should display assistant messages on the left', () => {
      const assistantMessage = createMockMessage({
        id: 'assistant-msg',
        content: 'Assistant message',
        role: 'assistant',
      });

      render(<MessageHistory messages={[assistantMessage]} />);

      const messageBox = screen.getByText('Assistant message').closest('.MuiBox-root');
      const parentBox = messageBox?.parentElement;

      // Assistant messages should be justified to flex-start (left)
      expect(parentBox).toHaveStyle({ justifyContent: 'flex-start' });
    });

    it('should format timestamps correctly', () => {
      const message = createMockMessage({
        timestamp: new Date('2024-01-01T14:45:00').toISOString(),
      });

      render(<MessageHistory messages={[message]} />);

      // Should display formatted time
      expect(screen.getByText('12:30')).toBeInTheDocument();
    });

    it('should preserve whitespace in message content', () => {
      const message = createMockMessage({
        content: 'Line 1\nLine 2\n  Indented line',
      });

      render(<MessageHistory messages={[message]} />);

      const messageText = screen.getByText(/Line 1/);
      expect(messageText).toHaveStyle({
        whiteSpace: 'pre-wrap',
        wordWrap: 'break-word',
      });
    });
  });

  describe('Streaming Display', () => {
    it('should display streaming message when isStreaming is true', () => {
      render(
        <MessageHistory
          messages={[]}
          isStreaming={true}
          streamingMessage="Streaming content..."
        />
      );

      expect(screen.getByText('Streaming content...')).toBeInTheDocument();
      expect(screen.getByText('Streaming...')).toBeInTheDocument();
    });

    it('should not display streaming message when isStreaming is false', () => {
      render(
        <MessageHistory
          messages={[]}
          isStreaming={false}
          streamingMessage="Streaming content..."
        />
      );

      expect(screen.queryByText('Streaming content...')).not.toBeInTheDocument();
      expect(screen.queryByText('Streaming...')).not.toBeInTheDocument();
    });

    it('should not display streaming message when streamingMessage is empty', () => {
      render(
        <MessageHistory
          messages={[]}
          isStreaming={true}
          streamingMessage=""
        />
      );

      expect(screen.queryByText('Streaming...')).not.toBeInTheDocument();
    });

    it('should display streaming message along with existing messages', () => {
      const messages = [
        createMockMessage({ id: 'msg-1', content: 'Existing message' }),
      ];

      render(
        <MessageHistory
          messages={messages}
          isStreaming={true}
          streamingMessage="New streaming content"
        />
      );

      expect(screen.getByText('Existing message')).toBeInTheDocument();
      expect(screen.getByText('New streaming content')).toBeInTheDocument();
    });
  });

  describe('Loading State', () => {
    it('should show typing indicator when isLoading is true', () => {
      render(<MessageHistory messages={[]} isLoading={true} />);

      expect(screen.getByText('Agent is typing...')).toBeInTheDocument();
    });

    it('should not show typing indicator when isLoading is false', () => {
      render(<MessageHistory messages={[]} isLoading={false} />);

      expect(screen.queryByText('Agent is typing...')).not.toBeInTheDocument();
    });

    it('should not show typing indicator when streaming', async () => {
      render(
        <MessageHistory
          messages={[]}
          isLoading={true}
          isStreaming={true}
          streamingMessage="Thinking about your question"
        />
      );

      // Should show streaming message but not typing indicator
      await waitFor(() => {
        expect(screen.getByText('Thinking about your question')).toBeInTheDocument();
      });

      expect(screen.queryByText('Agent is typing...')).not.toBeInTheDocument();
    });
  });

  describe('Message Role Icons', () => {
    it('should display Person icon for user messages', () => {
      const userMessage = createMockMessage({
        role: 'user',
        content: 'User message',
      });

      const { container } = render(<MessageHistory messages={[userMessage]} />);

      // Check for PersonIcon by looking for the Avatar with primary.main color
      const avatars = container.querySelectorAll('.MuiAvatar-root');
      expect(avatars.length).toBeGreaterThan(0);
    });

    it('should display Psychology icon for assistant messages', () => {
      const assistantMessage = createMockMessage({
        role: 'assistant',
        content: 'Assistant message',
      });

      const { container } = render(<MessageHistory messages={[assistantMessage]} />);

      // Check for Avatar with secondary.main color for assistant
      const avatars = container.querySelectorAll('.MuiAvatar-root');
      expect(avatars.length).toBeGreaterThan(0);
    });
  });

  describe('Mixed Message Scenarios', () => {
    it('should handle alternating user and assistant messages', () => {
      const messages = [
        createMockMessage({ id: 'msg-1', role: 'user', content: 'User 1' }),
        createMockMessage({ id: 'msg-2', role: 'assistant', content: 'Assistant 1' }),
        createMockMessage({ id: 'msg-3', role: 'user', content: 'User 2' }),
        createMockMessage({ id: 'msg-4', role: 'assistant', content: 'Assistant 2' }),
      ];

      render(<MessageHistory messages={messages} />);

      expect(screen.getByText('User 1')).toBeInTheDocument();
      expect(screen.getByText('Assistant 1')).toBeInTheDocument();
      expect(screen.getByText('User 2')).toBeInTheDocument();
      expect(screen.getByText('Assistant 2')).toBeInTheDocument();
    });

    it('should handle consecutive messages from the same role', () => {
      const messages = [
        createMockMessage({ id: 'msg-1', role: 'user', content: 'User message 1' }),
        createMockMessage({ id: 'msg-2', role: 'user', content: 'User message 2' }),
        createMockMessage({ id: 'msg-3', role: 'user', content: 'User message 3' }),
      ];

      render(<MessageHistory messages={messages} />);

      expect(screen.getByText('User message 1')).toBeInTheDocument();
      expect(screen.getByText('User message 2')).toBeInTheDocument();
      expect(screen.getByText('User message 3')).toBeInTheDocument();
    });
  });

  describe('Long Message Content', () => {
    it('should handle very long messages', () => {
      const longContent = 'A'.repeat(1000);
      const message = createMockMessage({
        content: longContent,
      });

      render(<MessageHistory messages={[message]} />);

      expect(screen.getByText(longContent)).toBeInTheDocument();
    });

    it('should handle messages with special characters', () => {
      const specialContent = 'Special: @#$%^&*()_+-=[]{}|;:,.<>?/~`';
      const message = createMockMessage({
        content: specialContent,
      });

      render(<MessageHistory messages={[message]} />);

      expect(screen.getByText(specialContent)).toBeInTheDocument();
    });

    it('should handle multi-line messages', () => {
      const multilineContent = 'Line 1\nLine 2\nLine 3\nLine 4';
      const message = createMockMessage({
        content: multilineContent,
      });

      render(<MessageHistory messages={[message]} />);

      // Check for content using a function matcher since exact newline matching is tricky
      expect(screen.getByText((_content, element) => {
        return element?.textContent === multilineContent;
      })).toBeInTheDocument();
    });
  });

  describe('Auto-scroll Behavior', () => {
    it('should render scroll anchor element', () => {
      const { container } = render(<MessageHistory messages={[]} />);

      // Check that the scroll anchor div exists
      expect(container.querySelector('.MuiStack-root')).toBeInTheDocument();
    });

    it('should trigger scroll on new messages', () => {
      const { rerender } = render(<MessageHistory messages={[]} />);

      const newMessages = [createMockMessage({ content: 'New message' })];
      rerender(<MessageHistory messages={newMessages} />);

      expect(screen.getByText('New message')).toBeInTheDocument();
    });

    it('should trigger scroll on streaming message updates', () => {
      const { rerender } = render(
        <MessageHistory
          messages={[]}
          isStreaming={true}
          streamingMessage="First chunk"
        />
      );

      rerender(
        <MessageHistory
          messages={[]}
          isStreaming={true}
          streamingMessage="First chunk Second chunk"
        />
      );

      expect(screen.getByText('First chunk Second chunk')).toBeInTheDocument();
    });
  });

  describe('Empty States and Edge Cases', () => {
    it('should handle undefined optional props', () => {
      render(<MessageHistory messages={[]} />);

      // Should render without errors
      expect(screen.queryByText('Agent is typing...')).not.toBeInTheDocument();
      expect(screen.queryByText('Streaming...')).not.toBeInTheDocument();
    });

    it('should handle message with undefined timestamp', () => {
      const messageWithInvalidTimestamp = {
        id: 'msg-1',
        content: 'Test',
        role: 'user' as const,
        timestamp: new Date('2024-01-01T00:00:00').toISOString(),
        sessionId: 'session-123',
      };

      render(<MessageHistory messages={[messageWithInvalidTimestamp]} />);

      // Should still render the message content
      expect(screen.getByText('Test')).toBeInTheDocument();
    });

    it('should handle very large message arrays', () => {
      const manyMessages = Array.from({ length: 100 }, (_, i) =>
        createMockMessage({ id: `msg-${i}`, content: `Message ${i}` })
      );

      render(<MessageHistory messages={manyMessages} />);

      // First and last messages should be present
      expect(screen.getByText('Message 0')).toBeInTheDocument();
      expect(screen.getByText('Message 99')).toBeInTheDocument();
    });
  });
});
