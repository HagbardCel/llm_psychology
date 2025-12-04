import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { ReactNode } from 'react';

/**
 * React Query client configuration
 * Provides caching, refetching, and error handling for server state
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes - data considered fresh for 5 min
      gcTime: 1000 * 60 * 10, // 10 minutes - cache kept in memory for 10 min
      refetchOnWindowFocus: true, // Refetch when user returns to tab
      refetchOnReconnect: true, // Refetch when internet reconnects
      retry: 1, // Retry failed requests once
    },
    mutations: {
      retry: 0, // Don't retry mutations by default
    },
  },
});

interface QueryProviderProps {
  children: ReactNode;
}

/**
 * QueryProvider wrapper component
 * Wraps the app with React Query client and dev tools
 */
export function QueryProvider({ children }: QueryProviderProps) {
  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}

// Export queryClient for use in tests and direct cache manipulation
export { queryClient };
