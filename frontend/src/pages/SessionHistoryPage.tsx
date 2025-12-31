import React, { Fragment } from 'react';
import {
  Container,
  Typography,
  Paper,
  List,
  ListItem,
  ListItemText,
  ListItemButton,
  Divider,
  Alert,
  Box,
  CircularProgress
} from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useSessionHistory } from '../hooks/useSessionHistory';

/**
 * SessionHistoryPage - Display user's past therapy sessions
 * Refactored to use React Query for server state management
 */
export const SessionHistoryPage: React.FC = () => {
  const userId = useCurrentUserId();
  const sessionId = useCurrentSessionId();
  const navigate = useNavigate();

  // Fetch sessions from backend via React Query
  const { data: sessions, isLoading, error } = useSessionHistory(
    userId || '',
    sessionId || ''
  );

  const handleSessionClick = (sessionId: string) => {
    navigate(`/session/${sessionId}`);
  };

  // Loading state
  if (isLoading) {
    return (
      <Container maxWidth="md" sx={{ mt: 4, mb: 4 }}>
        <Typography variant="h4" gutterBottom>
          Session History
        </Typography>
        <Paper elevation={3} sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress />
          </Box>
        </Paper>
      </Container>
    );
  }

  return (
    <Container maxWidth="md" sx={{ mt: 4, mb: 4 }}>
      <Typography variant="h4" gutterBottom>
        Session History
      </Typography>

      {/* Error state */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load sessions. Please try refreshing the page.
        </Alert>
      )}
      {!sessionId && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          No active session found. Please reconnect to view session history.
        </Alert>
      )}

      <Paper elevation={3}>
        {!sessions || sessions.length === 0 ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body1" color="text.secondary">
              No sessions found. Start a new session to begin your journey.
            </Typography>
          </Box>
        ) : (
          <List>
            {sessions.map((session, index) => (
              <Fragment key={session.session_id}>
                {index > 0 && <Divider />}
                <ListItem disablePadding>
                  <ListItemButton onClick={() => handleSessionClick(session.session_id)}>
                    <ListItemText
                      primary={`Session ${session.timestamp ? new Date(session.timestamp).toLocaleString() : 'Unknown date'}`}
                      secondary={`${session.transcript.length} messages • ${session.topics?.length || 0} topics`}
                    />
                  </ListItemButton>
                </ListItem>
              </Fragment>
            ))}
          </List>
        )}
      </Paper>
    </Container>
  );
};
