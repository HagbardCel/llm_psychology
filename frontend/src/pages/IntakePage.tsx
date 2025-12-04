import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, AlertTitle, Button } from '@mui/material';
import { PageContainer, LoadingOverlay } from '../components/shared';
import { TherapySession } from '../components/TherapySession';
import { useCurrentUserId } from '../contexts/AppContext';
import { useAuth } from '../contexts/AuthContext';
import { useUserProfile } from '../hooks/useUserProfile';
import { useWebSocket } from '../hooks/useWebSocket';
import { UserStatus } from '../types';

/**
 * IntakePage provides the interface for the intake assessment.
 * Uses the TherapySession component with the Intake agent.
 */
export function IntakePage() {
  const userId = useCurrentUserId();
  const { token, user: authUser } = useAuth();
  const { data: user, isLoading: userLoading } = useUserProfile(userId || '');
  const navigate = useNavigate();
  const { requestSession } = useWebSocket({
    userId: authUser?.userId || userId || '',
    authToken: token || ''
  });
  const [isSessionReady, setIsSessionReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (userLoading || !user) return;

    const initIntakeSession = async () => {
      try {
        // Verify user is in intake phase
        if (user.status !== UserStatus.INTAKE_IN_PROGRESS) {
          console.warn(
            `User status is ${user.status}, but IntakePage expects INTAKE_IN_PROGRESS. Proceeding anyway.`
          );
        }

        // Request session via WebSocket
        // The useWebSocket hook will emit 'session_started' event
        // which TherapySession will handle
        await requestSession();

        // Session will be initialized by TherapySession component
        setIsSessionReady(true);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : 'Failed to initialize intake session'
        );
        console.error('Intake session error:', err);
      }
    };

    initIntakeSession();
  }, [user, userLoading, requestSession]);

  if (error) {
    return (
      <PageContainer title="Intake Assessment" maxWidth="md">
        <Alert severity="error">
          {error}
          <Button onClick={() => window.location.reload()} sx={{ ml: 2 }}>
            Retry
          </Button>
        </Alert>
      </PageContainer>
    );
  }

  if (!isSessionReady) {
    return <LoadingOverlay message="Preparing your intake session..." fullScreen />;
  }

  return (
    <PageContainer
      title="Intake Assessment"
      subtitle="Tell me about what brings you here today"
      maxWidth="lg"
    >
      <TherapySession />

      {/* Show completion prompt when intake is done */}
      {user?.status === UserStatus.INTAKE_COMPLETE && (
        <Alert severity="success" sx={{ mt: 2 }}>
          <AlertTitle>Intake Complete!</AlertTitle>
          You've completed the intake assessment.
          <Button
            variant="contained"
            size="small"
            sx={{ ml: 2 }}
            onClick={() => navigate('/assessment')}
          >
            Proceed to Assessment
          </Button>
        </Alert>
      )}
    </PageContainer>
  );
}
