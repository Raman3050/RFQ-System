import TextField, { type TextFieldProps } from '@mui/material/TextField';
import { Controller, type Control, type FieldPath, type FieldValues } from 'react-hook-form';

type Props<T extends FieldValues> = Omit<TextFieldProps, 'name' | 'value' | 'onChange'> & {
  name: FieldPath<T>;
  control: Control<T>;
};

/**
 * MUI TextField bound to react-hook-form as a *controlled* input, so values set
 * programmatically (setValue/reset) render correctly, including the floating label.
 * Shows the field's validation message, falling back to `helperText`.
 */
export function FormTextField<T extends FieldValues>({
  name,
  control,
  helperText,
  ...props
}: Props<T>) {
  return (
    <Controller
      name={name}
      control={control}
      render={({ field, fieldState }) => (
        <TextField
          {...props}
          {...field}
          value={field.value ?? ''}
          inputRef={field.ref}
          error={!!fieldState.error}
          helperText={fieldState.error?.message ?? helperText}
          fullWidth={props.fullWidth ?? true}
        />
      )}
    />
  );
}
