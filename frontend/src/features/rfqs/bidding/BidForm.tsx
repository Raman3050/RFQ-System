import { zodResolver } from '@hookform/resolvers/zod';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import InputAdornment from '@mui/material/InputAdornment';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useMemo, useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { z } from 'zod';

import { ApiError, fieldErrors } from '@/api/client';
import { FormTextField } from '@/components/FormTextField';
import { useAuth } from '@/features/auth/AuthContext';
import { formatMoney } from '@/lib/money';
import { formatDate, formatDateTime, toLocalDate } from '@/lib/datetime';

import { useSubmitBid } from '../api';
import type { BidResult, Leaderboard, RfqDetail } from '../types';

const MONEY = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,2})?$/, 'Amount with up to 2 decimals');

const cents = (v: string) => Math.round(Number(v || 0) * 100);

function bidSchema(currentTotal: string | null, pickupDate: string) {
  return z
    .object({
      carrier_name: z.string().trim().min(1, 'Required').max(120),
      freight_charges: MONEY,
      origin_charges: MONEY,
      destination_charges: MONEY,
      transit_time_days: z
        .string()
        .regex(/^\d+$/, 'Whole days')
        .refine((v) => Number(v) >= 1 && Number(v) <= 365, '1 to 365 days'),
      quote_validity_until: z
        .string()
        .min(1, 'Required')
        .refine((v) => v >= toLocalDate(new Date()), 'Cannot be in the past')
        // A quote that lapses before pickup could be repriced after winning.
        .refine(
          (v) => v >= pickupDate,
          `Must be valid at least until the pickup date (${formatDate(pickupDate)})`,
        ),
    })
    .superRefine((v, ctx) => {
      const total =
        cents(v.freight_charges) + cents(v.origin_charges) + cents(v.destination_charges);
      if (total <= 0) {
        ctx.addIssue({
          code: 'custom',
          path: ['freight_charges'],
          message: 'Total must be above 0',
        });
      } else if (currentTotal !== null && total >= cents(currentTotal)) {
        ctx.addIssue({
          code: 'custom',
          path: ['freight_charges'],
          message: 'Your new total must be lower than your current bid',
        });
      }
    });
}

type BidForm = z.infer<ReturnType<typeof bidSchema>>;
const FIELDS: (keyof BidForm)[] = [
  'carrier_name',
  'freight_charges',
  'origin_charges',
  'destination_charges',
  'transit_time_days',
  'quote_validity_until',
];

