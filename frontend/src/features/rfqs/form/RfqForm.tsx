import { zodResolver } from '@hookform/resolvers/zod';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import FormControlLabel from '@mui/material/FormControlLabel';
import Grid from '@mui/material/Grid';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Radio from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Typography from '@mui/material/Typography';
import { useMemo, useState, type ReactNode } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';

import { ApiError, fieldErrors } from '@/api/client';
import { EmailChipsField } from '@/components/EmailChipsField';
import { FormTextField } from '@/components/FormTextField';
import { formatMinutes, localTimeZone } from '@/lib/datetime';

import { CURRENCIES, TRIGGER_LABEL, type TriggerType } from '../types';
import { auctionPreview, rfqFormSchema, type RfqFormValues } from './schema';

const FORM_FIELDS = new Set<keyof RfqFormValues>([
  'name',
  'bid_start_at',
  'bid_close_at',
  'forced_close_at',
  'pickup_date',
  'currency',
  'trigger_window_minutes',
  'extension_minutes',
  'trigger_type',
  'supplier_emails',
]);

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
      <Typography variant="h6" component="h2">
        {title}
      </Typography>
      {subtitle && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {subtitle}
        </Typography>
      )}
      <Box sx={{ mt: subtitle ? 0 : 2 }}>{children}</Box>
    </Paper>
  );
}

interface Props {
  mode: 'create' | 'edit';
  defaultValues: RfqFormValues;
  submitLabel: string;
  onSubmit: (values: RfqFormValues) => Promise<void>;
  onCancel: () => void;
}

