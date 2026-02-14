import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { lazy, Suspense } from 'react';
import { CircularProgress, Box } from '@mui/material';

import { AppProvider } from './contexts/AppContext';
import { WebSocketProvider } from './contexts/WebSocketContext';
import { Layout } from './components/Layout';
import { VersionCheck } from './components/VersionCheck';

// Lazy load pages for code splitting
const Dashboard = lazy(() => import('./components/Dashboard').then(m => ({ default: m.Dashboard })));
const SessionHistoryPage = lazy(() => import('./pages/SessionHistoryPage').then(m => ({ default: m.SessionHistoryPage })));
const ProfilePage = lazy(() => import('./pages/ProfilePage').then(m => ({ default: m.ProfilePage })));
const IntakePage = lazy(() => import('./pages/IntakePage').then(m => ({ default: m.IntakePage })));
const AssessmentPage = lazy(() => import('./pages/AssessmentPage').then(m => ({ default: m.AssessmentPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })));
const TherapySession = lazy(() => import('./components/TherapySession').then(m => ({ default: m.TherapySession })));

// Create Material-UI theme
const theme = createTheme({
  palette: {
    primary: {
      main: '#1976d2',
    },
    secondary: {
      main: '#dc004e',
    },
    background: {
      default: '#f5f5f5',
    },
  },
  typography: {
    fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
        },
      },
    },
  },
});

// Loading fallback component
function LoadingFallback() {
  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
      }}
    >
      <CircularProgress />
    </Box>
  );
}

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <VersionCheck />
      <AppProvider>
        <WebSocketProvider>
          <Router>
            <Suspense fallback={<LoadingFallback />}>
              <Routes>
                <Route
                  path="/profile"
                  element={
                    <Layout>
                      <ProfilePage />
                    </Layout>
                  }
                />
                <Route
                  path="/intake"
                  element={
                    <Layout>
                      <IntakePage />
                    </Layout>
                  }
                />
                <Route
                  path="/assessment"
                  element={
                    <Layout>
                      <AssessmentPage />
                    </Layout>
                  }
                />
                <Route
                  path="/session/new"
                  element={
                    <Layout>
                      <TherapySession />
                    </Layout>
                  }
                />
                <Route
                  path="/session/:sessionId"
                  element={
                    <Layout>
                      <TherapySession />
                    </Layout>
                  }
                />
                <Route
                  path="/dashboard"
                  element={
                    <Layout>
                      <Dashboard />
                    </Layout>
                  }
                />
                <Route
                  path="/history"
                  element={
                    <Layout>
                      <SessionHistoryPage />
                    </Layout>
                  }
                />
                <Route
                  path="/settings"
                  element={
                    <Layout>
                      <SettingsPage />
                    </Layout>
                  }
                />

                {/* Default redirects */}
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
              </Routes>
            </Suspense>
          </Router>
        </WebSocketProvider>
      </AppProvider>
    </ThemeProvider>
  );
}

export default App;
