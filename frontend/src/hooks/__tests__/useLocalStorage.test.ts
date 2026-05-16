import { renderHook, act } from '@testing-library/react';
import { useLocalStorage, useLocalStorageValue } from '../useLocalStorage';

describe('useLocalStorage', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe('getItem', () => {
    it('should get item from localStorage', () => {
      localStorage.setItem('test-key', JSON.stringify({ value: 'test' }));

      const { result } = renderHook(() => useLocalStorage());
      const item = result.current.getItem<{ value: string }>('test-key');

      expect(item).toEqual({ value: 'test' });
    });

    it('should return null for non-existent key', () => {
      const { result } = renderHook(() => useLocalStorage());
      const item = result.current.getItem('non-existent');

      expect(item).toBeNull();
    });

    it('should return null and log error for invalid JSON', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      localStorage.setItem('invalid-json', 'not a json');

      const { result } = renderHook(() => useLocalStorage());
      const item = result.current.getItem('invalid-json');

      expect(item).toBeNull();
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Error getting item from localStorage with key "invalid-json"'),
        expect.any(Error)
      );

      consoleErrorSpy.mockRestore();
    });

    it('should handle complex objects', () => {
      const complexObject = {
        name: 'Test',
        nested: { value: 123 },
        array: [1, 2, 3],
      };
      localStorage.setItem('complex', JSON.stringify(complexObject));

      const { result } = renderHook(() => useLocalStorage());
      const item = result.current.getItem<typeof complexObject>('complex');

      expect(item).toEqual(complexObject);
    });
  });

  describe('setItem', () => {
    it('should set item in localStorage', () => {
      const { result } = renderHook(() => useLocalStorage());

      act(() => {
        result.current.setItem('test-key', { value: 'test' });
      });

      const stored = localStorage.getItem('test-key');
      expect(stored).toBe(JSON.stringify({ value: 'test' }));
    });

    it('should handle primitive values', () => {
      const { result } = renderHook(() => useLocalStorage());

      act(() => {
        result.current.setItem('string-key', 'test string');
        result.current.setItem('number-key', 42);
        result.current.setItem('boolean-key', true);
      });

      expect(localStorage.getItem('string-key')).toBe(JSON.stringify('test string'));
      expect(localStorage.getItem('number-key')).toBe(JSON.stringify(42));
      expect(localStorage.getItem('boolean-key')).toBe(JSON.stringify(true));
    });

    it('should handle arrays', () => {
      const { result } = renderHook(() => useLocalStorage());
      const testArray = [1, 2, 3, { nested: true }];

      act(() => {
        result.current.setItem('array-key', testArray);
      });

      expect(localStorage.getItem('array-key')).toBe(JSON.stringify(testArray));
    });

    it('should log error when localStorage.setItem throws', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      const mockError = new Error('Quota exceeded');
      vi.spyOn(localStorage, 'setItem').mockImplementationOnce(() => {
        throw mockError;
      });

      const { result } = renderHook(() => useLocalStorage());

      act(() => {
        result.current.setItem('test-key', 'value');
      });

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Error setting item in localStorage with key "test-key"'),
        mockError
      );

      consoleErrorSpy.mockRestore();
      vi.restoreAllMocks();
    });
  });

  describe('removeItem', () => {
    it('should remove item from localStorage', () => {
      localStorage.setItem('test-key', JSON.stringify('test'));

      const { result } = renderHook(() => useLocalStorage());

      act(() => {
        result.current.removeItem('test-key');
      });

      expect(localStorage.getItem('test-key')).toBeNull();
    });

    it('should not throw when removing non-existent key', () => {
      const { result } = renderHook(() => useLocalStorage());

      expect(() => {
        act(() => {
          result.current.removeItem('non-existent');
        });
      }).not.toThrow();
    });

    it('should log error when localStorage.removeItem throws', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      const mockError = new Error('Remove error');
      vi.spyOn(localStorage, 'removeItem').mockImplementationOnce(() => {
        throw mockError;
      });

      const { result } = renderHook(() => useLocalStorage());

      act(() => {
        result.current.removeItem('test-key');
      });

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Error removing item from localStorage with key "test-key"'),
        mockError
      );

      consoleErrorSpy.mockRestore();
      vi.restoreAllMocks();
    });
  });

  describe('clear', () => {
    it('should clear all items from localStorage', () => {
      localStorage.setItem('key1', 'value1');
      localStorage.setItem('key2', 'value2');
      localStorage.setItem('key3', 'value3');

      const { result } = renderHook(() => useLocalStorage());

      act(() => {
        result.current.clear();
      });

      expect(localStorage.length).toBe(0);
    });

    it('should log error when localStorage.clear throws', () => {
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
      const mockError = new Error('Clear error');
      vi.spyOn(localStorage, 'clear').mockImplementationOnce(() => {
        throw mockError;
      });

      const { result } = renderHook(() => useLocalStorage());

      act(() => {
        result.current.clear();
      });

      expect(consoleErrorSpy).toHaveBeenCalledWith(
        'Error clearing localStorage:',
        mockError
      );

      consoleErrorSpy.mockRestore();
      vi.restoreAllMocks();
    });
  });
});

describe('useLocalStorageValue', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('should initialize with value from localStorage if exists', () => {
    localStorage.setItem('test-key', JSON.stringify('stored value'));

    const { result } = renderHook(() =>
      useLocalStorageValue('test-key', 'initial value')
    );

    expect(result.current[0]).toBe('stored value');
  });

  it('should initialize with initial value if localStorage is empty', () => {
    const { result } = renderHook(() =>
      useLocalStorageValue('test-key', 'initial value')
    );

    expect(result.current[0]).toBe('initial value');
  });

  it('should update value in state and localStorage', () => {
    const { result } = renderHook(() =>
      useLocalStorageValue('test-key', 'initial')
    );

    act(() => {
      result.current[1]('new value');
    });

    expect(result.current[0]).toBe('new value');
    expect(localStorage.getItem('test-key')).toBe(JSON.stringify('new value'));
  });

  it('should handle function updater', () => {
    const { result } = renderHook(() =>
      useLocalStorageValue('counter', 0)
    );

    act(() => {
      result.current[1]((prev) => prev + 1);
    });

    expect(result.current[0]).toBe(1);
    expect(localStorage.getItem('counter')).toBe(JSON.stringify(1));
  });

  it('should handle object values', () => {
    interface TestObject {
      name: string;
      count: number;
    }

    const initialObject: TestObject = { name: 'test', count: 0 };
    const { result } = renderHook(() =>
      useLocalStorageValue('object-key', initialObject)
    );

    const updatedObject: TestObject = { name: 'updated', count: 5 };

    act(() => {
      result.current[1](updatedObject);
    });

    expect(result.current[0]).toEqual(updatedObject);
    expect(localStorage.getItem('object-key')).toBe(JSON.stringify(updatedObject));
  });

  it('should log error when setValue throws', () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const mockError = new Error('Set error');

    // Mock setItem in the useLocalStorage hook
    vi.spyOn(localStorage, 'setItem').mockImplementationOnce(() => {
      throw mockError;
    });

    const { result } = renderHook(() =>
      useLocalStorageValue('test-key', 'initial')
    );

    act(() => {
      result.current[1]('new value');
    });

    expect(consoleErrorSpy).toHaveBeenCalled();

    consoleErrorSpy.mockRestore();
    vi.restoreAllMocks();
  });
});
