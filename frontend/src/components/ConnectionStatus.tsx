/**
 * Connection status indicator component
 */

import React from 'react';
import {
  Box,
  Chip,
  Tooltip,
  Typography,
  CircularProgress
} from '@mui/material';
import {
  WifiOff as DisconnectedIcon,
  Wifi as ConnectedIcon
} from '@mui/icons-material';
import { ConnectionStatus as ConnectionStatusType } from '../types/websocket';

interface ConnectionStatusProps {
  status: ConnectionStatusType;
  showDetails?: boolean;
  variant?: 'chip' | 'full';
}

export const ConnectionStatus: React.FC<ConnectionStatusProps> = ({
  status,
  showDetails = false,
  variant = 'chip'
}) => {
  const getStatusIcon = () => {
    if (status.isConnecting) {
      return <CircularProgress size={16} />;
    } else if (status.isConnected) {
      return <ConnectedIcon fontSize="small" />;
    } else {
      return <DisconnectedIcon fontSize="small" />;
    }
  };

  const getStatusColor = (): 'success' | 'warning' | 'error' => {
    if (status.isConnecting) return 'warning';
    return status.isConnected ? 'success' : 'error';
  };

  const getStatusText = () => {
    if (status.isConnecting) return 'Connecting...';
    return status.isConnected ? 'Connected' : 'Disconnected';
  };

  const getTooltipContent = () => {
    let content = getStatusText();
    
    if (status.lastConnected && status.isConnected) {
      content += `\nLast connected: ${status.lastConnected.toLocaleTimeString()}`;
    }
    
    if (status.connectionError) {
      content += `\nError: ${status.connectionError}`;
    }
    
    return content;
  };

  if (variant === 'chip') {
    return (
      <Tooltip title={getTooltipContent()} arrow>
        <Chip
          icon={getStatusIcon()}
          label={getStatusText()}
          color={getStatusColor()}
          variant="outlined"
          size="small"
          sx={{
            cursor: 'help',
            '& .MuiChip-icon': {
              marginLeft: '8px'
            }
          }}
        />
      </Tooltip>
    );
  }

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        padding: 1,
        borderRadius: 1,
        backgroundColor: (theme) =>
          status.isConnected
            ? theme.palette.success.light
            : status.isConnecting
            ? theme.palette.warning.light
            : theme.palette.error.light,
        color: (theme) =>
          status.isConnected
            ? theme.palette.success.contrastText
            : status.isConnecting
            ? theme.palette.warning.contrastText
            : theme.palette.error.contrastText,
        opacity: 0.8
      }}
    >
      {getStatusIcon()}
      <Box>
        <Typography variant="body2" fontWeight="medium">
          {getStatusText()}
        </Typography>
        {showDetails && (
          <>
            {status.lastConnected && status.isConnected && (
              <Typography variant="caption" display="block">
                Connected at {status.lastConnected.toLocaleTimeString()}
              </Typography>
            )}
            {status.connectionError && !status.isConnected && (
              <Typography variant="caption" display="block" color="error">
                Error: {status.connectionError}
              </Typography>
            )}
          </>
        )}
      </Box>
    </Box>
  );
};