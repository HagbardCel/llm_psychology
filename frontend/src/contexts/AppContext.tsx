import React, { createContext, useContext, useReducer, useEffect, ReactNode } from 'react';
import { AppState, User, Session, TherapyPlan } from '../types';
import { useLocalStorage } from '../hooks/useLocalStorage';

type AppAction =
  | { type: 'SET_USER'; payload: User | null }
  | { type: 'SET_CURRENT_SESSION'; payload: Session | null }
  | { type: 'ADD_SESSION'; payload: Session }
  | { type: 'UPDATE_SESSION'; payload: Session }
  | { type: 'SET_SESSIONS'; payload: Session[] }
  | { type: 'SET_THERAPY_PLAN'; payload: TherapyPlan | null }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'CLEAR_ERROR' };

const initialState: AppState = {
  user: null,
  currentSession: null,
  sessions: [],
  therapyPlan: null,
  isLoading: false,
  error: null,
};

function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_USER':
      return { ...state, user: action.payload };
    case 'SET_CURRENT_SESSION':
      return { ...state, currentSession: action.payload };
    case 'ADD_SESSION':
      return { 
        ...state, 
        sessions: [...state.sessions, action.payload],
        currentSession: action.payload
      };
    case 'UPDATE_SESSION':
      return {
        ...state,
        sessions: state.sessions.map(session =>
          session.id === action.payload.id ? action.payload : session
        ),
        currentSession: state.currentSession?.id === action.payload.id 
          ? action.payload 
          : state.currentSession
      };
    case 'SET_SESSIONS':
      return { ...state, sessions: action.payload };
    case 'SET_THERAPY_PLAN':
      return { ...state, therapyPlan: action.payload };
    case 'SET_LOADING':
      return { ...state, isLoading: action.payload };
    case 'SET_ERROR':
      return { ...state, error: action.payload, isLoading: false };
    case 'CLEAR_ERROR':
      return { ...state, error: null };
    default:
      return state;
  }
}

interface AppContextType {
  state: AppState;
  dispatch: React.Dispatch<AppAction>;
  actions: {
    setUser: (user: User | null) => void;
    setCurrentSession: (session: Session | null) => void;
    addSession: (session: Session) => void;
    updateSession: (session: Session) => void;
    setSessions: (sessions: Session[]) => void;
    setTherapyPlan: (plan: TherapyPlan | null) => void;
    setLoading: (loading: boolean) => void;
    setError: (error: string | null) => void;
    clearError: () => void;
  };
}

const AppContext = createContext<AppContextType | undefined>(undefined);

interface AppProviderProps {
  children: ReactNode;
}

export function AppProvider({ children }: AppProviderProps) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  const { getItem, setItem } = useLocalStorage();

  // Load initial data from localStorage
  useEffect(() => {
    const loadStoredData = async () => {
      try {
        dispatch({ type: 'SET_LOADING', payload: true });
        
        const storedUser = getItem<User>('user');
        const storedSessions = getItem<Session[]>('sessions') || [];
        const storedTherapyPlan = getItem<TherapyPlan>('therapyPlan');

        if (storedUser) {
          dispatch({ type: 'SET_USER', payload: storedUser });
        }
        
        dispatch({ type: 'SET_SESSIONS', payload: storedSessions });
        
        if (storedTherapyPlan) {
          dispatch({ type: 'SET_THERAPY_PLAN', payload: storedTherapyPlan });
        }

        // Find most recent active session
        const activeSession = storedSessions.find(s => s.status === 'ACTIVE');
        if (activeSession) {
          dispatch({ type: 'SET_CURRENT_SESSION', payload: activeSession });
        }
        
      } catch (error) {
        console.error('Error loading stored data:', error);
        dispatch({ type: 'SET_ERROR', payload: 'Failed to load stored data' });
      } finally {
        dispatch({ type: 'SET_LOADING', payload: false });
      }
    };

    loadStoredData();
  }, [getItem]);

  // Save data to localStorage when state changes
  useEffect(() => {
    if (state.user) {
      setItem('user', state.user);
    }
  }, [state.user, setItem]);

  useEffect(() => {
    if (state.sessions.length > 0) {
      setItem('sessions', state.sessions);
    }
  }, [state.sessions, setItem]);

  useEffect(() => {
    if (state.therapyPlan) {
      setItem('therapyPlan', state.therapyPlan);
    }
  }, [state.therapyPlan, setItem]);

  const actions = {
    setUser: (user: User | null) => dispatch({ type: 'SET_USER', payload: user }),
    setCurrentSession: (session: Session | null) => dispatch({ type: 'SET_CURRENT_SESSION', payload: session }),
    addSession: (session: Session) => dispatch({ type: 'ADD_SESSION', payload: session }),
    updateSession: (session: Session) => dispatch({ type: 'UPDATE_SESSION', payload: session }),
    setSessions: (sessions: Session[]) => dispatch({ type: 'SET_SESSIONS', payload: sessions }),
    setTherapyPlan: (plan: TherapyPlan | null) => dispatch({ type: 'SET_THERAPY_PLAN', payload: plan }),
    setLoading: (loading: boolean) => dispatch({ type: 'SET_LOADING', payload: loading }),
    setError: (error: string | null) => dispatch({ type: 'SET_ERROR', payload: error }),
    clearError: () => dispatch({ type: 'CLEAR_ERROR' }),
  };

  return (
    <AppContext.Provider value={{ state, dispatch, actions }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error('useAppContext must be used within an AppProvider');
  }
  return context;
}