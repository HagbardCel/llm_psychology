import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import type { User, Session, TherapyPlan } from '../types';

/**
 * DEPRECATED: Legacy state interface for backward compatibility
 * New components should use React Query hooks instead
 */
interface LegacyAppState {
  user: User | null;
  currentSession: Session | null;
  sessions: Session[];
  therapyPlan: TherapyPlan | null;
}

/**
 * DEPRECATED: Legacy actions interface for backward compatibility
 * New components should use React Query mutations instead
 */
interface LegacyAppActions {
  updateSession: (session: Session) => void;
  setCurrentSession: (session: Session | null) => void;
}

/**
 * UI-only state for the application
 * Business data (user, sessions, therapy plan) now managed by React Query
 */
interface AppContextType {
  // UI Preferences (persisted in localStorage)
  theme: 'light' | 'dark';
  setTheme: (theme: 'light' | 'dark') => void;

  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;

  // Current user ID (stored in localStorage for persistence)
  currentUserId: string | null;
  setCurrentUserId: (userId: string | null) => void;

  // Current session ID (stored in localStorage for persistence)
  currentSessionId: string | null;
  setCurrentSessionId: (sessionId: string | null) => void;

  // DEPRECATED: Legacy compatibility layer for components not yet refactored
  // These will be removed in a future release
  state: LegacyAppState;
  actions: LegacyAppActions;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

interface AppProviderProps {
  children: ReactNode;
}

/**
 * Simplified AppProvider - only manages UI state
 * All business data (user profiles, sessions, therapy plans) is now
 * managed by React Query hooks in individual components
 */
export function AppProvider({ children }: AppProviderProps) {
  // Theme preference (persisted in localStorage)
  const [theme, setThemeState] = useState<'light' | 'dark'>(() => {
    const stored = localStorage.getItem('theme');
    return (stored === 'light' || stored === 'dark') ? stored : 'light';
  });

  // Sidebar state (persisted in localStorage)
  const [sidebarOpen, setSidebarOpenState] = useState(() => {
    const stored = localStorage.getItem('sidebarOpen');
    return stored !== null ? stored === 'true' : true;
  });

  // Current user ID (persisted in localStorage)
  const [currentUserId, setCurrentUserIdState] = useState<string | null>(() => {
    const existing = localStorage.getItem('current_user_id');
    if (existing) {
      return existing;
    }

    const generated =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `user_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    localStorage.setItem('current_user_id', generated);
    return generated;
  });

  const [currentSessionId, setCurrentSessionIdState] = useState<string | null>(() => {
    const existing = localStorage.getItem('current_session_id');
    return existing || null;
  });

  // Persist theme changes
  useEffect(() => {
    localStorage.setItem('theme', theme);
    // Apply theme to document for CSS variables
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Persist sidebar state changes
  useEffect(() => {
    localStorage.setItem('sidebarOpen', sidebarOpen.toString());
  }, [sidebarOpen]);

  // Persist current user ID changes
  useEffect(() => {
    if (currentUserId) {
      localStorage.setItem('current_user_id', currentUserId);
    } else {
      localStorage.removeItem('current_user_id');
    }
  }, [currentUserId]);

  useEffect(() => {
    if (currentSessionId) {
      localStorage.setItem('current_session_id', currentSessionId);
    } else {
      localStorage.removeItem('current_session_id');
    }
  }, [currentSessionId]);

  const setTheme = (newTheme: 'light' | 'dark') => {
    setThemeState(newTheme);
  };

  const setSidebarOpen = (open: boolean) => {
    setSidebarOpenState(open);
  };

  const setCurrentUserId = (userId: string | null) => {
    setCurrentUserIdState(userId);
  };

  const setCurrentSessionId = (sessionId: string | null) => {
    setCurrentSessionIdState(sessionId);
  };

  // DEPRECATED: Legacy state for backward compatibility
  const legacyState: LegacyAppState = {
    user: null, // Components should use useUserProfile hook instead
    currentSession: null, // Components should manage session state locally
    sessions: [], // Components should use useSessionHistory hook instead
    therapyPlan: null, // Components should use useTherapyPlan hook instead
  };

  // DEPRECATED: Legacy actions for backward compatibility
  const legacyActions: LegacyAppActions = {
    updateSession: (_session: Session) => {
      console.warn('DEPRECATED: updateSession called. Components should use React Query mutations.');
      // No-op: This is a compatibility shim only
    },
    setCurrentSession: (_session: Session | null) => {
      console.warn('DEPRECATED: setCurrentSession called. Components should manage local state.');
      // No-op: This is a compatibility shim only
    },
  };

  return (
    <AppContext.Provider
      value={{
        theme,
        setTheme,
        sidebarOpen,
        setSidebarOpen,
        currentUserId,
        setCurrentUserId,
        currentSessionId,
        setCurrentSessionId,
        state: legacyState,
        actions: legacyActions,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

/**
 * Hook to access app context
 * @throws {Error} if used outside AppProvider
 */
export function useAppContext() {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useAppContext must be used within an AppProvider');
  }
  return context;
}

/**
 * Utility hook to get current user ID
 * Convenience wrapper around useAppContext
 */
export function useCurrentUserId(): string | null {
  const { currentUserId } = useAppContext();
  return currentUserId;
}

export function useCurrentSessionId(): string | null {
  const { currentSessionId } = useAppContext();
  return currentSessionId;
}
