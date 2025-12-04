import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SessionHistoryPage } from '../SessionHistoryPage';
import { User, UserStatus } from '../../types';

// Mock navigation
const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
}));

// Mock AppContext
jest.mock('../../contexts/AppContext', () => ({
  useAppContext: jest.fn(),
}));

// Mock fetch API
global.fetch = jest.fn();

// Helper to create properly structured mock fetch responses
const createMockResponse = (data: any, ok: boolean = true, status: number = 200, statusText: string = 'OK') => ({
  ok,
  status,
  statusText,
  json: async () => data,
  text: async () => JSON.stringify(data),
  headers: new Headers({ 'content-type': 'application/json' })
});

describe('SessionHistoryPage', () => {
  const createMockUser = (overrides?: Partial<User>): User => ({
    id: 'test-user-id',
    name: 'Test User',
    status: UserStatus.PLAN_COMPLETE,
    createdAt: new Date(),
    lastActiveAt: new Date(),
    ...overrides,
  });

  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockClear();
  });

  describe('Loading State', () => {
    it('should show loading skeletons while fetching sessions', () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      // Mock fetch to never resolve (simulate loading)
      (global.fetch as jest.Mock).mockImplementation(
        () => new Promise(() => {})
      );

      const { container } = render(<SessionHistoryPage />);

      expect(screen.getByText('Session History')).toBeInTheDocument();

      // Check for skeleton components
      const skeletons = container.querySelectorAll('.MuiSkeleton-root');
      expect(skeletons.length).toBeGreaterThan(0);
    });
  });

  describe('No User State', () => {
    it('should not fetch sessions when user is null', async () => {
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: null,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(global.fetch).not.toHaveBeenCalled();
      });

      expect(
        screen.getByText('No sessions found. Start a new session to begin your journey.')
      ).toBeInTheDocument();
    });
  });

  describe('Error State', () => {
    it('should display error message when fetch fails', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      (global.fetch as jest.Mock).mockRejectedValueOnce(
        new Error('Network error')
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText(/Network error: Network error/)).toBeInTheDocument();
      });

      expect(screen.getByRole('alert')).toHaveClass('MuiAlert-standardError');
    });

    it('should display error message when response is not ok', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse({ detail: 'Server error' }, false, 500, 'Internal Server Error')
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(
          screen.getByText(/Failed to fetch sessions: Internal Server Error/)
        ).toBeInTheDocument();
      });
    });

    it('should handle non-Error exceptions gracefully', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      // Reject with a non-Error value (string)
      (global.fetch as jest.Mock).mockRejectedValueOnce('String error');

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText('An unknown error occurred')).toBeInTheDocument();
      });
    });
  });

  describe('Empty State', () => {
    it('should display empty state message when no sessions exist', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse([])
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(
          screen.getByText('No sessions found. Start a new session to begin your journey.')
        ).toBeInTheDocument();
      });
    });
  });

  describe('Sessions Display', () => {
    it('should display sessions when fetch succeeds', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      const mockSessionData = [
        {
          id: 'session-1',
          userId: 'test-user-id',
          agentType: 'PSYCHOANALYST',
          status: 'ACTIVE',
          startTime: '2024-01-15T10:30:00.000Z',
          transcript: [
            {
              id: 'msg-1',
              content: 'Hello',
              role: 'user',
              timestamp: '2024-01-15T10:30:00.000Z',
              sessionId: 'session-1',
            },
          ],
          topics: ['anxiety'],
        },
      ];

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse(mockSessionData)
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText(/Session.*1\/15\/2024/)).toBeInTheDocument();
        expect(screen.getByText(/1 messages • 1 topics/)).toBeInTheDocument();
      });
    });

    it('should display multiple sessions in order', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      const mockSessionsData = [
        {
          id: 'session-1',
          userId: 'test-user-id',
          agentType: 'PSYCHOANALYST',
          status: 'ACTIVE',
          startTime: '2024-01-15T10:30:00.000Z',
          transcript: [{ id: 'msg-1', content: 'Message 1', role: 'user', timestamp: '2024-01-15T10:30:00.000Z', sessionId: 'session-1' }],
          topics: ['topic1'],
        },
        {
          id: 'session-2',
          userId: 'test-user-id',
          agentType: 'INTAKE',
          status: 'COMPLETED',
          startTime: '2024-01-16T14:00:00.000Z',
          transcript: [
            { id: 'msg-2', content: 'Message 2', role: 'user', timestamp: '2024-01-16T14:00:00.000Z', sessionId: 'session-2' },
            { id: 'msg-3', content: 'Message 3', role: 'assistant', timestamp: '2024-01-16T14:00:05.000Z', sessionId: 'session-2' },
          ],
          topics: ['topic2', 'topic3'],
        },
      ];

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse(mockSessionsData)
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText(/Session.*1\/15\/2024/)).toBeInTheDocument();
        expect(screen.getByText(/Session.*1\/16\/2024/)).toBeInTheDocument();
        expect(screen.getByText(/1 messages • 1 topics/)).toBeInTheDocument();
        expect(screen.getByText(/2 messages • 2 topics/)).toBeInTheDocument();
      });
    });

    it('should display dividers between sessions', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      const mockSessionsData = [
        {
          id: 'session-1',
          userId: 'test-user-id',
          agentType: 'PSYCHOANALYST',
          status: 'ACTIVE',
          startTime: '2024-01-15T10:30:00.000Z',
          transcript: [],
          topics: [],
        },
        {
          id: 'session-2',
          userId: 'test-user-id',
          agentType: 'INTAKE',
          status: 'COMPLETED',
          startTime: '2024-01-16T14:00:00.000Z',
          transcript: [],
          topics: [],
        },
      ];

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse(mockSessionsData)
      );

      const { container } = render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText(/Session.*1\/15\/2024/)).toBeInTheDocument();
      });

      const dividers = container.querySelectorAll('.MuiDivider-root');
      expect(dividers.length).toBe(1); // One divider for two sessions
    });
  });

  describe('Navigation', () => {
    it('should navigate to session detail on session click', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      const mockSessionData = [
        {
          id: 'session-abc-123',
          userId: 'test-user-id',
          agentType: 'PSYCHOANALYST',
          status: 'ACTIVE',
          startTime: '2024-01-15T10:30:00.000Z',
          transcript: [],
          topics: [],
        },
      ];

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse(mockSessionData)
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText(/Session.*1\/15\/2024/)).toBeInTheDocument();
      });

      const sessionButton = screen.getByRole('button', { name: /Session.*1\/15\/2024/ });
      fireEvent.click(sessionButton);

      expect(mockNavigate).toHaveBeenCalledWith('/session/session-abc-123');
    });
  });

  describe('Data Parsing', () => {
    it('should parse ISO date strings to Date objects', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      const mockSessionData = [
        {
          id: 'session-1',
          userId: 'test-user-id',
          agentType: 'PSYCHOANALYST',
          status: 'ACTIVE',
          startTime: '2024-01-15T10:30:00.000Z',
          endTime: '2024-01-15T11:30:00.000Z',
          transcript: [
            {
              id: 'msg-1',
              content: 'Hello',
              role: 'user',
              timestamp: '2024-01-15T10:30:00.000Z',
              sessionId: 'session-1',
            },
          ],
          topics: [],
        },
      ];

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse(mockSessionData)
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        // Should display formatted date/time (proves Date parsing worked)
        expect(screen.getByText(/Session.*1\/15\/2024/)).toBeInTheDocument();
      });
    });

    it('should handle sessions without endTime', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      const mockSessionData = [
        {
          id: 'session-1',
          userId: 'test-user-id',
          agentType: 'PSYCHOANALYST',
          status: 'ACTIVE',
          startTime: '2024-01-15T10:30:00.000Z',
          endTime: null,
          transcript: [],
          topics: [],
        },
      ];

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse(mockSessionData)
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText(/Session.*1\/15\/2024/)).toBeInTheDocument();
      });
    });

    it('should handle sessions with no topics', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      const mockSessionData = [
        {
          id: 'session-1',
          userId: 'test-user-id',
          agentType: 'PSYCHOANALYST',
          status: 'ACTIVE',
          startTime: '2024-01-15T10:30:00.000Z',
          transcript: [],
          topics: null,
        },
      ];

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse(mockSessionData)
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText(/0 messages • 0 topics/)).toBeInTheDocument();
      });
    });
  });

  describe('API Request', () => {
    it('should fetch sessions with correct user_id query parameter', async () => {
      const mockUser = createMockUser({ id: 'user-xyz-789' });
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse([])
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          '/api/sessions?user_id=user-xyz-789'
        );
      });
    });
  });

  describe('Page Structure', () => {
    it('should display page title', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse([])
      );

      render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText('Session History')).toBeInTheDocument();
      });

      expect(screen.getByText('Session History')).toHaveClass(
        'MuiTypography-h4'
      );
    });

    it('should wrap content in container with correct maxWidth', async () => {
      const mockUser = createMockUser();
      const useAppContext = require('../../contexts/AppContext').useAppContext;

      useAppContext.mockReturnValue({
        state: {
          user: mockUser,
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      (global.fetch as jest.Mock).mockResolvedValueOnce(
        createMockResponse([])
      );

      const { container } = render(<SessionHistoryPage />);

      await waitFor(() => {
        expect(screen.getByText('Session History')).toBeInTheDocument();
      });

      const containerElement = container.querySelector('.MuiContainer-maxWidthMd');
      expect(containerElement).toBeInTheDocument();
    });
  });
});
