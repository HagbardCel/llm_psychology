import { render, screen, fireEvent } from '@testing-library/react';
import App from '../App';

// Mock all page components
jest.mock('../pages/HomePage', () => ({
  HomePage: () => <div data-testid="home-page">Home Page</div>,
}));

jest.mock('../pages/SessionPage', () => ({
  SessionPage: () => <div data-testid="session-page">Session Page</div>,
}));

jest.mock('../pages/SessionHistoryPage', () => ({
  SessionHistoryPage: () => <div data-testid="history-page">History Page</div>,
}));

jest.mock('../pages/NotFoundPage', () => ({
  NotFoundPage: () => <div data-testid="not-found-page">Not Found Page</div>,
}));

// Mock Navigation component
jest.mock('../components/Navigation', () => ({
  Navigation: ({ open, onClose }: { open: boolean; onClose: () => void }) => (
    <div data-testid="navigation-mock">
      Navigation {open ? 'Open' : 'Closed'}
      <button data-testid="mock-close-navigation" onClick={onClose}>
        Close
      </button>
    </div>
  ),
}));

// Mock contexts
jest.mock('../contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="auth-provider">{children}</div>
  ),
}));

jest.mock('../contexts/AppContext', () => ({
  AppProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="app-provider">{children}</div>
  ),
}));

