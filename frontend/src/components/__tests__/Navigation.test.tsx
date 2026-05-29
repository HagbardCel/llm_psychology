import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router';
import { Navigation } from '../Navigation';
import { UserStatus } from '../../types';

const mockNavigate = vi.fn();
const mockLocation = { pathname: '/' };

vi.mock('react-router', async () => ({
  ...(await vi.importActual<typeof import('react-router')>('react-router')),
  useNavigate: () => mockNavigate,
  useLocation: () => mockLocation,
}));

vi.mock('../../contexts/AppContext', () => ({
  useCurrentUserId: () => 'test-user-id',
  useCurrentSessionId: () => 'test-session-id',
}));

const mockUseUserProfile = vi.fn();
vi.mock('../../hooks/useUserProfile', () => ({
  useUserProfile: (...args: any[]) => mockUseUserProfile(...args),
}));

describe('Navigation', () => {
  const mockOnClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockLocation.pathname = '/';
  });

  it('renders user name and status when user is available', () => {
    mockUseUserProfile.mockReturnValue({
      data: { id: 'test-user-id', name: 'Test User', status: UserStatus.PROFILE_ONLY },
      isLoading: false,
      error: null,
    });

    render(
      <BrowserRouter>
        <Navigation open={true} onClose={mockOnClose} />
      </BrowserRouter>
    );

    expect(screen.getByText('Test User')).toBeInTheDocument();
    expect(screen.getByText('Setup Required')).toBeInTheDocument();
  });

  it('renders expected menu items', () => {
    mockUseUserProfile.mockReturnValue({
      data: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_UPDATE_COMPLETE },
      isLoading: false,
      error: null,
    });

    render(
      <BrowserRouter>
        <Navigation open={true} onClose={mockOnClose} />
      </BrowserRouter>
    );

    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('New Session')).toBeInTheDocument();
    expect(screen.getByText('Session History')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByText('About')).toBeInTheDocument();
  });

  it('navigates and closes when clicking an enabled item', () => {
    mockUseUserProfile.mockReturnValue({
      data: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_UPDATE_COMPLETE },
      isLoading: false,
      error: null,
    });

    render(
      <BrowserRouter>
        <Navigation open={true} onClose={mockOnClose} />
      </BrowserRouter>
    );

    fireEvent.click(screen.getByText('Session History'));
    expect(mockNavigate).toHaveBeenCalledWith('/history');
    expect(mockOnClose).toHaveBeenCalled();
  });
});
