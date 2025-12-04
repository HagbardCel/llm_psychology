import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Alert,
  AlertTitle,
  Typography,
  Box,
  CircularProgress,
} from '@mui/material';
import { performVersionCheck, CLIENT_VERSION } from '../services/versionService';

interface VersionCheckProps {
  /** Base URL for backend API (optional, defaults to same origin) */
  baseUrl?: string;
  /** Callback when version check completes */
  onCheckComplete?: (compatible: boolean) => void;
}

/**
 * VersionCheck component
 *
 * Performs version compatibility check with backend on mount and displays
 * appropriate UI based on the result (error dialog, warning banner, or nothing).
 */
export function VersionCheck({ baseUrl = '', onCheckComplete }: VersionCheckProps) {
  const [checking, setChecking] = useState(true);
  const [compatible, setCompatible] = useState(true);
  const [message, setMessage] = useState('');
  const [severity, setSeverity] = useState<'error' | 'warning' | 'info'>('info');
  const [showDialog, setShowDialog] = useState(false);

  useEffect(() => {
    const checkVersion = async () => {
      setChecking(true);
      const result = await performVersionCheck(baseUrl);

      setCompatible(result.compatible);
      setMessage(result.message);
      setSeverity(result.severity);

      // Show dialog for errors (incompatible versions)
      if (!result.compatible) {
        setShowDialog(true);
      }

      setChecking(false);
      onCheckComplete?.(result.compatible);
    };

    checkVersion();
  }, [baseUrl, onCheckComplete]);

  // Show loading indicator while checking
  if (checking) {
    return (
      <Box
        sx={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          zIndex: 9999,
        }}
      >
        <Box sx={{ textAlign: 'center', color: 'white' }}>
          <CircularProgress color="inherit" size={60} />
          <Typography variant="h6" sx={{ mt: 2 }}>
            Checking version compatibility...
          </Typography>
        </Box>
      </Box>
    );
  }

  // Show error dialog for incompatible versions
  if (!compatible && showDialog) {
    return (
      <Dialog
        open={showDialog}
        disableEscapeKeyDown
        aria-labelledby="version-error-dialog-title"
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle id="version-error-dialog-title">Version Compatibility Error</DialogTitle>
        <DialogContent>
          <Alert severity="error" sx={{ mb: 2 }}>
            <AlertTitle>Incompatible Version</AlertTitle>
            {message}
          </Alert>

          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            Your web client version: <strong>v{CLIENT_VERSION}</strong>
          </Typography>

          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            Please refresh the page or clear your browser cache to get the latest version.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => window.location.reload()}
            color="primary"
            variant="contained"
            autoFocus
          >
            Refresh Page
          </Button>
        </DialogActions>
      </Dialog>
    );
  }

  // Show warning banner for outdated but compatible versions
  if (compatible && severity === 'warning') {
    return (
      <Alert
        severity="warning"
        onClose={() => setMessage('')}
        sx={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 9998,
          borderRadius: 0,
        }}
      >
        <AlertTitle>Update Available</AlertTitle>
        {message} Consider refreshing your browser to get the latest version.
      </Alert>
    );
  }

  // No UI needed for compatible versions without warnings
  return null;
}
