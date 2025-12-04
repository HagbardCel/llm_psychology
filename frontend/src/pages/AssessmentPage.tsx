import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Grid,
  Card,
  CardContent,
  CardActions,
  Typography,
  Button,
  CircularProgress,
  Alert,
  Divider
} from '@mui/material';
import { PageContainer } from '../components/shared';
import { TherapySession } from '../components/TherapySession';
import { useCurrentUserId } from '../contexts/AppContext';
import { useUserProfile } from '../hooks/useUserProfile';
import { TherapyStyle } from '../types';
import { api } from '../services/api';
import { ApiRequestError } from '../services/apiClient';

type AssessmentMode = 'chat' | 'selection';

interface StyleRecommendation {
  style: TherapyStyle;
  reason: string;
  description: string;
}

/**
 * AssessmentPage handles the therapy style assessment and selection.
 * Two modes:
 * 1. Chat mode: Conversation with Assessment agent
 * 2. Selection mode: Choose therapy style from recommendations
 */
export function AssessmentPage() {
  const userId = useCurrentUserId();
  const { data: user } = useUserProfile(userId || '');
  const navigate = useNavigate();
  const [mode, setMode] = useState<AssessmentMode>('chat');
  const [recommendations, setRecommendations] = useState<StyleRecommendation[]>([]);
  const [isCreatingPlan, setIsCreatingPlan] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Listen for assessment completion (custom event from backend WebSocket)
  useEffect(() => {
    const handleAssessmentComplete = (event: CustomEvent) => {
      const { recommended_styles } = event.detail;

      // Transform backend recommendations to UI format
      const styleRecommendations: StyleRecommendation[] = recommended_styles.map(
        (rec: { style: TherapyStyle; reason: string }) => ({
          style: rec.style,
          reason: rec.reason,
          description: getStyleDescription(rec.style)
        })
      );

      setRecommendations(styleRecommendations);
      setMode('selection');
    };

    window.addEventListener(
      'assessment-complete',
      handleAssessmentComplete as EventListener
    );
    return () =>
      window.removeEventListener(
        'assessment-complete',
        handleAssessmentComplete as EventListener
      );
  }, []);

  const handleStyleSelect = async (style: TherapyStyle) => {
    if (!user) return;

    setIsCreatingPlan(true);
    setError(null);

    try {
      await api.therapy.createPlan({
        user_id: user.id,
        therapy_style: style
      });

      // Navigate to dashboard
      // (Backend handles status update via workflow state machine)
      navigate('/dashboard');
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

  if (mode === 'chat') {
    return (
      <PageContainer
        title="Therapy Assessment"
        subtitle="Let's explore which therapeutic approach suits you best"
        maxWidth="lg"
      >
        <TherapySession />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title="Choose Your Therapy Style"
      subtitle="Based on our conversation, here are our recommendations"
      maxWidth="lg"
    >
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      <Grid container spacing={3}>
        {recommendations.map((rec) => (
          <Grid item xs={12} md={4} key={rec.style}>
            <Card
              sx={{
                height: '100%',
                display: 'flex',
                flexDirection: 'column'
              }}
            >
              <CardContent sx={{ flexGrow: 1 }}>
                <Typography variant="h5" component="h2" gutterBottom>
                  {capitalizeStyle(rec.style)}
                </Typography>

                <Typography variant="body2" color="text.secondary" paragraph>
                  {rec.description}
                </Typography>

                <Divider sx={{ my: 2 }} />

                <Typography variant="subtitle2" gutterBottom>
                  Why we recommend this:
                </Typography>
                <Typography variant="body2">{rec.reason}</Typography>
              </CardContent>

              <CardActions>
                <Button
                  fullWidth
                  variant="contained"
                  onClick={() => handleStyleSelect(rec.style)}
                  disabled={isCreatingPlan}
                >
                  {isCreatingPlan ? (
                    <CircularProgress size={24} />
                  ) : (
                    `Select ${capitalizeStyle(rec.style)}`
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
function getStyleDescription(style: TherapyStyle): string {
  const descriptions = {
    [TherapyStyle.FREUD]:
      'Psychoanalytic approach focusing on unconscious processes, childhood experiences, and dream analysis.',
    [TherapyStyle.JUNG]:
      'Analytical psychology emphasizing archetypes, the collective unconscious, and individuation.',
    [TherapyStyle.CBT]:
      'Cognitive Behavioral Therapy focusing on identifying and changing negative thought patterns.'
  };
  return descriptions[style] || 'A personalized therapeutic approach.';
}

function capitalizeStyle(style: string): string {
  return style.charAt(0).toUpperCase() + style.slice(1).toLowerCase();
}
