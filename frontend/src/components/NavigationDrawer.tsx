import { Link, useLocation } from 'react-router-dom';
import {
  Drawer,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Box,
  Typography,
  Avatar,
  Chip,
  CircularProgress
} from '@mui/material';
import type { ReactElement } from 'react';
import DashboardIcon from '@mui/icons-material/Dashboard';
import ChatIcon from '@mui/icons-material/Chat';
import HistoryIcon from '@mui/icons-material/History';
import PersonIcon from '@mui/icons-material/Person';
import SettingsIcon from '@mui/icons-material/Settings';
import LockIcon from '@mui/icons-material/Lock';
import { useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useUserProfile } from '../hooks/useUserProfile';
import { UserStatus } from '../types';

export interface NavigationDrawerProps {
  open: boolean;
  onClose: () => void;
  variant: 'permanent' | 'temporary';
}

interface NavigationItem {
  label: string;
  path: string;
  icon: ReactElement;
  locked?: boolean;
}

/**
 * NavigationDrawer provides the main app navigation.
 * Displays user profile summary and navigation links.
 * Locks certain routes based on user workflow status.
 * Refactored to use React Query for user data.
 */
export function NavigationDrawer({ open, onClose, variant }: NavigationDrawerProps) {
  const userId = useCurrentUserId();
  const sessionId = useCurrentSessionId();
  const { data: user, isLoading } = useUserProfile(userId || '', sessionId || '');
  const location = useLocation();

  if (isLoading) {
    return (
      <Drawer
        variant={variant}
        open={open}
        onClose={onClose}
        sx={{
          width: 240,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: 240,
            boxSizing: 'border-box'
          }
        }}
      >
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          <CircularProgress />
        </Box>
      </Drawer>
    );
  }

  if (!user) {
    return null;
  }

  const navigationItems: NavigationItem[] = [
    { label: 'Dashboard', path: '/dashboard', icon: <DashboardIcon /> },
    {
      label: 'Therapy Session',
      path: '/session/new',
      icon: <ChatIcon />,
      locked: user.status < UserStatus.PLAN_COMPLETE
    },
    { label: 'History', path: '/history', icon: <HistoryIcon /> },
    { label: 'Profile', path: '/profile', icon: <PersonIcon /> },
    { label: 'Settings', path: '/settings', icon: <SettingsIcon /> }
  ];

  return (
    <Drawer
      variant={variant}
      open={open}
      onClose={onClose}
      sx={{
        width: 240,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: 240,
          boxSizing: 'border-box'
        }
      }}
      role="navigation"
      aria-label="Main navigation"
    >
      {/* User profile summary */}
      <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Box display="flex" alignItems="center" gap={2}>
          <Avatar sx={{ bgcolor: 'primary.main' }}>{user.name[0]}</Avatar>
          <Box flex={1}>
            <Typography variant="subtitle1" noWrap>
              {user.name}
            </Typography>
            <Chip label={getUserStatusLabel(user.status)} size="small" />
          </Box>
        </Box>
      </Box>

      {/* Navigation list */}
      <List>
        {navigationItems.map((item) => (
          <ListItem
            key={item.path}
            component={Link}
            to={item.path}
            onClick={variant === 'temporary' ? onClose : undefined}
            sx={{
              color: 'inherit',
              textDecoration: 'none',
              bgcolor:
                location.pathname === item.path
                  ? 'action.selected'
                  : 'transparent',
              '&:hover': {
                bgcolor: 'action.hover'
              },
              pointerEvents: item.locked ? 'none' : 'auto',
              opacity: item.locked ? 0.5 : 1
            }}
          >
            <ListItemIcon>{item.icon}</ListItemIcon>
            <ListItemText primary={item.label} />
            {item.locked && <LockIcon fontSize="small" color="disabled" />}
          </ListItem>
        ))}
      </List>
    </Drawer>
  );
}

/**
 * Convert UserStatus enum to human-readable label.
 */
function getUserStatusLabel(status: UserStatus): string {
  switch (status) {
    case UserStatus.PROFILE_ONLY:
      return 'New User';
    case UserStatus.INTAKE_IN_PROGRESS:
      return 'Intake';
    case UserStatus.INTAKE_COMPLETE:
      return 'Intake Complete';
    case UserStatus.ASSESSMENT_IN_PROGRESS:
      return 'Assessment';
    case UserStatus.ASSESSMENT_COMPLETE:
      return 'Assessment Complete';
    case UserStatus.PLAN_COMPLETE:
      return 'Ready';
    case UserStatus.THERAPY_IN_PROGRESS:
      return 'In Therapy';
    case UserStatus.REFLECTION_IN_PROGRESS:
      return 'Reflecting';
    default:
      return status;
  }
}
