import { TextField, MenuItem } from '@mui/material';

export interface FormFieldProps {
  label: string;
  type?: 'text' | 'email' | 'date' | 'number' | 'select';
  value: string;
  onChange: (value: string) => void;
  error?: string;
  required?: boolean;
  disabled?: boolean;
  helperText?: string;
  options?: Array<{ value: string; label: string }>;
  multiline?: boolean;
  rows?: number;
}

/**
 * FormField provides a consistent form input component.
 * Supports text, email, date, number, and select field types.
 *
 * @example
 * ```tsx
 * <FormField
 *   label="Name"
 *   value={name}
 *   onChange={setName}
 *   required
 *   error={errors.name}
 * />
 * ```
 */
export function FormField({
  label,
  type = 'text',
  value,
  onChange,
  error,
  required,
  disabled,
  helperText,
  options,
  multiline,
  rows
}: FormFieldProps) {
  if (type === 'select' && options) {
    return (
      <TextField
        select
        fullWidth
        label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        disabled={disabled}
        error={Boolean(error)}
        helperText={error || helperText}
        margin="normal"
      >
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {option.label}
          </MenuItem>
        ))}
      </TextField>
    );
  }

  return (
    <TextField
      fullWidth
      label={label}
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required={required}
      disabled={disabled}
      error={Boolean(error)}
      helperText={error || helperText}
      margin="normal"
      multiline={multiline}
      rows={rows}
      InputLabelProps={type === 'date' ? { shrink: true } : undefined}
    />
  );
}
