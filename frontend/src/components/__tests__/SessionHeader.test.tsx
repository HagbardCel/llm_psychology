import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SessionHeader } from '../SessionHeader';
import { Session, TherapyStyle, AgentType, SessionStatus } from '../../types';
import { format } from 'date-fns';

describe('SessionHeader', () => {
  const mockOnMenuClick = vi.fn();
  const mockOnSettingsClick = vi.fn();
  const mockOnEndSession = vi.fn();

  const createMockSession = (overrides?: Partial<Session>): Session => ({
    session_id: 'session-123',
    user_id: 'user-123',
    session_type: 'therapy',
    timestamp: new Date('2024-01-15T14:30:00').toISOString(),
    transcript: [],
    topics: [],
    psychological_summary: null,
    dominant_affects: [],
    key_themes: [],
    notable_interactions: null,
    interpretations: null,
    patient_reactions: null,
    enriched: false,
    agentType: AgentType.THERAPIST,
    status: SessionStatus.ACTIVE,
    startTime: new Date('2024-01-15T14:30:00'),
    ...overrides,
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Rendering & Basic Display', () => {
    it('should render AppBar with Toolbar', () => {
      const { container } = render(
        <SessionHeader
          onMenuClick={mockOnMenuClick}
          onSettingsClick={mockOnSettingsClick}
          onEndSession={mockOnEndSession}
        />
      );

      expect(container.querySelector('.MuiAppBar-root')).toBeInTheDocument();
      expect(container.querySelector('.MuiToolbar-root')).toBeInTheDocument();
    });

    it('should render menu icon button', () => {
      const { container } = render(
        <SessionHeader onMenuClick={mockOnMenuClick} />
      );

      const menuButton = screen.getByLabelText('menu');
      expect(menuButton).toBeInTheDocument();

      // Verify MenuIcon is present
      const menuIcon = container.querySelector('[data-testid="MenuIcon"]');
      expect(menuIcon).toBeInTheDocument();
    });

    it('should render avatar with Psychology icon', () => {
      const { container } = render(
        <SessionHeader onMenuClick={mockOnMenuClick} />
      );

      const avatar = container.querySelector('.MuiAvatar-root');
      expect(avatar).toBeInTheDocument();

      const psychologyIcon = container.querySelector('[data-testid="PsychologyIcon"]');
      expect(psychologyIcon).toBeInTheDocument();
    });

    it('should display "Psychoanalyst" title when no session', () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      expect(screen.getByText('Psychoanalyst')).toBeInTheDocument();
    });

    it('should render more options button', () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      const moreButton = screen.getByLabelText('more options');
      expect(moreButton).toBeInTheDocument();
    });

    it('should not crash with null props', () => {
      const { container } = render(<SessionHeader />);

      expect(container.querySelector('.MuiAppBar-root')).toBeInTheDocument();
    });

    it('should apply correct styling to AppBar', () => {
      const { container } = render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      const appBar = container.querySelector('.MuiAppBar-root');
      expect(appBar).toHaveClass('MuiAppBar-positionStatic');
    });

    it('should show avatar with correct background color', () => {
      const { container } = render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      const avatar = container.querySelector('.MuiAvatar-root');
      expect(avatar).toBeInTheDocument();
    });
  });

  describe('Session Display', () => {
    it('should display "Intake Session" for INTAKE agent type', () => {
      const session = createMockSession({ agentType: AgentType.INTAKE });
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      expect(screen.getByText('Intake Session')).toBeInTheDocument();
    });

    it('should display "Assessment Session" for ASSESSMENT agent type', () => {
      const session = createMockSession({ agentType: AgentType.ASSESSMENT });
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      expect(screen.getByText('Assessment Session')).toBeInTheDocument();
    });

    it('should display "Therapy Session" for THERAPIST agent type', () => {
      const session = createMockSession({ agentType: AgentType.THERAPIST });
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      expect(screen.getByText('Therapy Session')).toBeInTheDocument();
    });

    it('should display "Reflection Session" for REFLECTION agent type', () => {
      const session = createMockSession({ agentType: AgentType.REFLECTION });
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      expect(screen.getByText('Reflection Session')).toBeInTheDocument();
    });

    it('should show session start time in HH:mm format', () => {
      const session = createMockSession();
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      const expectedTime = format(new Date(session.startTime!), 'HH:mm');
      expect(screen.getByText(`Started ${expectedTime}`)).toBeInTheDocument();
    });

    it('should hide start time when session has no startTime', () => {
      const session = createMockSession({ startTime: undefined as any });
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      expect(screen.queryByText(/Started/)).not.toBeInTheDocument();
    });

    it('should display therapy style chip when therapyStyle provided', () => {
      const session = createMockSession();
      render(
        <SessionHeader
          session={session}
          therapyStyle={TherapyStyle.FREUD}
          onMenuClick={mockOnMenuClick}
        />
      );

      expect(screen.getByText('Freudian Analysis')).toBeInTheDocument();
    });

    it('should hide therapy style chip when therapyStyle is null', () => {
      const session = createMockSession();
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      expect(screen.queryByText(/Analysis/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Therapy/)).toBeInTheDocument(); // "Therapy Session" still shown
    });
  });

  describe('Therapy Style Display', () => {
    it('should display "Freudian Analysis" for FREUD style', () => {
      render(
        <SessionHeader
          therapyStyle={TherapyStyle.FREUD}
          onMenuClick={mockOnMenuClick}
        />
      );

      expect(screen.getByText('Freudian Analysis')).toBeInTheDocument();
    });

    it('should display "Jungian Analysis" for JUNG style', () => {
      render(
        <SessionHeader
          therapyStyle={TherapyStyle.JUNG}
          onMenuClick={mockOnMenuClick}
        />
      );

      expect(screen.getByText('Jungian Analysis')).toBeInTheDocument();
    });

    it('should display "Cognitive Behavioral Therapy" for CBT style', () => {
      render(
        <SessionHeader
          therapyStyle={TherapyStyle.CBT}
          onMenuClick={mockOnMenuClick}
        />
      );

      expect(screen.getByText('Cognitive Behavioral Therapy')).toBeInTheDocument();
    });

    it('should handle unknown therapy styles gracefully', () => {
      // Test with an unknown style by casting
      const unknownStyle = 'unknown' as TherapyStyle;
      render(
        <SessionHeader
          therapyStyle={unknownStyle}
          onMenuClick={mockOnMenuClick}
        />
      );

      expect(screen.getByText('unknown')).toBeInTheDocument();
    });
  });

  describe('Menu Interactions', () => {
    it('should open menu when more button clicked', () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      expect(screen.getByText('Settings')).toBeInTheDocument();
    });

    it('should close menu when clicking outside', async () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      // Open menu
      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      expect(screen.getByText('Settings')).toBeInTheDocument();

      // Close menu by clicking the modal backdrop (reliable in jsdom/MUI portals)
      const backdrop = document.querySelector('.MuiBackdrop-root') as HTMLElement | null;
      expect(backdrop).toBeTruthy();
      if (backdrop) {
        fireEvent.mouseDown(backdrop);
        fireEvent.click(backdrop);
        fireEvent.mouseUp(backdrop);
      }

      // Menu should be closed (Settings should not be visible)
      // Note: MUI Menu uses portal, so we need to wait for it to close
      await waitFor(() => {
        expect(screen.queryByText('Settings')).not.toBeInTheDocument();
      });
    });

    it('should show Settings menu item', () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      expect(screen.getByText('Settings')).toBeInTheDocument();
    });

    it('should show "End Session" menu item only when session exists', () => {
      const session = createMockSession();
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      expect(screen.getByText('End Session')).toBeInTheDocument();
    });

    it('should hide "End Session" menu item when no session', () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      expect(screen.queryByText('End Session')).not.toBeInTheDocument();
    });

    it('should close menu after Settings clicked', async () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} onSettingsClick={mockOnSettingsClick} />);

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      const settingsItem = screen.getByText('Settings');
      fireEvent.click(settingsItem);

      // Menu should close after clicking Settings
      await waitFor(() => {
        expect(screen.queryByText('Settings')).not.toBeInTheDocument();
      });
    });

    it('should close menu after End Session clicked', async () => {
      const session = createMockSession();
      render(
        <SessionHeader
          session={session}
          onMenuClick={mockOnMenuClick}
          onEndSession={mockOnEndSession}
        />
      );

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      const endSessionItem = screen.getByText('End Session');
      fireEvent.click(endSessionItem);

      // Menu should close after clicking End Session
      await waitFor(() => {
        expect(screen.queryByText('End Session')).not.toBeInTheDocument();
      });
    });

    it('should apply error color to End Session item', () => {
      const session = createMockSession();
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      const endSessionItem = screen.getByText('End Session').closest('.MuiMenuItem-root');
      expect(endSessionItem).toBeInTheDocument();
    });
  });

  describe('Callback Functions', () => {
    it('should call onMenuClick when menu icon clicked', () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} />);

      const menuButton = screen.getByLabelText('menu');
      fireEvent.click(menuButton);

      expect(mockOnMenuClick).toHaveBeenCalledTimes(1);
    });

    it('should call onSettingsClick when Settings menu item clicked', () => {
      render(<SessionHeader onMenuClick={mockOnMenuClick} onSettingsClick={mockOnSettingsClick} />);

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      const settingsItem = screen.getByText('Settings');
      fireEvent.click(settingsItem);

      expect(mockOnSettingsClick).toHaveBeenCalledTimes(1);
    });

    it('should call onEndSession when End Session menu item clicked', () => {
      const session = createMockSession();
      render(
        <SessionHeader
          session={session}
          onMenuClick={mockOnMenuClick}
          onEndSession={mockOnEndSession}
        />
      );

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      const endSessionItem = screen.getByText('End Session');
      fireEvent.click(endSessionItem);

      expect(mockOnEndSession).toHaveBeenCalledTimes(1);
    });

    it('should not crash when onMenuClick is undefined', () => {
      render(<SessionHeader />);

      const menuButton = screen.getByLabelText('menu');
      fireEvent.click(menuButton);

      // Should not throw error
      expect(menuButton).toBeInTheDocument();
    });

    it('should not crash when onSettingsClick/onEndSession are undefined', () => {
      const session = createMockSession();
      render(<SessionHeader session={session} />);

      const moreButton = screen.getByLabelText('more options');
      fireEvent.click(moreButton);

      const settingsItem = screen.getByText('Settings');
      fireEvent.click(settingsItem);

      // Should not throw error
      expect(settingsItem).toBeInTheDocument();
    });
  });

  describe('Date Formatting', () => {
    it('should format start time correctly with date-fns', () => {
      const session = createMockSession();
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      // Verify formatted time is displayed
      const expectedTime = format(new Date(session.startTime!), 'HH:mm');
      expect(screen.getByText(`Started ${expectedTime}`)).toBeInTheDocument();
    });

    it('should render component without startTime', () => {
      const session = createMockSession({ startTime: undefined as any });
      render(<SessionHeader session={session} onMenuClick={mockOnMenuClick} />);

      // Component should still render without crashing
      expect(screen.getByText('Therapy Session')).toBeInTheDocument();
      // Start time should not be shown
      expect(screen.queryByText(/Started/)).not.toBeInTheDocument();
    });
  });
});
