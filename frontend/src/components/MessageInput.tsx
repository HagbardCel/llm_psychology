import { useState, useRef, KeyboardEvent } from 'react';
import {
  Box,
  TextField,
  IconButton,
  Paper,
  CircularProgress,
} from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import MicIcon from '@mui/icons-material/Mic';
import AttachFileIcon from '@mui/icons-material/AttachFile';

interface MessageInputProps {
  onSendMessage: (message: string) => void;
  disabled?: boolean;
  isLoading?: boolean;
  placeholder?: string;
}

export function MessageInput({
  onSendMessage,
  disabled = false,
  isLoading = false,
  placeholder = "Type your message...",
}: MessageInputProps) {
  const [message, setMessage] = useState('');
  const textFieldRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    if (message.trim() && !disabled && !isLoading) {
      onSendMessage(message.trim());
      setMessage('');
    }
  };

  const handleKeyPress = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  const handleVoiceInput = () => {
    // TODO: Implement voice input functionality
    console.log('Voice input not yet implemented');
  };

  const handleFileAttach = () => {
    // TODO: Implement file attachment functionality
    console.log('File attachment not yet implemented');
  };

  return (
    <Paper
      elevation={3}
      sx={{
        p: 2,
        borderTop: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'flex-end', gap: 1 }}>
        <IconButton
          onClick={handleFileAttach}
          disabled={disabled || isLoading}
          size="small"
          sx={{ mb: 0.5 }}
        >
          <AttachFileIcon />
        </IconButton>

        <TextField
          ref={textFieldRef}
          fullWidth
          multiline
          maxRows={4}
          variant="outlined"
          placeholder={placeholder}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyPress={handleKeyPress}
          disabled={disabled || isLoading}
          sx={{
            '& .MuiOutlinedInput-root': {
              borderRadius: 2,
            },
          }}
        />

        <IconButton
          onClick={handleVoiceInput}
          disabled={disabled || isLoading}
          size="small"
          sx={{ mb: 0.5 }}
        >
          <MicIcon />
        </IconButton>

        <IconButton
          onClick={handleSend}
          disabled={disabled || isLoading || !message.trim()}
          color="primary"
          size="large"
          sx={{
            mb: 0.5,
            bgcolor: 'primary.main',
            color: 'white',
            '&:hover': {
              bgcolor: 'primary.dark',
            },
            '&:disabled': {
              bgcolor: 'action.disabled',
              color: 'action.disabled',
            },
          }}
        >
          {isLoading ? (
            <CircularProgress size={20} color="inherit" />
          ) : (
            <SendIcon />
          )}
        </IconButton>
      </Box>

      {message.length > 500 && (
        <Box sx={{ mt: 1, textAlign: 'right' }}>
          <span style={{ color: message.length > 1000 ? 'red' : 'orange' }}>
            {message.length}/1000
          </span>
        </Box>
      )}
    </Paper>
  );
}