import { useState } from 'react';
import {
  Card,
  CardContent,
  Typography,
  Button,
  FormControl,
  FormLabel,
  RadioGroup,
  FormControlLabel,
  Radio,
  Box,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Alert,
  CircularProgress
} from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import DeleteIcon from '@mui/icons-material/Delete';
import WarningIcon from '@mui/icons-material/Warning';
import { PageContainer } from '../components/shared';
import { useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useUserProfile } from '../hooks/useUserProfile';
import { useSessionHistory } from '../hooks/useSessionHistory';
import { useTherapyPlan } from '../hooks/useTherapyPlan';
import { UserStatus } from '../types';

/**
 * SettingsPage allows users to manage their preferences and data.
 * Includes theme, font size, data export, and progress reset features.
 */
export function SettingsPage() {
  const userId = useCurrentUserId();
  const sessionId = useCurrentSessionId();
  const { data: user } = useUserProfile(userId || '', sessionId || '');
  const { data: sessions } = useSessionHistory(userId || '', sessionId || '');
  const { data: therapyPlan } = useTherapyPlan(userId || '', sessionId || '');

  const [themeMode, setThemeMode] = useState<'light' | 'dark'>(
    (localStorage.getItem('theme') as 'light' | 'dark') || 'light'
  );
  const [fontSize, setFontSize] = useState<'small' | 'medium' | 'large'>(
    (localStorage.getItem('fontSize') as 'small' | 'medium' | 'large') ||
      'medium'
  );

  // Danger zone state
  const [showResetDialog, setShowResetDialog] = useState(false);
  const [resetConfirmText, setResetConfirmText] = useState('');
  const [isResetting, setIsResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resetAvailable = false;

  const handleThemeChange = (newTheme: 'light' | 'dark') => {
    setThemeMode(newTheme);
    localStorage.setItem('theme', newTheme);
    // Emit event for global theme update
    window.dispatchEvent(new CustomEvent('theme-change', { detail: newTheme }));
  };

  const handleFontSizeChange = (newSize: 'small' | 'medium' | 'large') => {
    setFontSize(newSize);
    localStorage.setItem('fontSize', newSize);
  };

  const handleExportData = () => {
    const data = {
      user: user,
      sessions: sessions || [],
      therapyPlan: therapyPlan || null,
      exportedAt: new Date().toISOString()
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: 'application/json'
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `therapy-data-${user?.user_id}-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleResetProgress = async () => {
    if (!user) return;

    if (!resetAvailable) {
      setError('Reset progress is not available in this build.');
      return;
    }

    // Validation: Must type "RESET" exactly
    if (resetConfirmText !== 'RESET') {
      setError('Please type RESET to confirm');
      return;
    }

    setIsResetting(true);
    setError(null);

    try {
      setError('Reset progress is not available in this build.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset progress');
      console.error('Reset progress error:', err);
    } finally {
      setIsResetting(false);
      setShowResetDialog(false);
      setResetConfirmText('');
    }
  };

  const deletionPreview = {
    sessions: sessions?.length || 0,
    therapyPlan: therapyPlan ? 1 : 0,
    status: user?.status || UserStatus.PROFILE_ONLY
  };

  return (
    <PageContainer title="Settings" subtitle="Manage your preferences" maxWidth="md">
      {!sessionId && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          No active session found. Please reconnect to manage your data.
        </Alert>
      )}
      {/* Theme Settings */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Appearance
          </Typography>

          <FormControl component="fieldset" sx={{ mt: 2 }}>
            <FormLabel component="legend">Theme</FormLabel>
            <RadioGroup
              row
              value={themeMode}
              onChange={(e) =>
                handleThemeChange(e.target.value as 'light' | 'dark')
              }
            >
              <FormControlLabel value="light" control={<Radio />} label="Light" />
              <FormControlLabel value="dark" control={<Radio />} label="Dark" />
            </RadioGroup>
          </FormControl>

          <FormControl component="fieldset" sx={{ mt: 3 }}>
            <FormLabel component="legend">Font Size</FormLabel>
            <RadioGroup
              row
              value={fontSize}
              onChange={(e) =>
                handleFontSizeChange(
                  e.target.value as 'small' | 'medium' | 'large'
                )
              }
            >
              <FormControlLabel value="small" control={<Radio />} label="Small" />
              <FormControlLabel value="medium" control={<Radio />} label="Medium" />
              <FormControlLabel value="large" control={<Radio />} label="Large" />
            </RadioGroup>
          </FormControl>
        </CardContent>
      </Card>

      {/* Data Management */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Data Management
          </Typography>

          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={handleExportData}
            sx={{ mt: 2 }}
          >
            Export My Data
          </Button>
          <Typography variant="caption" display="block" sx={{ mt: 1 }}>
            Download all your sessions and therapy data as JSON
          </Typography>
        </CardContent>
      </Card>

      {/* Danger Zone */}
      <Card
        sx={{
          mb: 3,
          borderColor: 'error.main',
          borderWidth: 2,
          borderStyle: 'solid'
        }}
      >
        <CardContent>
          <Box display="flex" alignItems="center" gap={1} mb={2}>
            <WarningIcon color="error" />
            <Typography variant="h6" color="error">
              Danger Zone
            </Typography>
          </Box>

          <Typography variant="body2" paragraph>
            Resetting your progress will permanently delete:
          </Typography>

          <Box component="ul" sx={{ pl: 3 }}>
            <li>All {deletionPreview.sessions} therapy sessions</li>
            <li>
              {deletionPreview.therapyPlan
                ? 'Your therapy plan'
                : 'No therapy plan (already empty)'}
            </li>
            <li>Progress status (will reset to Profile Only)</li>
          </Box>

          <Typography variant="body2" paragraph sx={{ mt: 2 }}>
            <strong>Your user profile will NOT be deleted.</strong>
          </Typography>

          <Button
            variant="contained"
            color="error"
            startIcon={<DeleteIcon />}
            onClick={() => setShowResetDialog(true)}
            disabled={!resetAvailable}
            sx={{ mt: 2 }}
          >
            Reset Progress
          </Button>
          {!resetAvailable && (
            <Alert severity="info" sx={{ mt: 2 }}>
              Progress reset is not yet available. Your data remains unchanged.
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Reset Confirmation Dialog */}
      <Dialog
        open={showResetDialog}
        onClose={() => !isResetting && setShowResetDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          <Box display="flex" alignItems="center" gap={1}>
            <WarningIcon color="error" />
            Are you absolutely sure?
          </Box>
        </DialogTitle>
        <DialogContent>
          <Alert severity="error" sx={{ mb: 2 }}>
            This action cannot be undone. All your progress will be permanently
            deleted.
          </Alert>

          <Typography variant="body2" paragraph>
            You will lose:
          </Typography>
          <Box component="ul" sx={{ pl: 3, mb: 2 }}>
            <li>
              <strong>{deletionPreview.sessions}</strong> therapy sessions
            </li>
            <li>
              <strong>{deletionPreview.therapyPlan ? '1' : '0'}</strong> therapy
              plan
            </li>
            <li>
              Current status: <strong>{deletionPreview.status}</strong>
            </li>
          </Box>

          <Typography variant="body2" paragraph>
            Type <strong>RESET</strong> to confirm:
          </Typography>

          <TextField
            fullWidth
            value={resetConfirmText}
            onChange={(e) => setResetConfirmText(e.target.value)}
            placeholder="Type RESET"
            error={Boolean(error)}
            helperText={error}
            disabled={isResetting}
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowResetDialog(false)} disabled={isResetting}>
            Cancel
          </Button>
          <Button
            onClick={handleResetProgress}
            color="error"
            variant="contained"
            disabled={isResetting || resetConfirmText !== 'RESET'}
          >
            {isResetting ? (
              <CircularProgress size={24} />
            ) : (
              'Reset My Progress'
            )}
          </Button>
        </DialogActions>
      </Dialog>
    </PageContainer>
  );
}
