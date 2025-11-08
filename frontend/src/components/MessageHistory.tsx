import { useEffect, useRef } from 'react';
import {
  Box,
  Paper,
  Typography,
  Avatar,
  Stack,
  Chip,
} from '@mui/material';
import { format } from 'date-fns';
import { Message } from '../types';
import PersonIcon from '@mui/icons-material/Person';
import PsychologyIcon from '@mui/icons-material/Psychology';

interface MessageHistoryProps {
  messages: Message[];
  isLoading?: boolean;
  streamingMessage?: string;
  isStreaming?: boolean;
}

export function MessageHistory({
  messages,
  isLoading = false,
  streamingMessage = '',
  isStreaming = false
}: MessageHistoryProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingMessage]);

  return (
    <Box
      sx={{
        height: '100%',
        overflowY: 'auto',
        padding: 2,
        backgroundColor: '#f5f5f5',
      }}
    >
      <Stack spacing={2}>
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {/* Show streaming message in real-time */}
        {isStreaming && streamingMessage && (
          <StreamingMessageBubble content={streamingMessage} />
        )}

        {isLoading && !isStreaming && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
            <Chip
              label="Agent is typing..."
              variant="outlined"
              color="primary"
              sx={{ animation: 'pulse 2s infinite' }}
            />
          </Box>
        )}

        <div ref={messagesEndRef} />
      </Stack>
    </Box>
  );
}

interface MessageBubbleProps {
  message: Message;
}

function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.sender === 'user';

  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        mb: 1,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          flexDirection: isUser ? 'row-reverse' : 'row',
          alignItems: 'flex-start',
          maxWidth: '70%',
          gap: 1,
        }}
      >
        <Avatar
          sx={{
            width: 32,
            height: 32,
            bgcolor: isUser ? 'primary.main' : 'secondary.main',
          }}
        >
          {isUser ? <PersonIcon /> : <PsychologyIcon />}
        </Avatar>

        <Paper
          elevation={1}
          sx={{
            p: 2,
            backgroundColor: isUser ? 'primary.light' : 'white',
            color: isUser ? 'primary.contrastText' : 'text.primary',
            borderRadius: 2,
            borderTopLeftRadius: isUser ? 2 : 0.5,
            borderTopRightRadius: isUser ? 0.5 : 2,
          }}
        >
          <Typography
            variant="body1"
            sx={{
              whiteSpace: 'pre-wrap',
              wordWrap: 'break-word',
            }}
          >
            {message.content}
          </Typography>

          <Typography
            variant="caption"
            sx={{
              display: 'block',
              mt: 1,
              opacity: 0.7,
              textAlign: isUser ? 'right' : 'left',
            }}
          >
            {format(new Date(message.timestamp), 'HH:mm')}
          </Typography>
        </Paper>
      </Box>
    </Box>
  );
}

interface StreamingMessageBubbleProps {
  content: string;
}

function StreamingMessageBubble({ content }: StreamingMessageBubbleProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'flex-start',
        mb: 1,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'flex-start',
          maxWidth: '70%',
          gap: 1,
        }}
      >
        <Avatar
          sx={{
            width: 32,
            height: 32,
            bgcolor: 'secondary.main',
          }}
        >
          <PsychologyIcon />
        </Avatar>

        <Paper
          elevation={1}
          sx={{
            p: 2,
            backgroundColor: 'white',
            color: 'text.primary',
            borderRadius: 2,
            borderTopLeftRadius: 0.5,
            borderTopRightRadius: 2,
            position: 'relative',
            '&::after': {
              content: '""',
              position: 'absolute',
              right: 8,
              bottom: 8,
              width: 8,
              height: 8,
              backgroundColor: 'secondary.main',
              borderRadius: '50%',
              animation: 'blink 1s infinite',
            },
            '@keyframes blink': {
              '0%, 100%': { opacity: 1 },
              '50%': { opacity: 0.3 },
            },
          }}
        >
          <Typography
            variant="body1"
            sx={{
              whiteSpace: 'pre-wrap',
              wordWrap: 'break-word',
            }}
          >
            {content}
          </Typography>

          <Typography
            variant="caption"
            sx={{
              display: 'block',
              mt: 1,
              opacity: 0.7,
              fontStyle: 'italic',
            }}
          >
            Streaming...
          </Typography>
        </Paper>
      </Box>
    </Box>
  );
}