function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Quote submission form for an invited supplier while the auction is active. */
export function BidForm({ rfq, board }: { rfq: RfqDetail; board: Leaderboard }) {
  const { user } = useAuth();
  const submit = useSubmitBid(rfq.id);
  const [result, setResult] = useState<BidResult | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const mine = board.entries.find((e) => e.is_you);
  const l1 = board.entries[0];
  const schema = useMemo(
    () => bidSchema(board.my_current_total, rfq.pickup_date),
    [board.my_current_total, rfq.pickup_date],
  );

  // Computed once (not on every render): 14 days from today, but never before pickup.
  const [defaultValidity] = useState(() => {
    const inTwoWeeks = toLocalDate(new Date(Date.now() + 14 * 86_400_000));
    return inTwoWeeks > rfq.pickup_date ? inTwoWeeks : rfq.pickup_date;
  });
  const defaults: BidForm = {
    carrier_name: mine?.carrier_name ?? user?.company_name ?? '',
    freight_charges: '',
    origin_charges: '0',
    destination_charges: '0',
    transit_time_days: String(mine?.transit_time_days ?? 3),
    quote_validity_until: mine?.quote_validity_until ?? defaultValidity,
  };
  const { control, handleSubmit, setError, reset } = useForm<BidForm>({
    resolver: zodResolver(schema),
    defaultValues: defaults,
  });
  const v = useWatch({ control });
  const totalCents =
    cents(v.freight_charges ?? '') +
    cents(v.origin_charges ?? '') +
    cents(v.destination_charges ?? '');
  const money = (n: number | string) => formatMoney(n, rfq.currency);

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    setResult(null);
    try {
      const res = await submit.mutateAsync({
        input: { ...values, transit_time_days: Number(values.transit_time_days) },
        idempotencyKey: newKey(),
      });
      setResult(res);
      reset({ ...values, freight_charges: '', origin_charges: '0', destination_charges: '0' });
    } catch (err) {
      const byField = fieldErrors(err);
      const known = FIELDS.filter((f) => byField[f]);
      known.forEach((f) => setError(f, { message: byField[f] }));
      if (!known.length) {
        setFormError(err instanceof ApiError ? err.message : 'Could not submit your bid.');
      }
    }
  });

  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 }, borderColor: 'primary.main' }}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        sx={{ justifyContent: 'space-between', gap: 1, mb: 2 }}
      >
        <div>
          <Typography variant="h6" component="h2">
            {mine ? 'Lower your bid' : 'Submit your quote'}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {mine
              ? `You are ${mine.label} with ${money(mine.total_amount)}. A new bid must be lower.`
              : 'Your quote is ranked by its total charges. You can lower it any time before close.'}
          </Typography>
        </div>
        {l1 && (
          <Box sx={{ textAlign: { sm: 'right' } }}>
            <Typography variant="caption" color="text.secondary">
              CURRENT L1
            </Typography>
            <Typography variant="h6" sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {money(l1.total_amount)}
            </Typography>
          </Box>
        )}
      </Stack>

      {result && (
        <Alert
          severity={result.rank === 1 ? 'success' : 'info'}
          sx={{ mb: 2 }}
          onClose={() => setResult(null)}
        >
          Bid of <b>{money(result.bid.total_amount)}</b> placed — you are <b>L{result.rank}</b> of{' '}
          {result.total_bidders}.
          {result.extension && (
            <>
              {' '}
              Auction extended to <b>{formatDateTime(result.extension.new_close_at)}</b> (
              {result.extension.reason.toLowerCase()}
              {result.extension.capped && ', reached the forced close'}).
            </>
          )}
        </Alert>
      )}
      {formError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {formError}
        </Alert>
      )}

      <form onSubmit={onSubmit} noValidate>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <FormTextField name="carrier_name" control={control} label="Carrier name" />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <FormTextField
              name="transit_time_days"
              control={control}
              label="Transit time"
              type="number"
              slotProps={{
                input: { endAdornment: <InputAdornment position="end">days</InputAdornment> },
                htmlInput: { min: 1, max: 365 },
              }}
            />
          </Grid>
          <Grid size={{ xs: 6, md: 3 }}>
            <FormTextField
              name="quote_validity_until"
              control={control}
              label="Quote valid until"
              type="date"
              helperText={`Must cover pickup (${formatDate(rfq.pickup_date)})`}
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Grid>
          {(
            [
              ['freight_charges', 'Freight charges'],
              ['origin_charges', 'Origin charges'],
              ['destination_charges', 'Destination charges'],
            ] as const
          ).map(([name, label]) => (
            <Grid key={name} size={{ xs: 12, sm: 4 }}>
              <FormTextField
                name={name}
                control={control}
                label={label}
                inputMode="decimal"
                slotProps={{
                  input: {
                    startAdornment: (
                      <InputAdornment position="start">{rfq.currency}</InputAdornment>
                    ),
                  },
                }}
              />
            </Grid>
          ))}
        </Grid>
        <Divider sx={{ my: 2 }} />
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          sx={{ justifyContent: 'space-between', alignItems: { sm: 'center' } }}
        >
          <Typography>
            Total:{' '}
            <Box component="b" sx={{ fontSize: 20, fontVariantNumeric: 'tabular-nums' }}>
              {money(totalCents / 100)}
            </Box>
            {l1 && totalCents > 0 && (
              <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                {totalCents < cents(l1.total_amount) || l1.is_you
                  ? '→ would be L1'
                  : `${money((totalCents - cents(l1.total_amount)) / 100)} above L1`}
              </Typography>
            )}
          </Typography>
          <Button type="submit" variant="contained" size="large" disabled={submit.isPending}>
            {submit.isPending ? 'Submitting…' : mine ? 'Submit lower bid' : 'Submit bid'}
          </Button>
        </Stack>
      </form>
    </Paper>
  );
}
