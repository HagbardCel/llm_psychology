import { render, screen, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MessageInput } from '../MessageInput';

describe('MessageInput', () => {
  const mockOnSendMessage = jest.fn();
  const mockOnTypingChange = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('Rendering', () => {
    it('should render text field with default placeholder', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      expect(
        screen.getByPlaceholderText('Type your message...')
      ).toBeInTheDocument();
    });

    it('should render text field with custom placeholder', () => {
      render(
        <MessageInput
          onSendMessage={mockOnSendMessage}
          placeholder="Custom placeholder"
        />
      );

      expect(screen.getByPlaceholderText('Custom placeholder')).toBeInTheDocument();
    });

    it('should render send button', () => {
      const { container } = render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const sendIcon = container.querySelector('[data-testid="SendIcon"]');
      expect(sendIcon).toBeInTheDocument();
    });

    it('should render attachment button', () => {
      const { container } = render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const attachIcon = container.querySelector('[data-testid="AttachFileIcon"]');
      expect(attachIcon).toBeInTheDocument();
    });

    it('should render microphone button', () => {
      const { container } = render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const micIcon = container.querySelector('[data-testid="MicIcon"]');
      expect(micIcon).toBeInTheDocument();
    });
  });

  describe('Message Input', () => {
    it('should update message value when typing', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      await act(async () => {
        await user.type(input, 'Hello world');
      });

      expect(input).toHaveValue('Hello world');
    });

    it('should call onTypingChange when typing', async () => {
      const user = userEvent.setup();
      render(
        <MessageInput
          onSendMessage={mockOnSendMessage}
          onTypingChange={mockOnTypingChange}
        />
      );

      const input = screen.getByPlaceholderText('Type your message...');
      await act(async () => {
        await user.type(input, 'Hello');
      });

      expect(mockOnTypingChange).toHaveBeenCalled();
      expect(mockOnTypingChange).toHaveBeenLastCalledWith('Hello');
    });

    it('should not call onTypingChange when callback is not provided', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      await act(async () => {
        await user.type(input, 'Hello');
      });

      expect(input).toHaveValue('Hello');
      // No error should occur
    });
  });

  describe('Sending Messages', () => {
    it('should call onSendMessage when send button clicked with non-empty message', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1]; // Last button is send

      await act(async () => {
        await user.type(input, 'Hello');
        await user.click(sendButton);
      });

      expect(mockOnSendMessage).toHaveBeenCalledWith('Hello');
    });

    it('should trim whitespace before sending', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1];

      await act(async () => {
        await user.type(input, '  Hello world  ');
        await user.click(sendButton);
      });

      expect(mockOnSendMessage).toHaveBeenCalledWith('Hello world');
    });

    it('should clear input after sending message', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1];

      await act(async () => {
        await user.type(input, 'Hello');
        await user.click(sendButton);
      });

      expect(input).toHaveValue('');
    });

    it('should not send empty message', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1];

      // Button should be disabled when input is empty
      expect(sendButton).toBeDisabled();
      expect(mockOnSendMessage).not.toHaveBeenCalled();
    });

    it('should not send whitespace-only message', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1];

      await act(async () => {
        await user.type(input, '   ');
      });

      // Button should remain disabled for whitespace-only input
      expect(sendButton).toBeDisabled();
      expect(mockOnSendMessage).not.toHaveBeenCalled();
    });

    it('should send message on Enter key press', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      await act(async () => {
        await user.type(input, 'Hello{Enter}');
      });

      expect(mockOnSendMessage).toHaveBeenCalledWith('Hello');
    });

    it('should not send message on Shift+Enter key press', async () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');

      fireEvent.change(input, { target: { value: 'Hello' } });
      fireEvent.keyPress(input, { key: 'Enter', shiftKey: true });

      expect(mockOnSendMessage).not.toHaveBeenCalled();
    });
  });

  describe('Disabled State', () => {
    it('should disable input when disabled prop is true', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} disabled={true} />);

      const input = screen.getByPlaceholderText('Type your message...');
      expect(input).toBeDisabled();
    });

    it('should disable send button when disabled prop is true', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} disabled={true} />);

      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1];

      expect(sendButton).toBeDisabled();
    });

    it('should disable attachment button when disabled prop is true', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} disabled={true} />);

      const buttons = screen.getAllByRole('button');
      const attachButton = buttons[0]; // First button is attachment

      expect(attachButton).toBeDisabled();
    });

    it('should disable microphone button when disabled prop is true', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} disabled={true} />);

      const buttons = screen.getAllByRole('button');
      const micButton = buttons[1]; // Second button is microphone

      expect(micButton).toBeDisabled();
    });

    it('should not send message when disabled', async () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} disabled={true} />);

      const input = screen.getByPlaceholderText('Type your message...');

      // Input is disabled, so typing won't work normally
      expect(input).toBeDisabled();
    });
  });

  describe('Loading State', () => {
    it('should disable input when isLoading is true', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} isLoading={true} />);

      const input = screen.getByPlaceholderText('Type your message...');
      expect(input).toBeDisabled();
    });

    it('should show loading spinner instead of send icon when loading', () => {
      const { container } = render(
        <MessageInput onSendMessage={mockOnSendMessage} isLoading={true} />
      );

      const spinner = container.querySelector('.MuiCircularProgress-root');
      expect(spinner).toBeInTheDocument();

      const sendIcon = container.querySelector('[data-testid="SendIcon"]');
      expect(sendIcon).not.toBeInTheDocument();
    });

    it('should disable send button when loading', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} isLoading={true} />);

      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1];

      expect(sendButton).toBeDisabled();
    });
  });

  describe('Button Interactions', () => {
    it('should disable send button when input is empty', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1];

      expect(sendButton).toBeDisabled();
    });

    it('should enable send button when input has text', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      const sendButtons = screen.getAllByRole('button');
      const sendButton = sendButtons[sendButtons.length - 1];

      await act(async () => {
        await user.type(input, 'Hello');
      });

      expect(sendButton).not.toBeDisabled();
    });

    it('should show notice when voice button clicked', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const buttons = screen.getAllByRole('button');
      const voiceButton = buttons[1]; // Second button is voice

      await act(async () => {
        await user.click(voiceButton);
      });

      expect(
        await screen.findByText('Voice input is not supported in this build.')
      ).toBeInTheDocument();
    });

    it('should show notice when attachment button clicked', async () => {
      const user = userEvent.setup();
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const buttons = screen.getAllByRole('button');
      const attachButton = buttons[0]; // First button is attachment

      await act(async () => {
        await user.click(attachButton);
      });

      expect(
        await screen.findByText('File attachments are not supported in this build.')
      ).toBeInTheDocument();
    });
  });

  describe('Character Count Warning', () => {
    it('should not show character count for messages under 500 characters', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      fireEvent.change(input, { target: { value: 'A'.repeat(499) } });

      expect(screen.queryByText(/\/1000/)).not.toBeInTheDocument();
    });

    it('should show character count at exactly 501 characters', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      fireEvent.change(input, { target: { value: 'A'.repeat(501) } });

      const charCount = screen.getByText('501/1000');
      expect(charCount).toBeInTheDocument();
    });

    it('should show orange character count for messages 501-1000 characters', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      fireEvent.change(input, { target: { value: 'A'.repeat(750) } });

      const charCount = screen.getByText('750/1000');
      expect(charCount).toBeInTheDocument();
      expect(charCount).toHaveStyle({ color: 'orange' });
    });

    it('should show red character count for messages over 1000 characters', () => {
      render(<MessageInput onSendMessage={mockOnSendMessage} />);

      const input = screen.getByPlaceholderText('Type your message...');
      fireEvent.change(input, { target: { value: 'A'.repeat(1001) } });

      const charCount = screen.getByText('1001/1000');
      expect(charCount).toBeInTheDocument();
      expect(charCount).toHaveStyle({ color: 'red' });
    });
  });
});
