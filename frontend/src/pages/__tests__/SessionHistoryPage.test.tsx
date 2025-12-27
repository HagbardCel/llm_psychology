import { render, screen, fireEvent } from '@testing-library/react';
import { SessionHistoryPage } from '../SessionHistoryPage';

const mockNavigate = jest.fn();

jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
}));

jest.mock('../../contexts/AppContext', () => ({
  useCurrentUserId: () => 'test-user-id',
}));

const mockUseSessionHistory = jest.fn();
jest.mock('../../hooks/useSessionHistory', () => ({
  useSessionHistory: (...args: any[]) => mockUseSessionHistory(...args),
}));

describe('SessionHistoryPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state', () => {
    mockUseSessionHistory.mockReturnValue({ data: null, isLoading: true, error: null });

    render(<SessionHistoryPage />);

    expect(screen.getByText('Session History')).toBeInTheDocument();
  });

  it('shows empty state when there are no sessions', () => {
    mockUseSessionHistory.mockReturnValue({ data: [], isLoading: false, error: null });

    render(<SessionHistoryPage />);

    expect(
      screen.getByText('No sessions found. Start a new session to begin your journey.')
    ).toBeInTheDocument();
  });

  it('shows error banner when query errors', () => {
    mockUseSessionHistory.mockReturnValue({
      data: [],
      isLoading: false,
      error: new Error('failed'),
    });

    render(<SessionHistoryPage />);

    expect(
      screen.getByText('Failed to load sessions. Please try refreshing the page.')
    ).toBeInTheDocument();
  });

  it('navigates to session route when clicking a session', () => {
    mockUseSessionHistory.mockReturnValue({
      data: [
        {
          session_id: 'session-1',
          user_id: 'test-user-id',
          timestamp: '2024-01-01T00:00:00Z',
          transcript: [{ role: 'user', content: 'Hi', timestamp: '2024-01-01T00:00:00Z' }],
          topics: [],
          psychological_summary: null,
          dominant_affects: [],
          key_themes: [],
          notable_interactions: null,
          interpretations: null,
          patient_reactions: null,
          enriched: false,
        },
      ],
      isLoading: false,
      error: null,
    });

    render(<SessionHistoryPage />);

    fireEvent.click(screen.getByText('1 messages • 0 topics'));
    expect(mockNavigate).toHaveBeenCalledWith('/session/session-1');
  });
});
