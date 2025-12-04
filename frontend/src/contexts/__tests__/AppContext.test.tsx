import { renderHook, act, waitFor } from '@testing-library/react';
import { ReactNode } from 'react';
import { AppProvider, useAppContext } from '../AppContext';
import { User, Session, TherapyPlan, SessionStatus, AgentType, UserStatus, TherapyStyle } from '../../types';

// Mock localStorage
const mockGetItem = jest.fn();
const mockSetItem = jest.fn();
const mockRemoveItem = jest.fn();

jest.mock('../../hooks/useLocalStorage', () => ({
  useLocalStorage: () => ({
    getItem: mockGetItem,
    setItem: mockSetItem,
    removeItem: mockRemoveItem,
  }),
}));

// Mock console methods to avoid noise in tests
const originalConsoleLog = console.log;
const originalConsoleError = console.error;

describe('AppContext', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    console.log = jest.fn();
    console.error = jest.fn();
  });

  afterAll(() => {
    console.log = originalConsoleLog;
    console.error = originalConsoleError;
  });

  const wrapper = ({ children }: { children: ReactNode }) => (
    <AppProvider>{children}</AppProvider>
  );

  // Test data factories
  const createMockUser = (): User => ({
    id: 'test-user-id',
    name: 'Test User',
    email: 'test@example.com',
    status: UserStatus.INTAKE_COMPLETE,
    createdAt: new Date(),
    lastActiveAt: new Date(),
  });

  const createMockSession = (overrides?: Partial<Session>): Session => ({
    id: 'session-123',
    userId: 'test-user-id',
    agentType: AgentType.PSYCHOANALYST,
    status: SessionStatus.ACTIVE,
    startTime: new Date(),
    transcript: [],
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

  describe('useAppContext hook', () => {
    it('should throw error when used outside AppProvider', () => {
      // Suppress console.error for this test
      const originalError = console.error;
      console.error = jest.fn();

      expect(() => {
        renderHook(() => useAppContext());
      }).toThrow('useAppContext must be used within an AppProvider');

      console.error = originalError;
    });

    it('should provide context when used inside AppProvider', () => {
      mockGetItem.mockReturnValue(null);

      const { result } = renderHook(() => useAppContext(), { wrapper });

      expect(result.current.state).toBeDefined();
      expect(result.current.dispatch).toBeDefined();
      expect(result.current.actions).toBeDefined();
    });
  });

  describe('Reducer Actions', () => {
    beforeEach(() => {
      mockGetItem.mockReturnValue(null);
    });

    describe('SET_USER action', () => {
      it('should set user in state', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testUser = createMockUser();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setUser(testUser);
        });

        expect(result.current.state.user).toEqual(testUser);
      });

      it('should preserve other state when setting user', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testUser = createMockUser();
        const testSession = createMockSession();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(testSession);
          result.current.actions.setUser(testUser);
        });

        expect(result.current.state.user).toEqual(testUser);
        expect(result.current.state.currentSession).toEqual(testSession);
        expect(result.current.state.sessions).toContainEqual(testSession);
      });

      it('should handle null user', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setUser(null);
        });

        expect(result.current.state.user).toBeNull();
      });
    });

    describe('SET_CURRENT_SESSION action', () => {
      it('should set current session', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testSession = createMockSession();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setCurrentSession(testSession);
        });

        expect(result.current.state.currentSession).toEqual(testSession);
      });

      it('should clear current session when null', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testSession = createMockSession();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setCurrentSession(testSession);
        });

        expect(result.current.state.currentSession).toEqual(testSession);

        act(() => {
          result.current.actions.setCurrentSession(null);
        });

        expect(result.current.state.currentSession).toBeNull();
      });
    });

    describe('ADD_SESSION action', () => {
      it('should add new session to sessions array', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testSession = createMockSession();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(testSession);
        });

        expect(result.current.state.sessions).toHaveLength(1);
        expect(result.current.state.sessions[0]).toEqual(testSession);
      });

      it('should set new session as current session', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testSession = createMockSession();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(testSession);
        });

        expect(result.current.state.currentSession).toEqual(testSession);
      });

      it('should add multiple sessions', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const session1 = createMockSession({ id: 'session-1' });
        const session2 = createMockSession({ id: 'session-2' });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(session1);
          result.current.actions.addSession(session2);
        });

        expect(result.current.state.sessions).toHaveLength(2);
        expect(result.current.state.sessions).toContainEqual(session1);
        expect(result.current.state.sessions).toContainEqual(session2);
        expect(result.current.state.currentSession).toEqual(session2);
      });
    });

    describe('UPDATE_SESSION action', () => {
      it('should update existing session in sessions array', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testSession = createMockSession();
        const updatedSession = { ...testSession, status: SessionStatus.COMPLETED };

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(testSession);
          result.current.actions.updateSession(updatedSession);
        });

        expect(result.current.state.sessions).toHaveLength(1);
        expect(result.current.state.sessions[0].status).toBe(SessionStatus.COMPLETED);
      });

      it('should update current session if IDs match', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testSession = createMockSession();
        const updatedSession = { ...testSession, status: SessionStatus.COMPLETED };

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(testSession);
          result.current.actions.updateSession(updatedSession);
        });

        expect(result.current.state.currentSession?.status).toBe(SessionStatus.COMPLETED);
      });

      it('should not update current session if IDs do not match', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const session1 = createMockSession({ id: 'session-1' });
        const session2 = createMockSession({ id: 'session-2' });
        const updatedSession2 = { ...session2, status: SessionStatus.COMPLETED };

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(session1);
          result.current.actions.addSession(session2);
          result.current.actions.setCurrentSession(session1);
          result.current.actions.updateSession(updatedSession2);
        });

        expect(result.current.state.currentSession).toEqual(session1);
        expect(result.current.state.sessions.find(s => s.id === 'session-2')?.status).toBe(SessionStatus.COMPLETED);
      });

      it('should preserve other sessions when updating one', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const session1 = createMockSession({ id: 'session-1' });
        const session2 = createMockSession({ id: 'session-2' });
        const session3 = createMockSession({ id: 'session-3' });
        const updatedSession2 = { ...session2, status: SessionStatus.COMPLETED };

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(session1);
          result.current.actions.addSession(session2);
          result.current.actions.addSession(session3);
          result.current.actions.updateSession(updatedSession2);
        });

        expect(result.current.state.sessions).toHaveLength(3);
        expect(result.current.state.sessions).toContainEqual(session1);
        expect(result.current.state.sessions).toContainEqual(session3);
        expect(result.current.state.sessions.find(s => s.id === 'session-2')?.status).toBe(SessionStatus.COMPLETED);
      });
    });

    describe('SET_SESSIONS action', () => {
      it('should replace all sessions', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const session1 = createMockSession({ id: 'session-1' });
        const session2 = createMockSession({ id: 'session-2' });
        const newSessions = [
          createMockSession({ id: 'new-1' }),
          createMockSession({ id: 'new-2' }),
        ];

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(session1);
          result.current.actions.addSession(session2);
        });

        expect(result.current.state.sessions).toHaveLength(2);

        act(() => {
          result.current.actions.setSessions(newSessions);
        });

        expect(result.current.state.sessions).toHaveLength(2);
        expect(result.current.state.sessions).toEqual(newSessions);
      });

      it('should handle empty array', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const session1 = createMockSession({ id: 'session-1' });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(session1);
          result.current.actions.setSessions([]);
        });

        expect(result.current.state.sessions).toHaveLength(0);
      });
    });

    describe('SET_THERAPY_PLAN action', () => {
      it('should set therapy plan', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testPlan = createMockTherapyPlan();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setTherapyPlan(testPlan);
        });

        expect(result.current.state.therapyPlan).toEqual(testPlan);
      });

      it('should handle null therapy plan', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testPlan = createMockTherapyPlan();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setTherapyPlan(testPlan);
        });

        expect(result.current.state.therapyPlan).toEqual(testPlan);

        act(() => {
          result.current.actions.setTherapyPlan(null);
        });

        expect(result.current.state.therapyPlan).toBeNull();
      });
    });

    describe('SET_LOADING action', () => {
      it('should set loading state to true', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setLoading(true);
        });

        expect(result.current.state.isLoading).toBe(true);
      });

      it('should set loading state to false', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setLoading(true);
        });

        expect(result.current.state.isLoading).toBe(true);

        act(() => {
          result.current.actions.setLoading(false);
        });

        expect(result.current.state.isLoading).toBe(false);
      });
    });

    describe('SET_ERROR action', () => {
      it('should set error message', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setError('Test error message');
        });

        expect(result.current.state.error).toBe('Test error message');
      });

      it('should set loading to false when setting error', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setLoading(true);
          result.current.actions.setError('Test error');
        });

        expect(result.current.state.isLoading).toBe(false);
        expect(result.current.state.error).toBe('Test error');
      });

      it('should handle null error', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setError('Test error');
        });

        expect(result.current.state.error).toBe('Test error');

        act(() => {
          result.current.actions.setError(null);
        });

        expect(result.current.state.error).toBeNull();
      });
    });

    describe('CLEAR_ERROR action', () => {
      it('should clear error message', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setError('Test error');
        });

        expect(result.current.state.error).toBe('Test error');

        act(() => {
          result.current.actions.clearError();
        });

        expect(result.current.state.error).toBeNull();
      });

      it('should preserve other state when clearing error', async () => {
        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testUser = createMockUser();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setUser(testUser);
          result.current.actions.setError('Test error');
          result.current.actions.clearError();
        });

        expect(result.current.state.error).toBeNull();
        expect(result.current.state.user).toEqual(testUser);
      });
    });
  });

  describe('localStorage Integration', () => {
    beforeEach(() => {
      mockGetItem.mockReturnValue(null);
    });

    describe('Data Loading on Mount', () => {
      it('should load user from localStorage on mount', async () => {
        const testUser = createMockUser();
        mockGetItem
          .mockImplementation((key: string) => {
            if (key === 'schemaVersion') return 2;
            if (key === 'user') return testUser;
            return null;
          });

        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        expect(result.current.state.user).toEqual(testUser);
      });

      it('should load sessions from localStorage on mount', async () => {
        const testSessions = [
          createMockSession({ id: 'session-1', status: SessionStatus.COMPLETED }),
          createMockSession({ id: 'session-2', status: SessionStatus.ACTIVE }),
        ];

        mockGetItem
          .mockImplementation((key: string) => {
            if (key === 'schemaVersion') return 2;
            if (key === 'sessions') return testSessions;
            return null;
          });

        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        expect(result.current.state.sessions).toEqual(testSessions);
      });

      it('should load therapy plan from localStorage on mount', async () => {
        const testPlan = createMockTherapyPlan();

        mockGetItem
          .mockImplementation((key: string) => {
            if (key === 'schemaVersion') return 2;
            if (key === 'therapyPlan') return testPlan;
            return null;
          });

        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        expect(result.current.state.therapyPlan).toEqual(testPlan);
      });

      it('should set most recent active session as current session', async () => {
        const testSessions = [
          createMockSession({ id: 'session-1', status: SessionStatus.COMPLETED }),
          createMockSession({ id: 'session-2', status: SessionStatus.ACTIVE }),
          createMockSession({ id: 'session-3', status: SessionStatus.COMPLETED }),
        ];

        mockGetItem
          .mockImplementation((key: string) => {
            if (key === 'schemaVersion') return 2;
            if (key === 'sessions') return testSessions;
            return null;
          });

        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        expect(result.current.state.currentSession?.id).toBe('session-2');
      });

      it('should handle empty localStorage gracefully', async () => {
        mockGetItem.mockImplementation((key: string) => {
          if (key === 'schemaVersion') return 2;
          return null;
        });

        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        expect(result.current.state.user).toBeNull();
        expect(result.current.state.sessions).toEqual([]);
        expect(result.current.state.therapyPlan).toBeNull();
        expect(result.current.state.currentSession).toBeNull();
      });

      it('should handle corrupted localStorage data', async () => {
        mockGetItem.mockImplementation(() => {
          throw new Error('localStorage read error');
        });

        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.error).toBe('Failed to load stored data');
        });

        expect(result.current.state.isLoading).toBe(false);
      });
    });

    describe('Data Persistence', () => {
      it('should save user to localStorage when updated', async () => {
        mockGetItem.mockReturnValue(null);

        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testUser = createMockUser();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setUser(testUser);
        });

        await waitFor(() => {
          expect(mockSetItem).toHaveBeenCalledWith('user', testUser);
        });
      });

      it('should save sessions to localStorage when updated', async () => {
        mockGetItem.mockReturnValue(null);

        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testSession = createMockSession();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.addSession(testSession);
        });

        await waitFor(() => {
          expect(mockSetItem).toHaveBeenCalledWith('sessions', expect.arrayContaining([testSession]));
        });
      });

      it('should save therapy plan to localStorage when updated', async () => {
        mockGetItem.mockReturnValue(null);

        const { result } = renderHook(() => useAppContext(), { wrapper });
        const testPlan = createMockTherapyPlan();

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        act(() => {
          result.current.actions.setTherapyPlan(testPlan);
        });

        await waitFor(() => {
          expect(mockSetItem).toHaveBeenCalledWith('therapyPlan', testPlan);
        });
      });

      it('should not save empty sessions array to localStorage', async () => {
        mockGetItem.mockReturnValue(null);

        const { result } = renderHook(() => useAppContext(), { wrapper });

        await waitFor(() => {
          expect(result.current.state.isLoading).toBe(false);
        });

        expect(mockSetItem).not.toHaveBeenCalledWith('sessions', []);
      });
    });
  });

  describe('Schema Migration', () => {
    it('should detect old schema version', async () => {
      mockGetItem.mockImplementation((key: string) => {
        if (key === 'schemaVersion') return 1;
        return null;
      });

      // Mock localStorage.clear
      const mockClear = jest.fn();
      Object.defineProperty(window, 'localStorage', {
        value: {
          clear: mockClear,
        },
        writable: true,
      });

      renderHook(() => useAppContext(), { wrapper });

      await waitFor(() => {
        expect(mockClear).toHaveBeenCalled();
      });
    });

    it('should detect missing schema version', async () => {
      mockGetItem.mockImplementation((key: string) => {
        if (key === 'schemaVersion') return null;
        return null;
      });

      const mockClear = jest.fn();
      Object.defineProperty(window, 'localStorage', {
        value: {
          clear: mockClear,
        },
        writable: true,
      });

      renderHook(() => useAppContext(), { wrapper });

      await waitFor(() => {
        expect(mockClear).toHaveBeenCalled();
      });
    });

    it('should set schema version to 2 after clearing', async () => {
      mockGetItem.mockImplementation((key: string) => {
        if (key === 'schemaVersion') return 1;
        return null;
      });

      const mockClear = jest.fn();
      Object.defineProperty(window, 'localStorage', {
        value: {
          clear: mockClear,
        },
        writable: true,
      });

      renderHook(() => useAppContext(), { wrapper });

      await waitFor(() => {
        expect(mockSetItem).toHaveBeenCalledWith('schemaVersion', 2);
      });
    });

    it('should preserve data when schema version is current', async () => {
      const testUser = createMockUser();
      const testSessions = [createMockSession()];

      mockGetItem.mockImplementation((key: string) => {
        if (key === 'schemaVersion') return 2;
        if (key === 'user') return testUser;
        if (key === 'sessions') return testSessions;
        return null;
      });

      const mockClear = jest.fn();
      Object.defineProperty(window, 'localStorage', {
        value: {
          clear: mockClear,
        },
        writable: true,
      });

      const { result } = renderHook(() => useAppContext(), { wrapper });

      await waitFor(() => {
        expect(result.current.state.isLoading).toBe(false);
      });

      expect(mockClear).not.toHaveBeenCalled();
      expect(result.current.state.user).toEqual(testUser);
      expect(result.current.state.sessions).toEqual(testSessions);
    });

    it('should log when clearing old schema', async () => {
      mockGetItem.mockImplementation((key: string) => {
        if (key === 'schemaVersion') return 1;
        return null;
      });

      const mockClear = jest.fn();
      Object.defineProperty(window, 'localStorage', {
        value: {
          clear: mockClear,
        },
        writable: true,
      });

      renderHook(() => useAppContext(), { wrapper });

      await waitFor(() => {
        expect(console.log).toHaveBeenCalledWith('Cleared old localStorage schema');
      });
    });
  });

  describe('Initial State', () => {
    beforeEach(() => {
      mockGetItem.mockReturnValue(null);
    });

    it('should have correct initial state', async () => {
      mockGetItem.mockImplementation((key: string) => {
        if (key === 'schemaVersion') return 2;
        return null;
      });

      const { result } = renderHook(() => useAppContext(), { wrapper });

      await waitFor(() => {
        expect(result.current.state.isLoading).toBe(false);
      });

      expect(result.current.state).toEqual({
        user: null,
        currentSession: null,
        sessions: [],
        therapyPlan: null,
        isLoading: false,
        error: null,
      });
    });
  });

  describe('AppProvider', () => {
    it('should provide actions to children', async () => {
      mockGetItem.mockReturnValue(null);

      const { result } = renderHook(() => useAppContext(), { wrapper });

      await waitFor(() => {
        expect(result.current.state.isLoading).toBe(false);
      });

      expect(result.current.actions).toHaveProperty('setUser');
      expect(result.current.actions).toHaveProperty('setCurrentSession');
      expect(result.current.actions).toHaveProperty('addSession');
      expect(result.current.actions).toHaveProperty('updateSession');
      expect(result.current.actions).toHaveProperty('setSessions');
      expect(result.current.actions).toHaveProperty('setTherapyPlan');
      expect(result.current.actions).toHaveProperty('setLoading');
      expect(result.current.actions).toHaveProperty('setError');
      expect(result.current.actions).toHaveProperty('clearError');
    });

    it('should provide dispatch to children', async () => {
      mockGetItem.mockReturnValue(null);

      const { result } = renderHook(() => useAppContext(), { wrapper });

      await waitFor(() => {
        expect(result.current.state.isLoading).toBe(false);
      });

      expect(typeof result.current.dispatch).toBe('function');
    });
  });
});
