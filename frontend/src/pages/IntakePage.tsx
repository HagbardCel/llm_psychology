import { Alert } from '@mui/material';
import { PageContainer, LoadingOverlay } from '../components/shared';
import { TherapySession } from '../components/TherapySession';
import { useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useUserProfile } from '../hooks/useUserProfile';

/**
 * IntakePage renders the intake agent session.
 * The WorkflowGate ensures users land here only when appropriate.
 */
export function IntakePage() {
  const userId = useCurrentUserId();
  const sessionId = useCurrentSessionId();
  const { isLoading, error } = useUserProfile(userId || '', sessionId || '');

  if (isLoading) {
    return <LoadingOverlay message="Preparing your intake session..." fullScreen />;
  }

  return (
    <PageContainer
      title="Intake Assessment"
      subtitle="Tell me about what brings you here today"
      maxWidth="lg"
    >
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error instanceof Error ? error.message : 'Failed to load your profile. Reload the page to try again.'}
        </Alert>
      )}
      {!sessionId && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          No active session found. Please reconnect to begin intake.
        </Alert>
      )}
      <TherapySession />
    </PageContainer>
  );
}