export function RfqForm({ mode, defaultValues, submitLabel, onSubmit, onCancel }: Props) {
  const [formError, setFormError] = useState<string | null>(null);
  const schema = useMemo(
    () => rfqFormSchema({ mode, originalStart: defaultValues.bid_start_at }),
    [mode, defaultValues.bid_start_at],
  );
  const {
    control,
    handleSubmit,
    setError,
    formState: { isSubmitting },
  } = useForm<RfqFormValues>({ resolver: zodResolver(schema), defaultValues, mode: 'onTouched' });

  const values = useWatch({ control }) as RfqFormValues;
  const preview = auctionPreview(values);

  const submit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      await onSubmit(v);
    } catch (err) {
      const byField = fieldErrors(err);
      const mapped = Object.entries(byField).filter(([f]) =>
        FORM_FIELDS.has(f as keyof RfqFormValues),
      );
      mapped.forEach(([f, msg]) => setError(f as keyof RfqFormValues, { message: msg }));
      if (mapped.length === 0) {
        setFormError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.');
      } else {
        setFormError('Please fix the highlighted fields.');
      }
    }
  });

  return (
    <form onSubmit={submit} noValidate>
      <Stack spacing={3}>
        {formError && <Alert severity="error">{formError}</Alert>}

        <Section title="RFQ details">
          <Grid container spacing={2}>
            <Grid size={{ xs: 12, md: 8 }}>
              <FormTextField
                name="name"
                control={control}
                label="RFQ name"
                placeholder="e.g. Mumbai → Delhi FTL, 20T container"
                autoFocus={mode === 'create'}
              />
            </Grid>
            <Grid size={{ xs: 6, md: 2 }}>
              <FormTextField name="currency" control={control} label="Currency" select>
                {CURRENCIES.map((c) => (
                  <MenuItem key={c} value={c}>
                    {c}
                  </MenuItem>
                ))}
              </FormTextField>
            </Grid>
            <Grid size={{ xs: 6, md: 2 }}>
              <FormTextField
                name="pickup_date"
                control={control}
                label="Pickup / service date"
                type="date"
                slotProps={{ inputLabel: { shrink: true } }}
              />
            </Grid>
          </Grid>
        </Section>

        <Section
          title="Bidding schedule"
          subtitle={`Times are in your local time zone (${localTimeZone()}).`}
        >
          <Grid container spacing={2}>
            {(
              [
                ['bid_start_at', 'Bid start', undefined],
                ['bid_close_at', 'Bid close', 'Auction may be extended past this'],
                ['forced_close_at', 'Forced bid close', 'Hard stop — never extended beyond'],
              ] as const
            ).map(([name, label, help]) => (
              <Grid key={name} size={{ xs: 12, md: 4 }}>
                <FormTextField
                  name={name}
                  control={control}
                  label={label}
                  type="datetime-local"
                  helperText={help}
                  slotProps={{ inputLabel: { shrink: true } }}
                />
              </Grid>
            ))}
          </Grid>
        </Section>

        <Section title="British Auction">
          <Controller
            name="is_british_auction"
            control={control}
            render={({ field }) => (
              <FormControlLabel
                control={<Switch checked={field.value} onChange={(_, c) => field.onChange(c)} />}
                label="Automatically extend the auction when there is late bidding activity"
              />
            )}
          />

          {values.is_british_auction && (
            <Stack spacing={2} sx={{ mt: 2 }}>
              <Grid container spacing={2}>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <FormTextField
                    name="trigger_window_minutes"
                    control={control}
                    label="Trigger window (X minutes)"
                    type="number"
                    helperText="Watch activity in the last X minutes before close"
                    slotProps={{ htmlInput: { min: 1, max: 1440 } }}
                  />
                </Grid>
                <Grid size={{ xs: 12, sm: 6 }}>
                  <FormTextField
                    name="extension_minutes"
                    control={control}
                    label="Extension duration (Y minutes)"
                    type="number"
                    helperText="Add Y minutes to the close time when triggered"
                    slotProps={{ htmlInput: { min: 1, max: 1440 } }}
                  />
                </Grid>
              </Grid>

              <Controller
                name="trigger_type"
                control={control}
                render={({ field }) => (
                  <RadioGroup
                    value={field.value}
                    onChange={(_, v) => field.onChange(v as TriggerType)}
                    aria-label="Extension trigger"
                  >
                    <Typography variant="subtitle2" sx={{ mb: 1 }}>
                      Extend when…
                    </Typography>
                    {(Object.keys(TRIGGER_LABEL) as TriggerType[]).map((t) => (
                      <FormControlLabel
                        key={t}
                        value={t}
                        control={<Radio />}
                        sx={{ alignItems: 'flex-start', mb: 1, '& .MuiRadio-root': { pt: 0.5 } }}
                        label={
                          <Box>
                            <Typography sx={{ fontWeight: 600 }}>
                              {TRIGGER_LABEL[t].title}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {TRIGGER_LABEL[t].description}
                            </Typography>
                          </Box>
                        }
                      />
                    ))}
                  </RadioGroup>
                )}
              />

              {preview && (
                <Alert severity="info" variant="outlined">
                  Bidding runs for <b>{formatMinutes(preview.biddingMinutes)}</b>. Late activity can
                  extend it by {formatMinutes(Number(values.extension_minutes) || 0)} at a time, up
                  to <b>{formatMinutes(preview.bufferMinutes)}</b> past the original close (≈{' '}
                  {preview.maxExtensions} extension
                  {preview.maxExtensions === 1 ? '' : 's'}), and never beyond the forced close.
                </Alert>
              )}
            </Stack>
          )}
        </Section>

        {mode === 'create' && (
          <Section
            title="Invite suppliers"
            subtitle="Suppliers join by invitation only. New emails get a sign-up link; existing suppliers are notified. You can invite more later."
          >
            <Controller
              name="supplier_emails"
              control={control}
              render={({ field, fieldState }) => (
                <EmailChipsField
                  value={field.value}
                  onChange={field.onChange}
                  error={!!fieldState.error}
                  helperText={
                    fieldState.error?.message ??
                    (Array.isArray(fieldState.error)
                      ? fieldState.error.find(Boolean)?.message
                      : undefined) ??
                    'Separate with commas, spaces or Enter. You can paste a list.'
                  }
                />
              )}
            />
          </Section>
        )}

        <Stack direction="row" spacing={2} sx={{ justifyContent: 'flex-end' }}>
          <Button onClick={onCancel} disabled={isSubmitting}>
            Back
          </Button>
          <Button type="submit" variant="contained" size="large" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : submitLabel}
          </Button>
        </Stack>
      </Stack>
    </form>
  );
}
