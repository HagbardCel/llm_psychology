/**
 * React hook for managing typing indicators
 */

import { useCallback, useEffect, useRef, useState } from 'react';

interface UseTypingIndicatorOptions {
  onTypingStart?: () => void;
  onTypingStop?: () => void;
  typingTimeout?: number;
}

interface UseTypingIndicatorReturn {
  isTyping: boolean;
  startTyping: () => void;
  stopTyping: () => void;
  handleInputChange: (value: string) => void;
}

export const useTypingIndicator = (options: UseTypingIndicatorOptions = {}): UseTypingIndicatorReturn => {
  const {
    onTypingStart,
    onTypingStop,
    typingTimeout = 1000
  } = options;

  const [isTyping, setIsTyping] = useState(false);
  const typingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastValueRef = useRef<string>('');

  const startTyping = useCallback(() => {
    if (!isTyping) {
      setIsTyping(true);
      onTypingStart?.();
    }

    // Clear existing timeout
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
    }

    // Set new timeout to stop typing
    typingTimeoutRef.current = setTimeout(() => {
      setIsTyping(false);
      onTypingStop?.();
      typingTimeoutRef.current = null;
    }, typingTimeout);
  }, [isTyping, onTypingStart, onTypingStop, typingTimeout]);

  const stopTyping = useCallback(() => {
    if (typingTimeoutRef.current) {
      clearTimeout(typingTimeoutRef.current);
      typingTimeoutRef.current = null;
    }

    if (isTyping) {
      setIsTyping(false);
      onTypingStop?.();
    }
  }, [isTyping, onTypingStop]);

  const handleInputChange = useCallback((value: string) => {
    const trimmedValue = value.trim();
    const lastValue = lastValueRef.current;

    // Update last value
    lastValueRef.current = value;

    // If user is typing (value is not empty and different from last)
    if (trimmedValue && trimmedValue !== lastValue.trim()) {
      startTyping();
    } else if (!trimmedValue) {
      // If input is empty, stop typing
      stopTyping();
    }
  }, [startTyping, stopTyping]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (typingTimeoutRef.current) {
        clearTimeout(typingTimeoutRef.current);
      }
    };
  }, []);

  return {
    isTyping,
    startTyping,
    stopTyping,
    handleInputChange
  };
};