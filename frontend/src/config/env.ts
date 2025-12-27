/**
 * Environment configuration
 * Handles environment variables in both Vite and Jest environments
 */

declare const __VITE_API_URL__: string | undefined;
declare const __VITE_WS_URL__: string | undefined;

export const getApiBaseUrl = (): string => {
  // In Jest/test environment, always use localhost
  if (
    typeof window === 'undefined' &&
    typeof process !== 'undefined' &&
    process.env.NODE_ENV === 'test'
  ) {
    return 'http://localhost:8000';
  }

  if (typeof __VITE_API_URL__ !== 'undefined' && __VITE_API_URL__) {
    return __VITE_API_URL__;
  }

  return 'http://localhost:8000';
};

export const getWebSocketBaseUrl = (): string => {
  if (
    typeof window === 'undefined' &&
    typeof process !== 'undefined' &&
    process.env.NODE_ENV === 'test'
  ) {
    return 'ws://localhost:8000';
  }

  if (typeof __VITE_WS_URL__ !== 'undefined' && __VITE_WS_URL__) {
    return __VITE_WS_URL__;
  }

  return 'ws://localhost:8000';
};
