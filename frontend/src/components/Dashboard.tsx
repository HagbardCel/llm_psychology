import {
  Container,
  Grid,
  Card,
  CardContent,
  CardActions,
  Typography,
  Button,
  Box,
  LinearProgress,
  Chip,
  List,
  ListItem,
  ListItemText,
  ListItemIcon,
  Alert,
} from '@mui/material';
import {
  Psychology as PsychologyIcon,
  History as HistoryIcon,
  Assessment as AssessmentIcon,
  TrendingUp as TrendingUpIcon,
  Schedule as ScheduleIcon,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { format, formatDistanceToNow } from 'date-fns';
import { useAppContext } from '../contexts/AppContext';
import { UserStatus, SessionStatus, AgentType } from '../types';

export function Dashboard() {
  const navigate = useNavigate();
  const { state } = useAppContext();

  const recentSessions = state.sessions
    .filter(s => s.status === SessionStatus.COMPLETED)
    .sort((a, b) => new Date(b.startTime).getTime() - new Date(a.startTime).getTime())
    .slice(0, 5);

  const activeSession = state.sessions.find(s => s.status === SessionStatus.ACTIVE);
  const totalSessions = state.sessions.length;
  const completedSessions = state.sessions.filter(s => s.status === SessionStatus.COMPLETED).length;

  const getNextAction = () => {
    if (!state.user) {
      return {
        title: 'Create Your Profile',
        description: 'Start by creating your user profile to begin your therapeutic journey.',
        action: 'Get Started',
        path: '/profile',
      };
    }

    switch (state.user.status) {
      case UserStatus.PROFILE_ONLY:
        return {
          title: 'Complete Intake Assessment',
          description: 'Tell us about yourself and what you hope to achieve.',
          action: 'Start Intake',
          path: '/intake',
        };
      case UserStatus.INTAKE_COMPLETE:
        return {
          title: 'Complete Therapy Assessment',
          description: 'Let us recommend the best therapeutic approach for you.',
          action: 'Start Assessment',
          path: '/assessment',
        };
      case UserStatus.PLAN_COMPLETE:
        return {
          title: 'Begin Your Therapy Session',
          description: 'Ready to start your therapeutic journey with your personalized plan.',
          action: 'Start Session',
          path: '/session',
        };
      default:
        return null;
    }
  };

  const nextAction = getNextAction();

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      <Typography variant="h4" gutterBottom>
        Welcome to Your Therapeutic Journey
      </Typography>

      {activeSession && (
        <Alert 
          severity="info" 
          sx={{ mb: 3 }}
          action={
            <Button 
              color="inherit" 
              size="small"
              onClick={() => navigate('/session')}
            >
              Resume
            </Button>
          }
        >
          You have an active session that was started {formatDistanceToNow(new Date(activeSession.startTime))} ago.
        </Alert>
      )}

      <Grid container spacing={3}>
        {/* Next Action Card */}
        {nextAction && (
          <Grid item xs={12} md={8}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="h5" gutterBottom>
                  {nextAction.title}
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  {nextAction.description}
                </Typography>
              </CardContent>
              <CardActions>
                <Button 
                  variant="contained" 
                  size="large"
                  onClick={() => navigate(nextAction.path)}
                  startIcon={<PsychologyIcon />}
                >
                  {nextAction.action}
                </Button>
              </CardActions>
            </Card>
          </Grid>
        )}

        {/* Progress Overview */}
        <Grid item xs={12} md={4}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Your Progress
              </Typography>
              
              <Box sx={{ mb: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  Total Sessions: {totalSessions}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Completed: {completedSessions}
                </Typography>
              </Box>

              {state.user && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="body2" gutterBottom>
                    Setup Progress
                  </Typography>
                  <LinearProgress 
                    variant="determinate" 
                    value={getProgressValue(state.user.status)} 
                    sx={{ mb: 1 }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    {getProgressValue(state.user.status)}% Complete
                  </Typography>
                </Box>
              )}

              {state.therapyPlan && (
                <Chip
                  icon={<AssessmentIcon />}
                  label={`${state.therapyPlan.therapyStyle.toUpperCase()} Therapy`}
                  color="primary"
                  variant="outlined"
                />
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* Recent Sessions */}
        {recentSessions.length > 0 && (
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                  <Typography variant="h6">
                    Recent Sessions
                  </Typography>
                  <Button 
                    endIcon={<HistoryIcon />}
                    onClick={() => navigate('/history')}
                  >
                    View All
                  </Button>
                </Box>

                <List>
                  {recentSessions.map((session) => (
                    <ListItem key={session.id} divider>
                      <ListItemIcon>
                        {getSessionIcon(session.agentType)}
                      </ListItemIcon>
                      <ListItemText
                        primary={getSessionTitle(session.agentType)}
                        secondary={
                          <Box>
                            <Typography variant="body2" color="text.secondary">
                              {format(new Date(session.startTime), 'PPP p')}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                              {session.messages.length} messages
                            </Typography>
                          </Box>
                        }
                      />
                      <Chip 
                        label={session.status}
                        size="small"
                        color={session.status === SessionStatus.COMPLETED ? 'success' : 'default'}
                      />
                    </ListItem>
                  ))}
                </List>
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Quick Actions */}
        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent sx={{ textAlign: 'center' }}>
              <PsychologyIcon sx={{ fontSize: 48, color: 'primary.main', mb: 1 }} />
              <Typography variant="h6" gutterBottom>
                New Session
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Start a new therapy session
              </Typography>
              <Button 
                variant="outlined" 
                fullWidth
                onClick={() => navigate('/session')}
                disabled={state.user?.status !== UserStatus.PLAN_COMPLETE}
              >
                Start
              </Button>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent sx={{ textAlign: 'center' }}>
              <HistoryIcon sx={{ fontSize: 48, color: 'secondary.main', mb: 1 }} />
              <Typography variant="h6" gutterBottom>
                Session History
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Review past sessions
              </Typography>
              <Button 
                variant="outlined" 
                fullWidth
                onClick={() => navigate('/history')}
              >
                View
              </Button>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent sx={{ textAlign: 'center' }}>
              <TrendingUpIcon sx={{ fontSize: 48, color: 'success.main', mb: 1 }} />
              <Typography variant="h6" gutterBottom>
                Progress
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Track your journey
              </Typography>
              <Button 
                variant="outlined" 
                fullWidth
                onClick={() => navigate('/progress')}
              >
                View
              </Button>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card>
            <CardContent sx={{ textAlign: 'center' }}>
              <ScheduleIcon sx={{ fontSize: 48, color: 'info.main', mb: 1 }} />
              <Typography variant="h6" gutterBottom>
                Schedule
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Plan your sessions
              </Typography>
              <Button 
                variant="outlined" 
                fullWidth
                onClick={() => navigate('/schedule')}
              >
                Plan
              </Button>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Container>
  );
}

function getProgressValue(status: UserStatus): number {
  switch (status) {
    case UserStatus.PROFILE_ONLY:
      return 33;
    case UserStatus.INTAKE_COMPLETE:
      return 66;
    case UserStatus.PLAN_COMPLETE:
      return 100;
    default:
      return 0;
  }
}

function getSessionIcon(agentType: AgentType) {
  switch (agentType) {
    case AgentType.INTAKE:
      return <AssessmentIcon />;
    case AgentType.ASSESSMENT:
      return <TrendingUpIcon />;
    case AgentType.PSYCHOANALYST:
      return <PsychologyIcon />;
    case AgentType.REFLECTION:
      return <HistoryIcon />;
    default:
      return <PsychologyIcon />;
  }
}

function getSessionTitle(agentType: AgentType): string {
  switch (agentType) {
    case AgentType.INTAKE:
      return 'Intake Session';
    case AgentType.ASSESSMENT:
      return 'Assessment Session';
    case AgentType.PSYCHOANALYST:
      return 'Therapy Session';
    case AgentType.REFLECTION:
      return 'Reflection Session';
    default:
      return 'Session';
  }
}