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
} from '@mui/material';
import {
  Dashboard as DashboardIcon,
  Psychology as PsychologyIcon,
  History as HistoryIcon,
  Settings as SettingsIcon,
  Info as InfoIcon,
  ExitToApp as LogoutIcon,
  Person as PersonIcon,
} from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAppContext } from '../contexts/AppContext';
import { UserStatus } from '../types';

interface NavigationProps {
  open: boolean;
  onClose: () => void;
}

export function Navigation({ open, onClose }: NavigationProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { state } = useAppContext();

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
      case UserStatus.PLAN_COMPLETE:
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
      case UserStatus.PLAN_COMPLETE:
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
      path: '/session',
      enabled: state.user?.status === UserStatus.PLAN_COMPLETE,
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
        {state.user ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Avatar sx={{ bgcolor: 'primary.main' }}>
              <PersonIcon />
            </Avatar>
            <Box sx={{ flexGrow: 1 }}>
              <Typography variant="h6" noWrap>
                {state.user.name || 'User'}
              </Typography>
              <Chip
                label={getStatusText(state.user.status)}
                size="small"
                color={getStatusColor(state.user.status)}
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

      <Divider />

      {state.user && (
        <List>
          <ListItem disablePadding>
            <ListItemButton
              onClick={() => {
                // TODO: Implement logout functionality
                console.log('Logout clicked');
                onClose();
              }}
            >
              <ListItemIcon>
                <LogoutIcon />
              </ListItemIcon>
              <ListItemText primary="Sign Out" />
            </ListItemButton>
          </ListItem>
        </List>
      )}
    </Drawer>
  );
}