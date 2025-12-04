import { ReactNode } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button
} from '@mui/material';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string | ReactNode;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void;
  onCancel: () => void;
  severity?: 'info' | 'warning' | 'error';
  confirmColor?: 'primary' | 'error' | 'warning';
}

/**
 * ConfirmDialog displays a confirmation dialog for important actions.
 * Supports different severity levels with appropriate icons.
 *
 * @example
 * ```tsx
 * <ConfirmDialog
 *   open={showDialog}
 *   title="Delete Session?"
 *   message="This action cannot be undone."
 *   severity="error"
 *   confirmColor="error"
 *   onConfirm={handleDelete}
 *   onCancel={() => setShowDialog(false)}
 * />
 * ```
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  onConfirm,
  onCancel,
  severity = 'info',
  confirmColor = 'primary'
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-description"
    >
      <DialogTitle id="confirm-dialog-title">
        {severity === 'error' && (
          <ErrorIcon
            color="error"
            sx={{ mr: 1, verticalAlign: 'middle' }}
          />
        )}
        {severity === 'warning' && (
          <WarningIcon
            color="warning"
            sx={{ mr: 1, verticalAlign: 'middle' }}
          />
        )}
        {title}
      </DialogTitle>
      <DialogContent>
        <DialogContentText id="confirm-dialog-description">
          {message}
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel} color="inherit">
          {cancelText}
        </Button>
        <Button onClick={onConfirm} color={confirmColor} variant="contained" autoFocus>
          {confirmText}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
