import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

/**
 * Authentication context for managing user authentication state
 */
interface AuthContextType {
  // Authentication state
  token: string | null;
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;

  // Authentication actions
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, name: string) => Promise<void>;
  logout: () => void;
}

interface AuthUser {
  userId: string;
  username: string;
  name?: string;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
}

/**
 * AuthProvider component that wraps the app and provides authentication context
 */
export function AuthProvider({ children }: AuthProviderProps) {
  const [token, setToken] = useState<string | null>(() => {
    // Load token from sessionStorage on mount
    return sessionStorage.getItem('auth_token');
  });

  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load user profile when token changes
  useEffect(() => {
    if (token) {
      loadUserProfile(token);
    } else {
      setUser(null);
      setIsLoading(false);
    }
  }, [token]);

  const loadUserProfile = async (authToken: string) => {
    try {
      setIsLoading(true);

      // Decode JWT to get user info (simple base64 decode without verification)
      const payloadPart = authToken.split('.')[1];
      const padding = payloadPart.length % 4;
      const paddedPayload = padding ? payloadPart + '='.repeat(4 - padding) : payloadPart;
      const payload = JSON.parse(atob(paddedPayload));

      setUser({
        userId: payload.user_id,
        username: payload.username,
      });
    } catch (error) {
      console.error('Failed to load user profile:', error);
      // Invalid token, clear it
      setToken(null);
      sessionStorage.removeItem('auth_token');
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (username: string, password: string) => {
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

    const response = await fetch(`${apiUrl}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Login failed');
    }

    const data = await response.json();
    const newToken = data.access_token;

    // Save token
    setToken(newToken);
    sessionStorage.setItem('auth_token', newToken);
  };

  const register = async (username: string, password: string, name: string) => {
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

    const response = await fetch(`${apiUrl}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, password, name }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Registration failed');
    }

    const data = await response.json();
    const newToken = data.access_token;

    // Save token
    setToken(newToken);
    sessionStorage.setItem('auth_token', newToken);
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    sessionStorage.removeItem('auth_token');
    sessionStorage.removeItem('current_user_id');
  };

  const value = {
    token,
    user,
    isAuthenticated: !!token && !!user,
    isLoading,
    login,
    register,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Hook to access authentication context
 * @throws {Error} if used outside AuthProvider
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
