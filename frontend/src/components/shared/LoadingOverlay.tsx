import { Box, CircularProgress, Typography } from '@mui/material';

export interface LoadingOverlayProps {
  message?: string;
  fullScreen?: boolean;
}

/**
 * LoadingOverlay displays a centered loading spinner with optional message.
 *
 * @example
 * ```tsx
 * <LoadingOverlay message="Preparing your session..." fullScreen />
 * ```
 */
export function LoadingOverlay({
  message = 'Loading...',
  fullScreen = false
}: LoadingOverlayProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: fullScreen ? '100vh' : '400px',
        gap: 2
      }}
    >
      <CircularProgress />
      <Typography variant="body2" color="text.secondary">
        {message}
      </Typography>
    </Box>
  );
}
