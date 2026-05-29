import {
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Divider,
  Typography,
  Box,
  Avatar,
  Chip,
  CircularProgress,
} from '@mui/material';
import {
  Dashboard as DashboardIcon,
  Psychology as PsychologyIcon,
  History as HistoryIcon,
  Settings as SettingsIcon,
  Info as InfoIcon,
  Person as PersonIcon,
} from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router';
import { useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useUserProfile } from '../hooks/useUserProfile';
import { UserStatus } from '../types';

interface NavigationProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Navigation drawer component
 * Refactored to use React Query for user data
 */
export function Navigation({ open, onClose }: NavigationProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const userId = useCurrentUserId();
  const sessionId = useCurrentSessionId();

  // Fetch user data from backend via React Query
  const { data: user, isLoading } = useUserProfile(userId || '', sessionId || '');

  const handleNavigation = (path: string) => {
    navigate(path);
    onClose();
  };

  const getStatusColor = (status: UserStatus) => {
    switch (status) {
      case UserStatus.PROFILE_ONLY:
        return 'warning';
      case UserStatus.INTAKE_COMPLETE:
        return 'info';
      case UserStatus.INITIAL_PLAN_COMPLETE:
      case UserStatus.PLAN_UPDATE_COMPLETE:
        return 'success';
      default:
        return 'default';
    }
  };

  const getStatusText = (status: UserStatus) => {
    switch (status) {
      case UserStatus.PROFILE_ONLY:
        return 'Setup Required';
      case UserStatus.INTAKE_COMPLETE:
        return 'Assessment Ready';
      case UserStatus.INITIAL_PLAN_COMPLETE:
        return 'Ready for Therapy';
      case UserStatus.PLAN_UPDATE_COMPLETE:
        return 'Ready for Therapy';
      default:
        return 'Unknown';
    }
  };

  const menuItems = [
    {
      text: 'Dashboard',
      icon: <DashboardIcon />,
      path: '/',
      enabled: true,
    },
    {
      text: 'New Session',
      icon: <PsychologyIcon />,
      path: '/session/new',
      enabled:
        user?.status === UserStatus.INITIAL_PLAN_COMPLETE ||
        user?.status === UserStatus.PLAN_UPDATE_COMPLETE,
    },
    {
      text: 'Session History',
      icon: <HistoryIcon />,
      path: '/history',
      enabled: true,
    },
    {
      text: 'Settings',
      icon: <SettingsIcon />,
      path: '/settings',
      enabled: true,
    },
    {
      text: 'About',
      icon: <InfoIcon />,
      path: '/about',
      enabled: true,
    },
  ];

  return (
    <Drawer
      anchor="left"
      open={open}
      onClose={onClose}
      sx={{
        '& .MuiDrawer-paper': {
          width: 280,
          boxSizing: 'border-box',
        },
      }}
    >
      <Box sx={{ p: 2 }}>
        {isLoading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
            <CircularProgress size={40} />
          </Box>
        ) : user ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Avatar sx={{ bgcolor: 'primary.main' }}>
              <PersonIcon />
            </Avatar>
            <Box sx={{ flexGrow: 1 }}>
              <Typography variant="h6" noWrap>
                {user.name || 'User'}
              </Typography>
              <Chip
                label={getStatusText(user.status)}
                size="small"
                color={getStatusColor(user.status)}
                variant="outlined"
              />
            </Box>
          </Box>
        ) : (
          <Box sx={{ textAlign: 'center' }}>
            <Avatar sx={{ mx: 'auto', mb: 1, bgcolor: 'grey.400' }}>
              <PersonIcon />
            </Avatar>
            <Typography variant="body2" color="text.secondary">
              No user profile
            </Typography>
          </Box>
        )}
      </Box>

      <Divider />

      <List sx={{ flexGrow: 1 }}>
        {menuItems.map((item) => (
          <ListItem key={item.text} disablePadding>
            <ListItemButton
              selected={location.pathname === item.path}
              disabled={!item.enabled}
              onClick={() => handleNavigation(item.path)}
            >
              <ListItemIcon>
                {item.icon}
              </ListItemIcon>
              <ListItemText
                primary={item.text}
                secondary={!item.enabled ? 'Complete setup first' : ''}
              />
            </ListItemButton>
          </ListItem>
        ))}
      </List>

    </Drawer>
  );
}
