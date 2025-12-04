import { ReactNode } from 'react';
import { Container, Box, Typography } from '@mui/material';

export interface PageContainerProps {
  title: string;
  subtitle?: string;
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl';
  children: ReactNode;
  action?: ReactNode;
}

/**
 * PageContainer provides a consistent layout for all pages.
 * Includes title, optional subtitle, and optional header action.
 *
 * @example
 * ```tsx
 * <PageContainer title="Profile" subtitle="Edit your information" maxWidth="sm">
 *   <form>...</form>
 * </PageContainer>
 * ```
 */
export function PageContainer({
  title,
  subtitle,
  maxWidth = 'md',
  children,
  action
}: PageContainerProps) {
  return (
    <Container maxWidth={maxWidth} sx={{ py: 4 }}>
      <Box
        sx={{
          mb: 4,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start'
        }}
      >
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            {title}
          </Typography>
          {subtitle && (
            <Typography variant="body1" color="text.secondary">
              {subtitle}
            </Typography>
          )}
        </Box>
        {action && <Box>{action}</Box>}
      </Box>
      {children}
    </Container>
  );
}
