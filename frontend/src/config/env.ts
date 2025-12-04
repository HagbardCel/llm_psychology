/**
 * Environment configuration
 * Handles environment variables in both Vite and Jest environments
 */

export const getApiBaseUrl = (): string => {
  // In Jest/test environment, always use localhost
  if (typeof process !== 'undefined' && process.env.NODE_ENV === 'test') {
    return 'http://localhost:8000';
  }

  // In Vite/browser environment, try to get from import.meta.env
  // We use eval to prevent Jest from trying to parse import.meta at all
  try {
    const getViteEnv = new Function('return typeof import !== "undefined" && import.meta && import.meta.env');
    const viteEnv = getViteEnv();
    if (viteEnv && viteEnv.VITE_API_URL) {
      return viteEnv.VITE_API_URL;
    }
  } catch {
    // Fallback if import.meta is not available
  }

  return 'http://localhost:8000';
};