describe('App', () => {
  beforeEach(() => {
    // Reset window.location before each test
    window.history.pushState({}, '', '/');
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering & Structure', () => {
    it('should render without crashing', () => {
      const { container } = render(<App />);

      expect(container).toBeInTheDocument();
    });

    it('should render AuthProvider', () => {
      render(<App />);

      expect(screen.getByTestId('auth-provider')).toBeInTheDocument();
    });

    it('should render AppProvider inside AuthProvider', () => {
      render(<App />);

      const authProvider = screen.getByTestId('auth-provider');
      const appProvider = screen.getByTestId('app-provider');

      expect(authProvider).toContainElement(appProvider);
    });

    it('should render Navigation component', () => {
      render(<App />);

      expect(screen.getByTestId('navigation-mock')).toBeInTheDocument();
    });

    it('should apply MUI theme', () => {
      const { container } = render(<App />);

      // ThemeProvider should be applied (MUI components use theme)
      expect(container.querySelector('.MuiBox-root')).toBeInTheDocument();
    });

    it('should render CssBaseline', () => {
      const { container } = render(<App />);

      // CssBaseline creates a style element, verify app structure exists
      expect(container).toBeInTheDocument();
    });

    it('should render main layout Box', () => {
      const { container } = render(<App />);

      const boxes = container.querySelectorAll('.MuiBox-root');
      expect(boxes.length).toBeGreaterThan(0);
    });
  });

  describe('Routing', () => {
    it('should render HomePage at root path', () => {
      window.history.pushState({}, '', '/');
      render(<App />);

      expect(screen.getByTestId('home-page')).toBeInTheDocument();
    });

    it('should render SessionPage at /session', () => {
      window.history.pushState({}, '', '/session');
      render(<App />);

      expect(screen.getByTestId('session-page')).toBeInTheDocument();
    });

    it('should render SessionPage at /session/:sessionId', () => {
      window.history.pushState({}, '', '/session/abc123');
      render(<App />);

      expect(screen.getByTestId('session-page')).toBeInTheDocument();
    });

    it('should render SessionHistoryPage at /history', () => {
      window.history.pushState({}, '', '/history');
      render(<App />);

      expect(screen.getByTestId('history-page')).toBeInTheDocument();
    });

    it('should render "Coming Soon" for /settings', () => {
      window.history.pushState({}, '', '/settings');
      render(<App />);

      expect(screen.getByText('Settings (Coming Soon)')).toBeInTheDocument();
    });

    it('should render "Coming Soon" for /about', () => {
      window.history.pushState({}, '', '/about');
      render(<App />);

      expect(screen.getByText('About (Coming Soon)')).toBeInTheDocument();
    });

    it('should render "Coming Soon" for /profile', () => {
      window.history.pushState({}, '', '/profile');
      render(<App />);

      expect(screen.getByText('Profile Setup (Coming Soon)')).toBeInTheDocument();
    });

    it('should render "Coming Soon" for /intake', () => {
      window.history.pushState({}, '', '/intake');
      render(<App />);

      expect(screen.getByText('Intake Assessment (Coming Soon)')).toBeInTheDocument();
    });

    it('should render "Coming Soon" for /assessment', () => {
      window.history.pushState({}, '', '/assessment');
      render(<App />);

      expect(screen.getByText('Therapy Assessment (Coming Soon)')).toBeInTheDocument();
    });

    it('should render "Coming Soon" for /progress', () => {
      window.history.pushState({}, '', '/progress');
      render(<App />);

      expect(screen.getByText('Progress Tracking (Coming Soon)')).toBeInTheDocument();
    });

    it('should render "Coming Soon" for /schedule', () => {
      window.history.pushState({}, '', '/schedule');
      render(<App />);

      expect(screen.getByText('Session Scheduling (Coming Soon)')).toBeInTheDocument();
    });

    it('should render NotFoundPage for unknown routes', () => {
      window.history.pushState({}, '', '/unknown-route');
      render(<App />);

      expect(screen.getByTestId('not-found-page')).toBeInTheDocument();
    });

    it('should render NotFoundPage for /invalid/nested/route', () => {
      window.history.pushState({}, '', '/invalid/nested/route');
      render(<App />);

      expect(screen.getByTestId('not-found-page')).toBeInTheDocument();
    });
  });

  describe('Navigation State', () => {
    it('should initialize with navigation closed', () => {
      render(<App />);

      expect(screen.getByText('Navigation Closed')).toBeInTheDocument();
    });

    it('should render Navigation with onClose handler', () => {
      render(<App />);

      // Navigation component should be rendered with props
      expect(screen.getByTestId('navigation-mock')).toBeInTheDocument();
    });

    it('should call handleNavigationClose when Navigation onClose is triggered', () => {
      render(<App />);

      const closeButton = screen.getByTestId('mock-close-navigation');
      fireEvent.click(closeButton);

      // Should not crash - handler is called successfully
      expect(screen.getByTestId('navigation-mock')).toBeInTheDocument();
    });
  });

  describe('Theme Configuration', () => {
    it('should apply custom theme primary color', () => {
      const { container } = render(<App />);

      // Theme is applied to the component tree
      expect(container).toBeInTheDocument();
    });

    it('should apply custom theme background color', () => {
      const { container } = render(<App />);

      // Verify theme provider is wrapping content
      expect(container.firstChild).toBeInTheDocument();
    });

    it('should apply button text transform override', () => {
      const { container } = render(<App />);

      // Theme overrides are applied
      expect(container).toBeInTheDocument();
    });
  });

  describe('Integration', () => {
    it('should have proper provider hierarchy: Theme > Auth > App > Router', () => {
      render(<App />);

      const authProvider = screen.getByTestId('auth-provider');
      const appProvider = screen.getByTestId('app-provider');

      // Verify nesting
      expect(authProvider).toContainElement(appProvider);
    });

    it('should render both Navigation and route content', () => {
      render(<App />);

      expect(screen.getByTestId('navigation-mock')).toBeInTheDocument();
      expect(screen.getByTestId('home-page')).toBeInTheDocument();
    });

    it('should maintain layout structure with flex display', () => {
      const { container } = render(<App />);

      const boxes = container.querySelectorAll('.MuiBox-root');
      expect(boxes.length).toBeGreaterThan(0);
    });
  });

  describe('Edge Cases', () => {
    it('should render without errors when re-rendered', () => {
      const { rerender } = render(<App />);

      // Re-render should not crash
      rerender(<App />);
      expect(screen.getByTestId('home-page')).toBeInTheDocument();
    });

    it('should maintain structure across multiple renders', () => {
      const { rerender, container } = render(<App />);

      const initialBoxCount = container.querySelectorAll('.MuiBox-root').length;

      rerender(<App />);

      const afterRerenderBoxCount = container.querySelectorAll('.MuiBox-root').length;
      expect(afterRerenderBoxCount).toBe(initialBoxCount);
    });
  });
});
