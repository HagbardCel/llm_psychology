import { memo, useCallback, useMemo } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Typography,
  Button,
  List,
  ListItem,
  ListItemText,
  CircularProgress,
  Alert
} from '@mui/material';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import { useNavigate } from 'react-router-dom';
import { PageContainer, WorkflowStepper } from './shared';
import { useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useUserProfile } from '../hooks/useUserProfile';
import { useSessionHistory } from '../hooks/useSessionHistory';
import { useTherapyPlan } from '../hooks/useTherapyPlan';
import { useWorkflowNextAction } from '../hooks/useWorkflowNavigation';
import { labelForRequiredAction, routeForRequiredAction } from '../utils/workflow';

/**
 * Dashboard provides an overview of the user's therapy journey.
 * Now uses React Query hooks for all server state - backend-driven architecture.
 */
export const Dashboard = memo(function Dashboard() {
  const navigate = useNavigate();
  const userId = useCurrentUserId();
  const sessionId = useCurrentSessionId();

  // Fetch all data from backend via React Query
  const { data: user, isLoading: userLoading, error: userError } = useUserProfile(
    userId || '',
    sessionId || ''
  );
  const effectiveUserId = user ? userId : '';
  const { data: sessions, isLoading: sessionsLoading } = useSessionHistory(
    effectiveUserId || '',
    sessionId || ''
  );
  const { data: therapyPlan } = useTherapyPlan(effectiveUserId || '', sessionId || '');
  const { data: nextAction, isLoading: actionLoading } = useWorkflowNextAction(
    userId || '',
    sessionId || '',
    '/dashboard',
    { enabled: !!user && !!sessionId }
  );

  // Backend-driven navigation action
  const handleContinue = useCallback(() => {
    const targetRoute = routeForRequiredAction(nextAction?.required_action);
    if (targetRoute) {
      navigate(targetRoute);
    }
  }, [nextAction, navigate]);

  // Memoize expensive computations
  const recentSessions = useMemo(() => sessions?.slice(0, 5) || [], [sessions]);
  const totalSessions = useMemo(() => sessions?.length || 0, [sessions]);

  // Memoize last session date
  const lastSessionDate = useMemo(() => {
    if (sessions && sessions[0]?.timestamp) {
      return new Date(sessions[0].timestamp).toLocaleDateString();
    }
    return 'Never';
  }, [sessions]);

  // Loading state
  if (userLoading || actionLoading) {
    return (
      <PageContainer title="Dashboard" maxWidth="lg">
        <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
          <CircularProgress />
        </div>
      </PageContainer>
    );
  }

  // Error state
  if (userError) {
    return (
      <PageContainer title="Dashboard" maxWidth="lg">
        <Alert severity="error">
          Failed to load user profile. Please try refreshing the page.
        </Alert>
      </PageContainer>
    );
  }

  if (!sessionId) {
    return (
      <PageContainer title="Dashboard" maxWidth="lg">
        <Alert severity="warning">
          No active session found. Please reconnect to start a session.
        </Alert>
      </PageContainer>
    );
  }

  // No user state - guide new users to create a profile
  if (!user) {
    return (
      <PageContainer title="Welcome" maxWidth="lg">
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Let&apos;s get started
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Create your profile so we can personalize your experience.
            </Typography>
            <Button variant="contained" size="large" onClick={() => navigate('/profile')}>
              Continue
            </Button>
          </CardContent>
        </Card>
      </PageContainer>
    );
  }

  return (
    <PageContainer title={`Welcome back, ${user.name}`} maxWidth="lg">
      {nextAction?.required_action === 'wait' && (
        <Alert severity="info" sx={{ mb: 3 }}>
          {nextAction.prompt || 'Assessment in progress. Please wait.'}
        </Alert>
      )}
      {/* Backend-provided instructions */}
      {nextAction?.prompt && nextAction?.required_action !== 'wait' && (
        <Card sx={{ mb: 3, bgcolor: 'primary.light', color: 'primary.contrastText' }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Next Step
            </Typography>
            <Typography variant="body2">{nextAction.prompt}</Typography>
          </CardContent>
        </Card>
      )}

      {/* Workflow Progress */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Your Progress
          </Typography>
          <WorkflowStepper
            currentStatus={user.status}
            onStepClick={(route) => navigate(route)}
          />
        </CardContent>
      </Card>

      {/* Quick Actions */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Quick Actions
          </Typography>
          <Grid container spacing={2} sx={{ mt: 1 }}>
            <Grid item xs={12} md={6}>
              <Button
                variant="contained"
                size="large"
                fullWidth
                onClick={handleContinue}
                disabled={!routeForRequiredAction(nextAction?.required_action)}
              >
                {labelForRequiredAction(nextAction?.required_action)}
              </Button>
            </Grid>
            <Grid item xs={12} md={6}>
              <Button
                variant="outlined"
                size="large"
                fullWidth
                onClick={() => navigate('/history')}
              >
                View Session History
              </Button>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* Stats */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={4}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Total Sessions
              </Typography>
              <Typography variant="h4">
                {sessionsLoading ? <CircularProgress size={24} /> : totalSessions}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={4}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Therapy Style
              </Typography>
              <Typography variant="h4">
                {therapyPlan?.selected_therapy_style || 'Not set'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={4}>
          <Card>
            <CardContent>
              <Typography color="text.secondary" gutterBottom>
                Last Session
              </Typography>
              <Typography variant="h6">
                {lastSessionDate}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Recent Sessions */}
      {recentSessions.length > 0 && (
        <Card>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Recent Sessions
            </Typography>
            <List>
              {recentSessions.map((session) => (
                <ListItem
                  key={session.session_id}
                  onClick={() => navigate(`/session/${session.session_id}`)}
                  sx={{ cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' } }}
                >
                  <ListItemText
                    primary={`Session on ${session.timestamp ? new Date(session.timestamp).toLocaleDateString() : 'Unknown date'}`}
                    secondary={`${session.transcript.length} messages${session.topics ? ` • ${session.topics.length} topics` : ''}`}
                  />
                  <ChevronRightIcon />
                </ListItem>
              ))}
            </List>
          </CardContent>
        </Card>
      )}
    </PageContainer>
  );
});
