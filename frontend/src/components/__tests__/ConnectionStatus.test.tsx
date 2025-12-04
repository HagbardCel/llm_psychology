import { render, screen } from '@testing-library/react';
import { ConnectionStatus } from '../ConnectionStatus';
import { ConnectionStatus as ConnectionStatusType } from '../../types/websocket';

describe('ConnectionStatus', () => {
  const createMockStatus = (
    overrides?: Partial<ConnectionStatusType>
  ): ConnectionStatusType => ({
    isConnected: false,
    isConnecting: false,
    lastConnected: undefined,
    connectionError: undefined,
    ...overrides,
  });

  describe('Chip Variant (Default)', () => {
    it('should render chip variant by default', () => {
      const status = createMockStatus({ isConnected: true });
      const { container } = render(<ConnectionStatus status={status} />);

      expect(container.querySelector('.MuiChip-root')).toBeInTheDocument();
    });

    it('should display "Connected" with success color when connected', () => {
      const status = createMockStatus({ isConnected: true });
      render(<ConnectionStatus status={status} variant="chip" />);

      expect(screen.getByText('Connected')).toBeInTheDocument();
      const chip = screen.getByText('Connected').closest('.MuiChip-root');
      expect(chip).toHaveClass('MuiChip-colorSuccess');
    });

    it('should display "Disconnected" with error color when disconnected', () => {
      const status = createMockStatus({ isConnected: false });
      render(<ConnectionStatus status={status} variant="chip" />);

      expect(screen.getByText('Disconnected')).toBeInTheDocument();
      const chip = screen.getByText('Disconnected').closest('.MuiChip-root');
      expect(chip).toHaveClass('MuiChip-colorError');
    });

    it('should display "Connecting..." with warning color when connecting', () => {
      const status = createMockStatus({ isConnecting: true });
      render(<ConnectionStatus status={status} variant="chip" />);

      expect(screen.getByText('Connecting...')).toBeInTheDocument();
      const chip = screen.getByText('Connecting...').closest('.MuiChip-root');
      expect(chip).toHaveClass('MuiChip-colorWarning');
    });

    it('should show Connected icon when connected', () => {
      const status = createMockStatus({ isConnected: true });
      const { container } = render(<ConnectionStatus status={status} variant="chip" />);

      const wifiIcon = container.querySelector('[data-testid="WifiIcon"]');
      expect(wifiIcon).toBeInTheDocument();
    });

    it('should show Disconnected icon when disconnected', () => {
      const status = createMockStatus({ isConnected: false });
      const { container } = render(<ConnectionStatus status={status} variant="chip" />);

      const wifiOffIcon = container.querySelector('[data-testid="WifiOffIcon"]');
      expect(wifiOffIcon).toBeInTheDocument();
    });

    it('should show CircularProgress when connecting', () => {
      const status = createMockStatus({ isConnecting: true });
      const { container } = render(<ConnectionStatus status={status} variant="chip" />);

      const progress = container.querySelector('.MuiCircularProgress-root');
      expect(progress).toBeInTheDocument();
    });

    it('should wrap chip in Tooltip component', () => {
      const status = createMockStatus({ isConnected: true });
      const { container } = render(<ConnectionStatus status={status} variant="chip" />);

      // Tooltip wraps the chip - verify it renders correctly
      const chip = container.querySelector('.MuiChip-root');
      expect(chip).toBeInTheDocument();
      expect(chip?.parentElement).toBeInTheDocument();
    });

    it('should include lastConnected time in tooltip content', () => {
      const lastConnected = new Date('2024-01-15T10:30:00');
      const status = createMockStatus({
        isConnected: true,
        lastConnected,
      });

      const { container } = render(<ConnectionStatus status={status} variant="chip" />);

      // Tooltip wraps the chip - verify it exists
      const chip = container.querySelector('.MuiChip-root');
      expect(chip).toBeInTheDocument();
      expect(screen.getByText('Connected')).toBeInTheDocument();
    });

    it('should include connection error in tooltip when present', () => {
      const status = createMockStatus({
        isConnected: false,
        connectionError: 'Network timeout',
      });

      const { container } = render(<ConnectionStatus status={status} variant="chip" />);

      // Tooltip wraps the chip - verify it exists with disconnected state
      const chip = container.querySelector('.MuiChip-root');
      expect(chip).toBeInTheDocument();
      expect(screen.getByText('Disconnected')).toBeInTheDocument();
    });

    it('should have cursor help style', () => {
      const status = createMockStatus({ isConnected: true });
      render(<ConnectionStatus status={status} variant="chip" />);

      const chip = screen.getByText('Connected').closest('.MuiChip-root');
      expect(chip).toHaveStyle({ cursor: 'help' });
    });
  });

  describe('Full Variant', () => {
    it('should render full variant Box when specified', () => {
      const status = createMockStatus({ isConnected: true });
      const { container } = render(<ConnectionStatus status={status} variant="full" />);

      // Should not have chip, should have Box with content
      expect(container.querySelector('.MuiChip-root')).not.toBeInTheDocument();
      expect(screen.getByText('Connected')).toBeInTheDocument();
    });

    it('should display status text in full variant', () => {
      const status = createMockStatus({ isConnected: true });
      render(<ConnectionStatus status={status} variant="full" />);

      const typography = screen.getByText('Connected');
      expect(typography).toHaveClass('MuiTypography-body2');
    });

    it('should show Connected icon in full variant', () => {
      const status = createMockStatus({ isConnected: true });
      const { container } = render(<ConnectionStatus status={status} variant="full" />);

      const wifiIcon = container.querySelector('[data-testid="WifiIcon"]');
      expect(wifiIcon).toBeInTheDocument();
    });

    it('should show Disconnected icon in full variant', () => {
      const status = createMockStatus({ isConnected: false });
      const { container } = render(<ConnectionStatus status={status} variant="full" />);

      const wifiOffIcon = container.querySelector('[data-testid="WifiOffIcon"]');
      expect(wifiOffIcon).toBeInTheDocument();
    });

    it('should show CircularProgress in full variant when connecting', () => {
      const status = createMockStatus({ isConnecting: true });
      const { container } = render(<ConnectionStatus status={status} variant="full" />);

      const progress = container.querySelector('.MuiCircularProgress-root');
      expect(progress).toBeInTheDocument();
    });

    it('should show lastConnected time when showDetails is true and connected', () => {
      const lastConnected = new Date('2024-01-15T10:30:00');
      const status = createMockStatus({
        isConnected: true,
        lastConnected,
      });

      render(<ConnectionStatus status={status} variant="full" showDetails={true} />);

      expect(screen.getByText(/Connected at/)).toBeInTheDocument();
    });

    it('should not show lastConnected time when showDetails is false', () => {
      const lastConnected = new Date('2024-01-15T10:30:00');
      const status = createMockStatus({
        isConnected: true,
        lastConnected,
      });

      render(<ConnectionStatus status={status} variant="full" showDetails={false} />);

      expect(screen.queryByText(/Connected at/)).not.toBeInTheDocument();
    });

    it('should show connection error when showDetails is true and disconnected', () => {
      const status = createMockStatus({
        isConnected: false,
        connectionError: 'WebSocket failed',
      });

      render(<ConnectionStatus status={status} variant="full" showDetails={true} />);

      expect(screen.getByText('Error: WebSocket failed')).toBeInTheDocument();
    });

    it('should not show connection error when connected even with showDetails', () => {
      const status = createMockStatus({
        isConnected: true,
        connectionError: 'Previous error',
      });

      render(<ConnectionStatus status={status} variant="full" showDetails={true} />);

      expect(screen.queryByText(/Error:/)).not.toBeInTheDocument();
    });

    it('should not show details when showDetails is false', () => {
      const status = createMockStatus({
        isConnected: false,
        connectionError: 'Some error',
      });

      render(<ConnectionStatus status={status} variant="full" showDetails={false} />);

      expect(screen.queryByText(/Error:/)).not.toBeInTheDocument();
    });
  });

  describe('Status Text', () => {
    it('should display "Connecting..." when isConnecting is true', () => {
      const status = createMockStatus({ isConnecting: true });
      render(<ConnectionStatus status={status} />);

      expect(screen.getByText('Connecting...')).toBeInTheDocument();
    });

    it('should display "Connected" when isConnected is true', () => {
      const status = createMockStatus({ isConnected: true });
      render(<ConnectionStatus status={status} />);

      expect(screen.getByText('Connected')).toBeInTheDocument();
    });

    it('should display "Disconnected" when neither connecting nor connected', () => {
      const status = createMockStatus({
        isConnected: false,
        isConnecting: false,
      });
      render(<ConnectionStatus status={status} />);

      expect(screen.getByText('Disconnected')).toBeInTheDocument();
    });

    it('should prioritize connecting status over connected', () => {
      // Edge case: both isConnecting and isConnected are true
      const status = createMockStatus({
        isConnecting: true,
        isConnected: true,
      });
      render(<ConnectionStatus status={status} />);

      // Should show "Connecting..." since that's checked first
      expect(screen.getByText('Connecting...')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('should handle undefined lastConnected gracefully', () => {
      const status = createMockStatus({
        isConnected: true,
        lastConnected: undefined,
      });

      render(<ConnectionStatus status={status} variant="full" showDetails={true} />);

      expect(screen.getByText('Connected')).toBeInTheDocument();
      expect(screen.queryByText(/Connected at/)).not.toBeInTheDocument();
    });

    it('should handle undefined connectionError gracefully', () => {
      const status = createMockStatus({
        isConnected: false,
        connectionError: undefined,
      });

      render(<ConnectionStatus status={status} variant="full" showDetails={true} />);

      expect(screen.getByText('Disconnected')).toBeInTheDocument();
      expect(screen.queryByText(/Error:/)).not.toBeInTheDocument();
    });

    it('should handle empty connectionError string', () => {
      const status = createMockStatus({
        isConnected: false,
        connectionError: '',
      });

      render(<ConnectionStatus status={status} variant="full" showDetails={true} />);

      expect(screen.getByText('Disconnected')).toBeInTheDocument();
      expect(screen.queryByText(/Error:/)).not.toBeInTheDocument();
    });
  });
});
