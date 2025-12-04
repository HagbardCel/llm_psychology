import { render, screen } from '@testing-library/react';
import { HomePage } from '../HomePage';

// Mock the Dashboard component
jest.mock('../../components/Dashboard', () => ({
  Dashboard: () => <div data-testid="dashboard-mock">Dashboard Component</div>,
}));

describe('HomePage', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('should render Dashboard component', () => {
    render(<HomePage />);

    expect(screen.getByTestId('dashboard-mock')).toBeInTheDocument();
  });

  it('should render without crashing', () => {
    const { container } = render(<HomePage />);

    expect(container).toBeInTheDocument();
  });

  it('should only render Dashboard (no other content)', () => {
    const { container } = render(<HomePage />);

    // Should only have the mocked Dashboard component
    expect(screen.getByTestId('dashboard-mock')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="dashboard-mock"]')).toBeInTheDocument();
  });
});
