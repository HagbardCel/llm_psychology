import { render, screen } from '@testing-library/react';
import { SessionPage } from '../SessionPage';

// Mock react-router
const mockUseParams = vi.fn();
vi.mock('react-router', () => ({
  useParams: () => mockUseParams(),
}));

// Mock TherapySession component
vi.mock('../../components/TherapySession', () => ({
  TherapySession: ({ sessionId }: { sessionId?: string }) => (
    <div data-testid="therapy-session-mock">
      TherapySession {sessionId ? `(${sessionId})` : '(no session)'}
    </div>
  ),
}));

describe('SessionPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should render TherapySession component', () => {
    mockUseParams.mockReturnValue({ sessionId: undefined });
    render(<SessionPage />);

    expect(screen.getByTestId('therapy-session-mock')).toBeInTheDocument();
  });

  it('should pass sessionId to TherapySession when present in URL params', () => {
    const testSessionId = 'test-session-123';
    mockUseParams.mockReturnValue({ sessionId: testSessionId });

    render(<SessionPage />);

    expect(screen.getByText(`TherapySession (${testSessionId})`)).toBeInTheDocument();
  });

  it('should pass undefined sessionId when not in URL params', () => {
    mockUseParams.mockReturnValue({ sessionId: undefined });

    render(<SessionPage />);

    expect(screen.getByText('TherapySession (no session)')).toBeInTheDocument();
  });

  it('should render without crashing', () => {
    mockUseParams.mockReturnValue({});
    const { container } = render(<SessionPage />);

    expect(container).toBeInTheDocument();
  });

  it('should handle empty string sessionId', () => {
    mockUseParams.mockReturnValue({ sessionId: '' });

    render(<SessionPage />);

    expect(screen.getByTestId('therapy-session-mock')).toBeInTheDocument();
  });
});
