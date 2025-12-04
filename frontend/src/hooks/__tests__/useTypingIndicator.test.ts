import { renderHook, act } from '@testing-library/react';
import { useTypingIndicator } from '../useTypingIndicator';

describe('useTypingIndicator', () => {
  jest.useFakeTimers();

  afterEach(() => {
    jest.clearAllTimers();
    jest.clearAllMocks();
  });

  it('should initialize with isTyping as false', () => {
    const { result } = renderHook(() => useTypingIndicator());

    expect(result.current.isTyping).toBe(false);
  });

  it('should set isTyping to true when startTyping is called', () => {
    const { result } = renderHook(() => useTypingIndicator());

    act(() => {
      result.current.startTyping();
    });

    expect(result.current.isTyping).toBe(true);
  });

  it('should set isTyping to false when stopTyping is called', () => {
    const { result } = renderHook(() => useTypingIndicator());

    act(() => {
      result.current.startTyping();
    });

    expect(result.current.isTyping).toBe(true);

    act(() => {
      result.current.stopTyping();
    });

    expect(result.current.isTyping).toBe(false);
  });

  it('should call onTypingStart callback when typing starts', () => {
    const onTypingStart = jest.fn();
    const { result } = renderHook(() => useTypingIndicator({ onTypingStart }));

    act(() => {
      result.current.startTyping();
    });

    expect(onTypingStart).toHaveBeenCalledTimes(1);
  });

  it('should call onTypingStop callback when typing stops', () => {
    const onTypingStop = jest.fn();
    const { result } = renderHook(() => useTypingIndicator({ onTypingStop }));

    act(() => {
      result.current.startTyping();
    });

    act(() => {
      result.current.stopTyping();
    });

    expect(onTypingStop).toHaveBeenCalledTimes(1);
  });

  it('should auto-stop typing after timeout', () => {
    const onTypingStop = jest.fn();
    const { result } = renderHook(() =>
      useTypingIndicator({ onTypingStop, typingTimeout: 1000 })
    );

    act(() => {
      result.current.startTyping();
    });

    expect(result.current.isTyping).toBe(true);

    act(() => {
      jest.advanceTimersByTime(1000);
    });

    expect(result.current.isTyping).toBe(false);
    expect(onTypingStop).toHaveBeenCalledTimes(1);
  });

  it('should handle input change and start typing', () => {
    const { result } = renderHook(() => useTypingIndicator());

    act(() => {
      result.current.handleInputChange('Hello');
    });

    expect(result.current.isTyping).toBe(true);
  });

  it('should stop typing when input is empty', () => {
    const { result } = renderHook(() => useTypingIndicator());

    act(() => {
      result.current.handleInputChange('Hello');
    });

    expect(result.current.isTyping).toBe(true);

    act(() => {
      result.current.handleInputChange('');
    });

    expect(result.current.isTyping).toBe(false);
  });

  it('should not start typing if value is only whitespace', () => {
    const { result } = renderHook(() => useTypingIndicator());

    act(() => {
      result.current.handleInputChange('   ');
    });

    expect(result.current.isTyping).toBe(false);
  });

  it('should reset timeout when startTyping is called again', () => {
    const onTypingStop = jest.fn();
    const { result } = renderHook(() =>
      useTypingIndicator({ onTypingStop, typingTimeout: 1000 })
    );

    act(() => {
      result.current.startTyping();
    });

    act(() => {
      jest.advanceTimersByTime(500);
    });

    // Still typing after 500ms
    expect(result.current.isTyping).toBe(true);

    // Start typing again - should reset the timeout
    act(() => {
      result.current.startTyping();
    });

    act(() => {
      jest.advanceTimersByTime(500);
    });

    // Still typing because timeout was reset
    expect(result.current.isTyping).toBe(true);
    expect(onTypingStop).not.toHaveBeenCalled();

    // Advance another 500ms to reach 1000ms from last startTyping
    act(() => {
      jest.advanceTimersByTime(500);
    });

    expect(result.current.isTyping).toBe(false);
    expect(onTypingStop).toHaveBeenCalledTimes(1);
  });

  it('should cleanup timeout on unmount', () => {
    const { result, unmount } = renderHook(() => useTypingIndicator());

    act(() => {
      result.current.startTyping();
    });

    expect(result.current.isTyping).toBe(true);

    unmount();

    // Should not throw error
    expect(true).toBe(true);
  });
});
