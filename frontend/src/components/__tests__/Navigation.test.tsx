import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { Navigation } from '../Navigation';
import { UserStatus } from '../../types';

const mockNavigate = jest.fn();
const mockLocation = { pathname: '/' };

jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
  useLocation: () => mockLocation,
}));

jest.mock('../../contexts/AppContext', () => ({
  useCurrentUserId: () => 'test-user-id',
}));

const mockUseUserProfile = jest.fn();
jest.mock('../../hooks/useUserProfile', () => ({
  useUserProfile: (...args: any[]) => mockUseUserProfile(...args),
}));

describe('Navigation', () => {
  const mockOnClose = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
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
      data: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE },
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
      data: { id: 'test-user-id', name: 'Test User', status: UserStatus.PLAN_COMPLETE },
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
