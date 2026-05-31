import { useEffect, useState } from 'react';
import {
  Grid,
  Card,
  CardContent,
  CardActions,
  Typography,
  Button,
  CircularProgress,
  Alert,
  Box,
  Divider
} from '@mui/material';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { PageContainer } from '../components/shared';
import { useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useWebSocketContext } from '../contexts/WebSocketContext';
import { useUserProfile } from '../hooks/useUserProfile';
import { TherapyStyle, TherapyStyleInfo, WorkflowNextAction } from '../types';
import { apiClient, ApiRequestError } from '../services/apiClient';
import { useWorkflowNextAction } from '../hooks/useWorkflowNavigation';
import { labelForRequiredAction } from '../utils/workflow';

/**
 * AssessmentPage handles the therapy style assessment and selection.
 * In the backend-driven flow, the assessment runs asynchronously and this
 * page only handles style selection once required_action is set.
 */
export function AssessmentPage() {
  const userId = useCurrentUserId();
  const sessionId = useCurrentSessionId();
  const { assessmentRecommendations } = useWebSocketContext();
  const { data: user } = useUserProfile(userId || '', sessionId || '');
  const queryClient = useQueryClient();
  const { data: nextAction, isLoading: actionLoading } = useWorkflowNextAction(
    userId || '',
    sessionId || '',
    '/assessment',
    { enabled: !!userId && !!sessionId }
  );
  const [stylesError, setStylesError] = useState<string | null>(null);
  const [isCreatingPlan, setIsCreatingPlan] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recommendations =
    assessmentRecommendations?.user_id === userId
      ? assessmentRecommendations.recommendations || []
      : [];
  const hasRecommendations = recommendations.length > 0;

  const {
    data: styles,
    isLoading: stylesLoading,
    error: stylesQueryError,
  } = useQuery({
    queryKey: ['therapyStyles', userId, sessionId],
    queryFn: async () =>
      apiClient.get<TherapyStyleInfo[]>(
        `/api/therapy/styles?user_id=${encodeURIComponent(userId || '')}&session_id=${encodeURIComponent(sessionId || '')}`
      ),
    enabled: nextAction?.required_action === 'select_therapy_style' && !!sessionId,
  });

  useEffect(() => {
    if (stylesQueryError) {
      setStylesError(
        stylesQueryError instanceof Error
          ? stylesQueryError.message
          : 'Failed to load styles'
      );
      return;
    }
    if (!stylesLoading) {
      setStylesError(null);
    }
  }, [stylesLoading, stylesQueryError]);

  const handleStyleSelect = async (style: string) => {
    if (!user) return;
    if (!sessionId) {
      setError('Session is required to select a therapy style. Please reconnect.');
      return;
    }

    setIsCreatingPlan(true);
    setError(null);

    try {
      await apiClient.post<WorkflowNextAction>(
        '/api/workflow/select_therapy_style',
        {
          user_id: user.user_id,
          session_id: sessionId,
          selected_therapy_style: style.toLowerCase()
        }
      );

      await queryClient.invalidateQueries({
        queryKey: ['workflow', 'next', user.user_id, sessionId]
      });
      await queryClient.invalidateQueries({
        queryKey: ['therapyPlan', user.user_id, sessionId]
      });
    } catch (err) {
      if (err instanceof ApiRequestError) {
        const errorMessage = err.body?.detail || err.body?.message || err.statusText;
        setError(`Failed to create therapy plan: ${errorMessage}`);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to create therapy plan');
      }
      console.error('Therapy plan creation error:', err);
    } finally {
      setIsCreatingPlan(false);
    }
  };

  if (actionLoading) {
    return (
      <PageContainer
        title="Therapy Assessment"
        subtitle="Checking assessment status..."
        maxWidth="lg"
      >
        <CircularProgress />
      </PageContainer>
    );
  }

  if (nextAction?.required_action === 'wait') {
    return (
      <PageContainer
        title="Therapy Assessment"
        subtitle={nextAction.prompt || 'Assessment in progress. Please wait.'}
        maxWidth="lg"
      >
        <CircularProgress />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title="Choose Your Therapy Style"
      subtitle={nextAction?.prompt || 'Select a therapy style to continue'}
      maxWidth="lg"
    >
      {!sessionId && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          No active session found. Please reconnect to continue.
        </Alert>
      )}
      {!hasRecommendations && (
        <Alert severity="info" sx={{ mb: 3 }}>
          Waiting for assessment recommendations before selecting a therapy style.
        </Alert>
      )}
      {hasRecommendations && (
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Assessment Recommendations
            </Typography>
            {(recommendations || []).map((rec, index) => (
              <Box key={`${rec.style_id || index}`} sx={{ mb: 2 }}>
                <Typography variant="subtitle1">
                  {capitalizeStyle(rec.style_id || `option_${index + 1}`)}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {rec.explanation || 'No rationale provided.'}
                </Typography>
              </Box>
            ))}
          </CardContent>
        </Card>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {stylesError && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {stylesError}
        </Alert>
      )}

      {stylesLoading && <CircularProgress />}

      <Grid container spacing={3}>
        {(styles || []).map((style) => (
          <Grid size={{ xs: 12, md: 4 }} key={style.style}>
            <Card
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column'
              }}
            >
              <CardContent sx={{ flexGrow: 1 }}>
                <Typography variant="h5" component="h2" gutterBottom>
                  {capitalizeStyle(style.style)}
                </Typography>

                <Typography variant="body2" color="text.secondary" paragraph>
                  {style.description || getStyleDescription(style.style)}
                </Typography>

                <Divider sx={{ my: 2 }} />

                <Typography variant="subtitle2" gutterBottom>
                  {labelForRequiredAction('select_therapy_style')}
                </Typography>
                <Typography variant="body2">
                  Choose the style that feels right for you.
                </Typography>
              </CardContent>

              <CardActions>
                <Button
                  fullWidth
                  variant="contained"
                  onClick={() => handleStyleSelect(style.style)}
                  disabled={isCreatingPlan || !hasRecommendations}
                >
                  {isCreatingPlan ? (
                    <CircularProgress size={24} />
                  ) : (
                    `Select ${capitalizeStyle(style.style)}`
                  )}
                </Button>
              </CardActions>
            </Card>
          </Grid>
        ))}
      </Grid>
    </PageContainer>
  );
}

// Helper functions
function getStyleDescription(style: string): string {
  const normalized = style.toLowerCase() as TherapyStyle;
  const descriptions = {
    [TherapyStyle.FREUD]:
      'Psychoanalytic approach focusing on unconscious processes, childhood experiences, and dream analysis.',
    [TherapyStyle.JUNG]:
      'Analytical psychology emphasizing archetypes, the collective unconscious, and individuation.',
    [TherapyStyle.CBT]:
      'Cognitive Behavioral Therapy focusing on identifying and changing negative thought patterns.'
  };
  return descriptions[normalized] || 'A personalized therapeutic approach.';
}

function capitalizeStyle(style: string): string {
  return style.charAt(0).toUpperCase() + style.slice(1).toLowerCase();
}
