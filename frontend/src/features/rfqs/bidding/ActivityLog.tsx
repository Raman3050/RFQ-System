import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { formatDateTime } from '@/lib/datetime';

import { useActivity } from '../api';
import { DOT, describeEvent } from './describeEvent';
import type { Currency } from '../types';

/** Activity log (spec §8): bid submissions, time extensions and the reason for each. */
export function ActivityLog({
  rfqId,
  currency,
  live,
}: {
  rfqId: string;
  currency: Currency;
  live: boolean;
}) {
  const { data, isPending, fetchNextPage, hasNextPage, isFetchingNextPage } = useActivity(
    rfqId,
    live,
  );
  const events = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
      <Typography variant="h6" component="h2" sx={{ mb: 2 }}>
        Activity log
      </Typography>
      {isPending ? (
        <Typography color="text.secondary">Loading…</Typography>
      ) : events.length === 0 ? (
        <Typography color="text.secondary">No activity yet.</Typography>
      ) : (
        <Stack
          component="ol"
          spacing={0}
          sx={{ listStyle: 'none', p: 0, m: 0 }}
          aria-label="Activity log"
        >
          {events.map((e) => {
            const { tone, text } = describeEvent(e, currency);
            return (
              <Stack
                component="li"
                key={e.id}
                direction="row"
                spacing={2}
                sx={{ py: 1.25, borderBottom: 1, borderColor: 'divider' }}
              >
                <Box
                  sx={{
                    mt: 0.75,
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    bgcolor: DOT[tone],
                    flexShrink: 0,
                  }}
                />
                <Box sx={{ flexGrow: 1 }}>
                  <Typography component="div">{text}</Typography>
                </Box>
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}
                >
                  {formatDateTime(e.created_at)}
                </Typography>
              </Stack>
            );
          })}
        </Stack>
      )}
      {hasNextPage && (
        <Button sx={{ mt: 1 }} onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
          {isFetchingNextPage ? 'Loading…' : 'Show older activity'}
        </Button>
      )}
    </Paper>
  );
}
