import { ReactNode } from 'react';
import {
  Box,
  AppBar,
  Toolbar,
  IconButton,
  Typography,
  useMediaQuery,
  useTheme
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import { NavigationDrawer } from './NavigationDrawer';
import { WorkflowGate } from './WorkflowGate';
import { useAppContext } from '../contexts/AppContext';

export interface LayoutProps {
  children: ReactNode;
}

/**
 * Layout provides the main application layout with AppBar and NavigationDrawer.
 * Responsive: Permanent drawer on desktop, temporary drawer on mobile.
 */
export function Layout({ children }: LayoutProps) {
  const { sidebarOpen, setSidebarOpen } = useAppContext();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      {/* AppBar - visible only on mobile */}
      <AppBar
        position="fixed"
        sx={{
          zIndex: (theme) => theme.zIndex.drawer + 1,
          display: { md: 'none' } // Hide on desktop
        }}
      >
        <Toolbar>
          <IconButton
            color="inherit"
            aria-label="open drawer"
            edge="start"
            onClick={() => setSidebarOpen(true)}
            sx={{ mr: 2 }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" noWrap component="div">
            Psychoanalyst
          </Typography>
        </Toolbar>
      </AppBar>

      {/* Navigation Drawer */}
      <NavigationDrawer
        open={isMobile ? sidebarOpen : true}
        onClose={() => setSidebarOpen(false)}
        variant={isMobile ? 'temporary' : 'permanent'}
      />

      {/* Main content area */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          mt: { xs: 8, md: 0 }, // Margin-top for mobile AppBar
          ml: { md: '240px' }, // Margin-left for permanent drawer on desktop
          width: { xs: '100%', md: 'calc(100% - 240px)' }
        }}
      >
        <WorkflowGate />
        {children}
      </Box>
    </Box>
  );
}
