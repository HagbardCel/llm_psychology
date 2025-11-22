import { useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { Box } from '@mui/material';

import { AppProvider } from './contexts/AppContext';
import { Navigation } from './components/Navigation';
import { HomePage } from './pages/HomePage';
import { SessionPage } from './pages/SessionPage';
import { SessionHistoryPage } from './pages/SessionHistoryPage';
import { NotFoundPage } from './pages/NotFoundPage';

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

function App() {
  const [navigationOpen, setNavigationOpen] = useState(false);


  const handleNavigationClose = () => {
    setNavigationOpen(false);
  };

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AppProvider>
        <Router>
          <Box sx={{ display: 'flex', minHeight: '100vh' }}>
            <Navigation 
              open={navigationOpen} 
              onClose={handleNavigationClose} 
            />
            
            <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
              <Routes>
                <Route path="/" element={<HomePage />} />
                <Route path="/session" element={<SessionPage />} />
                <Route path="/session/:sessionId" element={<SessionPage />} />
                <Route path="/history" element={<SessionHistoryPage />} />
                <Route path="/settings" element={<div>Settings (Coming Soon)</div>} />
                <Route path="/about" element={<div>About (Coming Soon)</div>} />
                <Route path="/profile" element={<div>Profile Setup (Coming Soon)</div>} />
                <Route path="/intake" element={<div>Intake Assessment (Coming Soon)</div>} />
                <Route path="/assessment" element={<div>Therapy Assessment (Coming Soon)</div>} />
                <Route path="/progress" element={<div>Progress Tracking (Coming Soon)</div>} />
                <Route path="/schedule" element={<div>Session Scheduling (Coming Soon)</div>} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </Box>
          </Box>
        </Router>
      </AppProvider>
    </ThemeProvider>
  );
}

export default App;