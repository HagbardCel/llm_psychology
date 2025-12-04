import { render, screen, fireEvent } from '@testing-library/react';
import { NotFoundPage } from '../NotFoundPage';

// Mock react-router-dom
const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

describe('NotFoundPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render 404 heading', () => {
      render(<NotFoundPage />);

      expect(screen.getByText('404')).toBeInTheDocument();
    });

    it('should render "Page Not Found" heading', () => {
      render(<NotFoundPage />);

      expect(screen.getByText('Page Not Found')).toBeInTheDocument();
    });

    it('should render error message', () => {
      render(<NotFoundPage />);

      expect(
        screen.getByText("The page you're looking for doesn't exist or has been moved.")
      ).toBeInTheDocument();
    });

    it('should render "Go Home" button', () => {
      render(<NotFoundPage />);

      const button = screen.getByRole('button', { name: /go home/i });
      expect(button).toBeInTheDocument();
    });

    it('should render Home icon in button', () => {
      const { container } = render(<NotFoundPage />);

      const homeIcon = container.querySelector('[data-testid="HomeIcon"]');
      expect(homeIcon).toBeInTheDocument();
    });

    it('should render in a Container with sm maxWidth', () => {
      const { container } = render(<NotFoundPage />);

      const muiContainer = container.querySelector('.MuiContainer-maxWidthSm');
      expect(muiContainer).toBeInTheDocument();
    });
  });

  describe('Navigation', () => {
    it('should navigate to home when "Go Home" button clicked', () => {
      render(<NotFoundPage />);

      const button = screen.getByRole('button', { name: /go home/i });
      fireEvent.click(button);

      expect(mockNavigate).toHaveBeenCalledTimes(1);
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });

    it('should not navigate on initial render', () => {
      render(<NotFoundPage />);

      expect(mockNavigate).not.toHaveBeenCalled();
    });
  });

  describe('Layout & Styling', () => {
    it('should apply centered flexbox layout to Box', () => {
      const { container } = render(<NotFoundPage />);

      const box = container.querySelector('.MuiBox-root');
      expect(box).toBeInTheDocument();
    });

    it('should render Typography with correct variants', () => {
      render(<NotFoundPage />);

      // h1 variant for 404
      const h1Typography = screen.getByText('404').closest('.MuiTypography-h1');
      expect(h1Typography).toBeInTheDocument();

      // h4 variant for Page Not Found
      const h4Typography = screen.getByText('Page Not Found').closest('.MuiTypography-h4');
      expect(h4Typography).toBeInTheDocument();

      // body1 variant for message
      const bodyTypography = screen
        .getByText("The page you're looking for doesn't exist or has been moved.")
        .closest('.MuiTypography-body1');
      expect(bodyTypography).toBeInTheDocument();
    });

    it('should render Button with contained variant', () => {
      render(<NotFoundPage />);

      const button = screen.getByRole('button', { name: /go home/i });
      expect(button.closest('.MuiButton-contained')).toBeInTheDocument();
    });

    it('should render Button with large size', () => {
      render(<NotFoundPage />);

      const button = screen.getByRole('button', { name: /go home/i });
      expect(button.closest('.MuiButton-sizeLarge')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('should render without crashing', () => {
      const { container } = render(<NotFoundPage />);

      expect(container).toBeInTheDocument();
    });

    it('should handle multiple clicks on "Go Home" button', () => {
      render(<NotFoundPage />);

      const button = screen.getByRole('button', { name: /go home/i });
      fireEvent.click(button);
      fireEvent.click(button);
      fireEvent.click(button);

      expect(mockNavigate).toHaveBeenCalledTimes(3);
    });
  });
});
