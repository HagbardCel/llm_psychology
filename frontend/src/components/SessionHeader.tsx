import React from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Chip,
  Box,
  Avatar,
  Menu,
  MenuItem,
} from '@mui/material';
import {
  Menu as MenuIcon,
  MoreVert as MoreVertIcon,
  Settings as SettingsIcon,
  ExitToApp as ExitToAppIcon,
  Psychology as PsychologyIcon,
} from '@mui/icons-material';
import { format } from 'date-fns';
import { Session, TherapyStyle, AgentType } from '../types';

interface SessionHeaderProps {
  session?: Session | null;
  therapyStyle?: TherapyStyle;
  onMenuClick?: () => void;
  onSettingsClick?: () => void;
  onEndSession?: () => void;
}

export function SessionHeader({
  session,
  therapyStyle,
  onMenuClick,
  onSettingsClick,
  onEndSession,
}: SessionHeaderProps) {
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleMenuClose = () => {
    setAnchorEl(null);
  };

  const getAgentDisplayName = (agentType: AgentType) => {
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
  };

  const getTherapyStyleDisplay = (style: TherapyStyle) => {
    switch (style) {
      case TherapyStyle.FREUD:
        return 'Freudian Analysis';
      case TherapyStyle.JUNG:
        return 'Jungian Analysis';
      case TherapyStyle.CBT:
        return 'Cognitive Behavioral Therapy';
      default:
        return style;
    }
  };

  return (
    <AppBar position="static" elevation={1}>
      <Toolbar>
        <IconButton
          edge="start"
          color="inherit"
          aria-label="menu"
          onClick={onMenuClick}
          sx={{ mr: 2 }}
        >
          <MenuIcon />
        </IconButton>

        <Avatar sx={{ mr: 2, bgcolor: 'secondary.main' }}>
          <PsychologyIcon />
        </Avatar>

        <Box sx={{ flexGrow: 1 }}>
          <Typography variant="h6" component="div">
            {session ? getAgentDisplayName(session.agentType) : 'Psychoanalyst'}
          </Typography>
          
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 0.5 }}>
            {therapyStyle && (
              <Chip
                label={getTherapyStyleDisplay(therapyStyle)}
                size="small"
                variant="outlined"
                sx={{ 
                  color: 'white', 
                  borderColor: 'rgba(255, 255, 255, 0.5)',
                  fontSize: '0.75rem',
                }}
              />
            )}
            
            {session?.startTime && (
              <Typography variant="caption" sx={{ opacity: 0.8 }}>
                Started {format(new Date(session.startTime), 'HH:mm')}
              </Typography>
            )}
          </Box>
        </Box>

        <IconButton
          color="inherit"
          onClick={handleMenuOpen}
          aria-label="more options"
        >
          <MoreVertIcon />
        </IconButton>

        <Menu
          anchorEl={anchorEl}
          open={Boolean(anchorEl)}
          onClose={handleMenuClose}
          anchorOrigin={{
            vertical: 'bottom',
            horizontal: 'right',
          }}
          transformOrigin={{
            vertical: 'top',
            horizontal: 'right',
          }}
        >
          <MenuItem
            onClick={() => {
              handleMenuClose();
              onSettingsClick?.();
            }}
          >
            <SettingsIcon sx={{ mr: 1 }} />
            Settings
          </MenuItem>
          
          {session && (
            <MenuItem
              onClick={() => {
                handleMenuClose();
                onEndSession?.();
              }}
              sx={{ color: 'error.main' }}
            >
              <ExitToAppIcon sx={{ mr: 1 }} />
              End Session
            </MenuItem>
          )}
        </Menu>
      </Toolbar>
    </AppBar>
  );
}