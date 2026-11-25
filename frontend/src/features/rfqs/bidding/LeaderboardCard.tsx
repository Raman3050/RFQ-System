import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';

import { formatDate, formatDateTime } from '@/lib/datetime';

import { Money } from '../components';
import type { Leaderboard } from '../types';

function RankChip({ label, rank }: { label: string; rank: number }) {
  return (
    <Chip
      label={label}
      size="small"
      color={rank === 1 ? 'success' : 'default'}
      variant={rank === 1 ? 'filled' : 'outlined'}
      sx={{ fontWeight: 700, minWidth: 44 }}
    />
  );
}

const hidden = (
  <Typography component="span" color="text.disabled">
    —
  </Typography>
);

/**
 * Supplier bids sorted by price with L1, L2, … ranking and quote details (spec §8).
 * For suppliers, competitors appear as "Bidder N" without their charge breakdown.
 */
export function LeaderboardCard({
  board,
  viewerIsBuyer,
}: {
  board: Leaderboard;
  viewerIsBuyer: boolean;
}) {
  const { entries, currency } = board;
  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack
        direction="row"
        sx={{ justifyContent: 'space-between', alignItems: 'baseline', mb: 2, gap: 2 }}
      >
        <Typography variant="h6" component="h2">
          Bids
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {entries.length} supplier{entries.length === 1 ? '' : 's'} bidding
          {!viewerIsBuyer && ' · competitors are anonymised'}
        </Typography>
      </Stack>

      {entries.length === 0 ? (
        <Box sx={{ py: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">No bids yet.</Typography>
        </Box>
      ) : (
        <TableContainer sx={{ overflowX: 'auto' }}>
          <Table size="small" sx={{ minWidth: 880 }} aria-label="Ranked bids">
            <TableHead>
              <TableRow>
                <TableCell>Rank</TableCell>
                <TableCell>Supplier</TableCell>
                <TableCell>Carrier</TableCell>
                <TableCell align="right">Freight</TableCell>
                <TableCell align="right">Origin</TableCell>
                <TableCell align="right">Destination</TableCell>
                <TableCell align="right">Total</TableCell>
                <TableCell align="right">Transit</TableCell>
                <TableCell>Valid until</TableCell>
                <TableCell>Last bid</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {entries.map((e) => (
                <TableRow
                  key={e.rank}
                  selected={e.is_you}
                  sx={e.rank === 1 ? { '& td': { fontWeight: 600 } } : undefined}
                >
                  <TableCell>
                    <RankChip label={e.label} rank={e.rank} />
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                      <span>{e.supplier_label}</span>
                      {e.is_you && <Chip label="You" size="small" color="primary" />}
                    </Stack>
                    {e.supplier_name && (
                      <Typography variant="body2" color="text.secondary">
                        {e.supplier_name}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>{e.carrier_name ?? hidden}</TableCell>
                  <TableCell align="right">
                    {e.freight_charges ? (
                      <Money amount={e.freight_charges} currency={currency} plain />
                    ) : (
                      hidden
                    )}
                  </TableCell>
                  <TableCell align="right">
                    {e.origin_charges ? (
                      <Money amount={e.origin_charges} currency={currency} plain />
                    ) : (
                      hidden
                    )}
                  </TableCell>
                  <TableCell align="right">
                    {e.destination_charges ? (
                      <Money amount={e.destination_charges} currency={currency} plain />
                    ) : (
                      hidden
                    )}
                  </TableCell>
                  <TableCell align="right">
                    <Money amount={e.total_amount} currency={currency} />
                  </TableCell>
                  <TableCell align="right">{e.transit_time_days} d</TableCell>
                  <TableCell>
                    {e.quote_validity_until ? formatDate(e.quote_validity_until) : hidden}
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{formatDateTime(e.last_bid_at)}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {e.bid_count} bid{e.bid_count === 1 ? '' : 's'}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Paper>
  );
}
