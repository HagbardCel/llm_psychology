import { useState, useCallback } from 'react';

interface UseLocalStorageReturn {
  getItem: <T>(key: string) => T | null;
  setItem: <T>(key: string, value: T) => void;
  removeItem: (key: string) => void;
  clear: () => void;
}

export function useLocalStorage(): UseLocalStorageReturn {
  const [, setStorageState] = useState({});

  const getItem = useCallback(<T>(key: string): T | null => {
    try {
      if (typeof window === 'undefined') {
        return null;
      }
      
      const item = window.localStorage.getItem(key);
      if (item === null) {
        return null;
      }
      
      return JSON.parse(item) as T;
    } catch (error) {
      console.error(`Error getting item from localStorage with key "${key}":`, error);
      return null;
    }
  }, []);

  const setItem = useCallback(<T>(key: string, value: T): void => {
    try {
      if (typeof window === 'undefined') {
        return;
      }
      
      window.localStorage.setItem(key, JSON.stringify(value));
      setStorageState(prev => ({ ...prev, [key]: value }));
    } catch (error) {
      console.error(`Error setting item in localStorage with key "${key}":`, error);
    }
  }, []);

  const removeItem = useCallback((key: string): void => {
    try {
      if (typeof window === 'undefined') {
        return;
      }
      
      window.localStorage.removeItem(key);
      setStorageState(prev => {
        const newState = { ...prev } as Record<string, any>;
        delete newState[key];
        return newState;
      });
    } catch (error) {
      console.error(`Error removing item from localStorage with key "${key}":`, error);
    }
  }, []);

  const clear = useCallback((): void => {
    try {
      if (typeof window === 'undefined') {
        return;
      }
      
      window.localStorage.clear();
      setStorageState({});
    } catch (error) {
      console.error('Error clearing localStorage:', error);
    }
  }, []);

  return {
    getItem,
    setItem,
    removeItem,
    clear,
  };
}

// Hook for specific localStorage keys with type safety
export function useLocalStorageValue<T>(
  key: string,
  initialValue: T
): [T, (value: T | ((prev: T) => T)) => void] {
  const { getItem, setItem } = useLocalStorage();
  
  const [storedValue, setStoredValue] = useState<T>(() => {
    const item = getItem<T>(key);
    return item !== null ? item : initialValue;
  });

  const setValue = useCallback((value: T | ((prev: T) => T)) => {
    try {
      const valueToStore = value instanceof Function ? value(storedValue) : value;
      setStoredValue(valueToStore);
      setItem(key, valueToStore);
    } catch (error) {
      console.error(`Error setting localStorage value for key "${key}":`, error);
    }
  }, [key, setItem, storedValue]);

  return [storedValue, setValue];
}