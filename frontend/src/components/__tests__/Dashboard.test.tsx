import { render, screen, fireEvent, within } from '@testing-library/react';
import { Dashboard } from '../Dashboard';
import { AppProvider } from '../../contexts/AppContext';
import { BrowserRouter } from 'react-router-dom';
import { Session, User, TherapyPlan, SessionStatus, AgentType, UserStatus, TherapyStyle } from '../../types';

// Mock useNavigate
const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
}));

// Mock date-fns to avoid timezone issues
jest.mock('date-fns', () => ({
  format: jest.fn((date: Date) => date.toLocaleDateString()),
  formatDistanceToNow: jest.fn(() => '5 minutes'),
}));

describe('Dashboard', () => {
  // Test data factories
  const createMockUser = (status: UserStatus = UserStatus.PLAN_COMPLETE): User => ({
    id: 'test-user-id',
    name: 'Test User',
    status,
    createdAt: new Date(),
    lastActiveAt: new Date(),
  });

  const createMockSession = (overrides?: Partial<Session>): Session => ({
    id: 'session-123',
    userId: 'test-user-id',
    agentType: AgentType.PSYCHOANALYST,
    status: SessionStatus.COMPLETED,
    startTime: new Date(Date.now() - 86400000), // 1 day ago
    transcript: [
      {
        id: 'msg-1',
        content: 'Test message',
        role: 'user',
        timestamp: new Date(),
        sessionId: 'session-123',
      },
    ],
    topics: [],
    ...overrides,
  });

  const createMockTherapyPlan = (): TherapyPlan => ({
    id: 'plan-123',
    userId: 'test-user-id',
    therapyStyle: TherapyStyle.FREUD,
    goals: ['Goal 1', 'Goal 2'],
    sessionCount: 5,
    createdAt: new Date(),
    updatedAt: new Date(),
  });

  const TestWrapper = ({ children }: { children: React.ReactNode }) => (
    <BrowserRouter>
      <AppProvider>{children}</AppProvider>
    </BrowserRouter>
  );

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render without crashing', () => {
      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Welcome to Your Therapeutic Journey')).toBeInTheDocument();
    });

    it('should render quick action cards', () => {
      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('New Session')).toBeInTheDocument();
      expect(screen.getByText('Session History')).toBeInTheDocument();
      expect(screen.getByText('Progress')).toBeInTheDocument();
      expect(screen.getByText('Schedule')).toBeInTheDocument();
    });
  });

  describe('Next Action Based on User Status', () => {
    it('should show "Create Profile" when no user', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
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

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Create Your Profile')).toBeInTheDocument();
      expect(screen.getByText('Start by creating your user profile to begin your therapeutic journey.')).toBeInTheDocument();
      expect(screen.getByText('Get Started')).toBeInTheDocument();
    });

    it('should show "Complete Intake Assessment" for PROFILE_ONLY status', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.PROFILE_ONLY),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Complete Intake Assessment')).toBeInTheDocument();
      expect(screen.getByText('Tell us about yourself and what you hope to achieve.')).toBeInTheDocument();
      expect(screen.getByText('Start Intake')).toBeInTheDocument();
    });

    it('should show "Complete Therapy Assessment" for INTAKE_COMPLETE status', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.INTAKE_COMPLETE),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Complete Therapy Assessment')).toBeInTheDocument();
      expect(screen.getByText('Let us recommend the best therapeutic approach for you.')).toBeInTheDocument();
      expect(screen.getByText('Start Assessment')).toBeInTheDocument();
    });

    it('should show "Begin Your Therapy Session" for PLAN_COMPLETE status', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.PLAN_COMPLETE),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Begin Your Therapy Session')).toBeInTheDocument();
      expect(screen.getByText('Ready to start your therapeutic journey with your personalized plan.')).toBeInTheDocument();
      expect(screen.getByText('Start Session')).toBeInTheDocument();
    });
  });

  describe('Progress Overview', () => {
    it('should display total sessions count', () => {
      const sessions = [
        createMockSession({ id: 'session-1' }),
        createMockSession({ id: 'session-2' }),
        createMockSession({ id: 'session-3' }),
      ];

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions,
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Total Sessions: 3')).toBeInTheDocument();
    });

    it('should display completed sessions count', () => {
      const sessions = [
        createMockSession({ id: 'session-1', status: SessionStatus.COMPLETED }),
        createMockSession({ id: 'session-2', status: SessionStatus.COMPLETED }),
        createMockSession({ id: 'session-3', status: SessionStatus.ACTIVE }),
      ];

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions,
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Completed: 2')).toBeInTheDocument();
    });

    it('should display setup progress for PROFILE_ONLY (20%)', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.PROFILE_ONLY),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('20% Complete')).toBeInTheDocument();
    });

    it('should display setup progress for INTAKE_COMPLETE (50%)', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.INTAKE_COMPLETE),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('50% Complete')).toBeInTheDocument();
    });

    it('should display setup progress for PLAN_COMPLETE (100%)', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.PLAN_COMPLETE),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('100% Complete')).toBeInTheDocument();
    });

    it('should display therapy plan when present', () => {
      const therapyPlan = createMockTherapyPlan();

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions: [],
          therapyPlan,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('FREUD Therapy')).toBeInTheDocument();
    });
  });

  describe('Active Session Alert', () => {
    it('should display alert when there is an active session', () => {
      const activeSession = createMockSession({
        id: 'active-session',
        status: SessionStatus.ACTIVE,
      });

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions: [activeSession],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText(/You have an active session that was started/)).toBeInTheDocument();
      expect(screen.getByText('Resume')).toBeInTheDocument();
    });

    it('should navigate to session when Resume button clicked', () => {
      const activeSession = createMockSession({
        id: 'active-session',
        status: SessionStatus.ACTIVE,
      });

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions: [activeSession],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const resumeButton = screen.getByText('Resume');
      fireEvent.click(resumeButton);

      expect(mockNavigate).toHaveBeenCalledWith('/session');
    });

    it('should not display alert when no active session', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.queryByText(/You have an active session/)).not.toBeInTheDocument();
    });
  });

  describe('Recent Sessions', () => {
    it('should display up to 5 recent completed sessions', () => {
      const sessions = Array.from({ length: 7 }, (_, i) =>
        createMockSession({
          id: `session-${i}`,
          status: SessionStatus.COMPLETED,
          startTime: new Date(Date.now() - i * 86400000),
        })
      );

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions,
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Recent Sessions')).toBeInTheDocument();

      // Should display exactly 5 sessions (getAllByText returns array)
      const sessionElements = screen.getAllByText('Therapy Session');
      expect(sessionElements.length).toBe(5);
    });

    it('should not display Recent Sessions section when no completed sessions', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.queryByText('Recent Sessions')).not.toBeInTheDocument();
    });

    it('should display correct session titles for different agent types', () => {
      const sessions = [
        createMockSession({ id: 'intake', agentType: AgentType.INTAKE }),
        createMockSession({ id: 'assessment', agentType: AgentType.ASSESSMENT }),
        createMockSession({ id: 'psycho', agentType: AgentType.PSYCHOANALYST }),
        createMockSession({ id: 'planning', agentType: AgentType.PLANNING }),
        createMockSession({ id: 'reflection', agentType: AgentType.REFLECTION }),
      ];

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions,
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Intake Session')).toBeInTheDocument();
      expect(screen.getByText('Assessment Session')).toBeInTheDocument();
      expect(screen.getByText('Therapy Session')).toBeInTheDocument();
      expect(screen.getByText('Planning Session')).toBeInTheDocument();
      expect(screen.getByText('Reflection Session')).toBeInTheDocument();
    });

    it('should navigate to history when "View All" clicked', () => {
      const sessions = [createMockSession()];

      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions,
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const viewAllButton = screen.getByText('View All');
      fireEvent.click(viewAllButton);

      expect(mockNavigate).toHaveBeenCalledWith('/history');
    });
  });

  describe('Quick Actions Navigation', () => {
    it('should navigate to /session when "New Session" Start button clicked', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.PLAN_COMPLETE),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      // Find the "New Session" card and click its Start button
      const newSessionCard = screen.getByText('New Session').closest('.MuiCard-root');
      const startButton = within(newSessionCard! as HTMLElement).getByText('Start');
      fireEvent.click(startButton);

      expect(mockNavigate).toHaveBeenCalledWith('/session');
    });

    it('should disable "New Session" button when user status is not PLAN_COMPLETE', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.INTAKE_COMPLETE),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const newSessionCard = screen.getByText('New Session').closest('.MuiCard-root');
      const startButton = within(newSessionCard! as HTMLElement).getByText('Start');

      expect(startButton).toBeDisabled();
    });

    it('should navigate to /history when "Session History" View button clicked', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const historyCard = screen.getByText('Session History').closest('.MuiCard-root');
      const viewButton = within(historyCard! as HTMLElement).getByText('View');
      fireEvent.click(viewButton);

      expect(mockNavigate).toHaveBeenCalledWith('/history');
    });

    it('should navigate to /progress when "Progress" View button clicked', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const progressCard = screen.getByText('Progress').closest('.MuiCard-root');
      const viewButton = within(progressCard! as HTMLElement).getByText('View');
      fireEvent.click(viewButton);

      expect(mockNavigate).toHaveBeenCalledWith('/progress');
    });

    it('should navigate to /schedule when "Schedule" Plan button clicked', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const scheduleCard = screen.getByText('Schedule').closest('.MuiCard-root');
      const planButton = within(scheduleCard! as HTMLElement).getByText('Plan');
      fireEvent.click(planButton);

      expect(mockNavigate).toHaveBeenCalledWith('/schedule');
    });
  });

  describe('Next Action Button Navigation', () => {
    it('should navigate to /profile when "Get Started" clicked', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
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

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const getStartedButton = screen.getByText('Get Started');
      fireEvent.click(getStartedButton);

      expect(mockNavigate).toHaveBeenCalledWith('/profile');
    });

    it('should navigate to /intake when "Start Intake" clicked', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.PROFILE_ONLY),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const startIntakeButton = screen.getByText('Start Intake');
      fireEvent.click(startIntakeButton);

      expect(mockNavigate).toHaveBeenCalledWith('/intake');
    });

    it('should navigate to /assessment when "Start Assessment" clicked', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.INTAKE_COMPLETE),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      const startAssessmentButton = screen.getByText('Start Assessment');
      fireEvent.click(startAssessmentButton);

      expect(mockNavigate).toHaveBeenCalledWith('/assessment');
    });
  });

  describe('Additional UserStatus Coverage', () => {
    it('should render for INTAKE_IN_PROGRESS status', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.INTAKE_IN_PROGRESS),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Welcome to Your Therapeutic Journey')).toBeInTheDocument();
    });

    it('should render for ASSESSMENT_IN_PROGRESS status', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.ASSESSMENT_IN_PROGRESS),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Welcome to Your Therapeutic Journey')).toBeInTheDocument();
    });

    it('should render for ASSESSMENT_COMPLETE status', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.ASSESSMENT_COMPLETE),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Welcome to Your Therapeutic Journey')).toBeInTheDocument();
    });

    it('should render for THERAPY_IN_PROGRESS status', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.THERAPY_IN_PROGRESS),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Welcome to Your Therapeutic Journey')).toBeInTheDocument();
    });

    it('should render for REFLECTION_IN_PROGRESS status', () => {
      jest.spyOn(require('../../contexts/AppContext'), 'useAppContext').mockReturnValue({
        state: {
          user: createMockUser(UserStatus.REFLECTION_IN_PROGRESS),
          sessions: [],
          therapyPlan: null,
          currentSession: null,
          isLoading: false,
          error: null,
        },
        actions: {},
      });

      render(
        <TestWrapper>
          <Dashboard />
        </TestWrapper>
      );

      expect(screen.getByText('Welcome to Your Therapeutic Journey')).toBeInTheDocument();
    });
  });
});
