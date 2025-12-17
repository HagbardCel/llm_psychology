import { renderHook, act, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

import { AppProvider, useAppContext } from '../AppContext';

let mockAuthState: any = {
  token: 'test-token',
  user: { userId: 'test-user-id', username: 'test-user' },
  isAuthenticated: true,
  isLoading: false,
};

jest.mock('../AuthContext', () => ({
  useAuth: () => mockAuthState,
}));

describe('AppContext', () => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <AppProvider>{children}</AppProvider>
  );

  beforeEach(() => {
    jest.clearAllMocks();

    mockAuthState = {
      token: 'test-token',
      user: { userId: 'test-user-id', username: 'test-user' },
      isAuthenticated: true,
      isLoading: false,
    };

    const originalGetItem = Storage.prototype.getItem;
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(function (key: string) {
      if (key === 'theme') return null;
      if (key === 'sidebarOpen') return null;
      if (key === 'current_user_id') return null;
      return originalGetItem.call(this, key);
    });

    const originalSetItem = Storage.prototype.setItem;
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (key: string, value: string) {
      return originalSetItem.call(this, key, value);
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('throws if used outside provider', () => {
    expect(() => renderHook(() => useAppContext())).toThrow(
      'useAppContext must be used within an AppProvider'
    );
  });

  it('initializes theme and persists changes', async () => {
    const { result } = renderHook(() => useAppContext(), { wrapper });

    expect(result.current.theme).toBe('light');

    act(() => {
      result.current.setTheme('dark');
    });

    await waitFor(() => {
      expect(localStorage.setItem).toHaveBeenCalledWith('theme', 'dark');
    });
  });

  it('initializes sidebarOpen and persists changes', async () => {
    const { result } = renderHook(() => useAppContext(), { wrapper });

    expect(typeof result.current.sidebarOpen).toBe('boolean');

    act(() => {
      result.current.setSidebarOpen(false);
    });

    await waitFor(() => {
      expect(localStorage.setItem).toHaveBeenCalledWith('sidebarOpen', 'false');
    });
  });

  it('syncs currentUserId from AuthContext', async () => {
    const { result } = renderHook(() => useAppContext(), { wrapper });

    await waitFor(() => {
      expect(result.current.currentUserId).toBe('test-user-id');
    });
  });

  it('clears currentUserId when unauthenticated', async () => {
    const { result, rerender } = renderHook(() => useAppContext(), { wrapper });

    await waitFor(() => {
      expect(result.current.currentUserId).toBe('test-user-id');
    });

    mockAuthState = {
      token: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
    };
    rerender();

    await waitFor(() => {
      expect(result.current.currentUserId).toBeNull();
    });
  });
});
