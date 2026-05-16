import { render, screen, fireEvent } from '@testing-library/react';
import { Dashboard } from '../Dashboard';

const mockNavigate = vi.fn();

vi.mock('react-router', async () => ({
  ...(await vi.importActual<typeof import('react-router')>('react-router')),
  useNavigate: () => mockNavigate,
}));

vi.mock('../../contexts/AppContext', () => ({
  useCurrentUserId: () => 'test-user-id',
  useCurrentSessionId: () => 'test-session-id',
}));

const mockUseUserProfile = vi.fn();
vi.mock('../../hooks/useUserProfile', () => ({
  useUserProfile: (...args: any[]) => mockUseUserProfile(...args),
}));

const mockUseSessionHistory = vi.fn();
vi.mock('../../hooks/useSessionHistory', () => ({
  useSessionHistory: (...args: any[]) => mockUseSessionHistory(...args),
}));

const mockUseTherapyPlan = vi.fn();
vi.mock('../../hooks/useTherapyPlan', () => ({
  useTherapyPlan: (...args: any[]) => mockUseTherapyPlan(...args),
}));

const mockUseWorkflowNextAction = vi.fn();
vi.mock('../../hooks/useWorkflowNavigation', () => ({
  useWorkflowNextAction: (...args: any[]) => mockUseWorkflowNextAction(...args),
}));

vi.mock('../shared', () => ({
  PageContainer: ({ title, children }: any) => (
    <div>
      <h1>{title}</h1>
      {children}
    </div>
  ),
  WorkflowStepper: () => <div data-testid="workflow-stepper" />,
}));

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading state while fetching data', () => {
    mockUseUserProfile.mockReturnValue({ data: null, isLoading: true, error: null });
    mockUseWorkflowNextAction.mockReturnValue({ data: null, isLoading: true, error: null });
    mockUseSessionHistory.mockReturnValue({ data: [], isLoading: false, error: null });
    mockUseTherapyPlan.mockReturnValue({ data: null, isLoading: false, error: null });

    render(<Dashboard />);

    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
  });

  it('renders error state when user profile fails to load', () => {
    mockUseUserProfile.mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error('failed'),
    });
    mockUseWorkflowNextAction.mockReturnValue({ data: null, isLoading: false, error: null });
    mockUseSessionHistory.mockReturnValue({ data: [], isLoading: false, error: null });
    mockUseTherapyPlan.mockReturnValue({ data: null, isLoading: false, error: null });

    render(<Dashboard />);

    expect(
      screen.getByText('Failed to load user profile. Please try refreshing the page.')
    ).toBeInTheDocument();
  });

  it('navigates to backend-provided next route when clicking Continue', () => {
    mockUseUserProfile.mockReturnValue({
      data: { id: 'test-user-id', name: 'Test User', status: 'PROFILE_ONLY' },
      isLoading: false,
      error: null,
    });
    mockUseSessionHistory.mockReturnValue({ data: [], isLoading: false, error: null });
    mockUseTherapyPlan.mockReturnValue({ data: null, isLoading: false, error: null });
    mockUseWorkflowNextAction.mockReturnValue({
      data: {
        user_id: 'test-user-id',
        workflow_state: 'NEW',
        required_action: 'complete_profile',
        required_fields: ['name'],
        defaults: null,
        prompt: 'Complete your profile.',
        blocking: true,
        timestamp: new Date().toISOString(),
      },
      isLoading: false,
      error: null,
    });

    render(<Dashboard />);

    expect(screen.getByRole('heading', { name: 'Welcome back, Test User' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Complete Profile' }));
    expect(mockNavigate).toHaveBeenCalledWith('/profile');
  });
});
