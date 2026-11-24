import Autocomplete from '@mui/material/Autocomplete';
import Chip from '@mui/material/Chip';
import TextField from '@mui/material/TextField';
import { useState } from 'react';

import { EMAIL_RE, splitEmails } from '@/lib/emails';

interface Props {
  value: string[];
  onChange: (emails: string[]) => void;
  label?: string;
  placeholder?: string;
  error?: boolean;
  helperText?: string;
  disabled?: boolean;
}

/**
 * Multi-email input: type or paste addresses separated by comma, space or Enter.
 * Invalid addresses stay visible as red chips so the user can fix them.
 */
export function EmailChipsField({
  value,
  onChange,
  label = 'Supplier emails',
  placeholder = 'name@carrier.com',
  error,
  helperText,
  disabled,
}: Props) {
  const [input, setInput] = useState('');

  const commit = (raw: string) => {
    const add = splitEmails(raw).filter((e) => !value.includes(e));
    if (add.length) onChange([...value, ...add]);
    setInput('');
  };

  return (
    <Autocomplete
      multiple
      freeSolo
      options={[]}
      value={value}
      disabled={disabled}
      inputValue={input}
      onInputChange={(_, v, reason) => {
        if (reason === 'reset') return;
        if (/[\s,;]$/.test(v)) commit(v);
        else setInput(v);
      }}
      onChange={(_, next) => onChange(splitEmails((next as string[]).join(',')))}
      renderValue={(emails, getItemProps) =>
        emails.map((email, index) => {
          const { key, ...itemProps } = getItemProps({ index });
          return (
            <Chip
              key={key}
              {...itemProps}
              label={email}
              size="small"
              color={EMAIL_RE.test(email) ? 'default' : 'error'}
              variant={EMAIL_RE.test(email) ? 'filled' : 'outlined'}
            />
          );
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={value.length ? '' : placeholder}
          error={error}
          helperText={helperText}
          onBlur={() => input && commit(input)}
          onPaste={(e) => {
            const text = e.clipboardData.getData('text');
            if (/[\s,;]/.test(text.trim())) {
              e.preventDefault();
              commit(input + text);
            }
          }}
        />
      )}
    />
  );
}
