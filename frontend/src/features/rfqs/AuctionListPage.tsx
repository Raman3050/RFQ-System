import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import InputAdornment from '@mui/material/InputAdornment';
import LinearProgress from '@mui/material/LinearProgress';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { useAuth } from '@/features/auth/AuthContext';
import { LiveIndicator } from '@/features/realtime/LiveIndicator';
import { useLiveAuctions } from '@/features/realtime/useLiveAuctions';
import { formatDateTime } from '@/lib/datetime';

import { useRfqList } from './api';
import { Countdown, LiveStatusBadge, Money } from './components';
import { STATUS_LABEL, type RfqStatus } from './types';

const FILTERS: { label: string; statuses: RfqStatus[] }[] = [
  { label: 'All', statuses: [] },
  { label: STATUS_LABEL.ACTIVE, statuses: ['ACTIVE'] },
  { label: STATUS_LABEL.SCHEDULED, statuses: ['SCHEDULED'] },
  { label: 'Ended', statuses: ['CLOSED', 'FORCE_CLOSED'] },
  { label: STATUS_LABEL.CANCELLED, statuses: ['CANCELLED'] },
];

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function AuctionListPage() {
  const { user, hasRole } = useAuth();
  const isBuyer = hasRole('BUYER', 'ADMIN');
  const navigate = useNavigate();

  // Filters live in the URL so they survive reloads and can be shared.
  const [params, setParams] = useSearchParams();
  const filterIdx = Math.max(0, Number(params.get('f') ?? 0)) % FILTERS.length;
  const page = Math.max(1, Number(params.get('page') ?? 1));
  const [search, setSearch] = useState(params.get('q') ?? '');
  const q = useDebounced(search);
  const size = 20;

  const setParam = (updates: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        Object.entries(updates).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)));
        return next;
      },
      { replace: true },
    );

  useEffect(() => {
    if ((params.get('q') ?? '') !== q) setParam({ q: q || null, page: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const { data, isPending, isFetching, error } = useRfqList({
    status: FILTERS[filterIdx]?.statuses,
    q,
    sort: 'created_desc',
    page,
    size,
  });

  // Live close times / L1 prices for the rows on screen (ended auctions don't change).
  const liveIds = (data?.items ?? [])
    .filter((r) => r.status === 'SCHEDULED' || r.status === 'ACTIVE')
    .map((r) => r.id);
  const liveState = useLiveAuctions(liveIds);

  return (
    <Stack spacing={3}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        sx={{ justifyContent: 'space-between', alignItems: { sm: 'flex-end' } }}
      >
        <div>
          <Typography variant="h4" component="h1">
            British Auctions
          </Typography>
          {liveIds.length > 0 && <LiveIndicator state={liveState} />}
          <Typography color="text.secondary">
            {isBuyer
              ? `RFQs created by ${user?.company_name}`
              : 'RFQs you have been invited to quote on'}
          </Typography>
        </div>
        {isBuyer && (
          <Button component={Link} to="/rfqs/new" variant="contained" size="large">
            Create RFQ
          </Button>
        )}
      </Stack>

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        spacing={2}
        sx={{ alignItems: { md: 'center' } }}
      >
        <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1, flexGrow: 1 }}>
          {FILTERS.map((f, i) => (
            <Chip
              key={f.label}
              label={f.label}
              clickable
              color={i === filterIdx ? 'primary' : 'default'}
              variant={i === filterIdx ? 'filled' : 'outlined'}
              onClick={() => setParam({ f: i ? String(i) : null, page: null })}
            />
          ))}
        </Stack>
        <TextField
          size="small"
          placeholder="Search name or RFQ ID"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: { md: 280 } }}
          slotProps={{
            input: { startAdornment: <InputAdornment position="start">⌕</InputAdornment> },
            htmlInput: { 'aria-label': 'Search auctions' },
          }}
        />
      </Stack>

      {error && <Alert severity="error">Could not load auctions: {error.message}</Alert>}

      <Paper variant="outlined">
        <Box sx={{ height: 4 }}>{isFetching && <LinearProgress />}</Box>
        <TableContainer sx={{ overflowX: 'auto' }}>
          <Table sx={{ minWidth: 820 }} aria-label="Auctions">
            <TableHead>
              <TableRow>
                <TableCell>RFQ</TableCell>
                <TableCell align="right">Current lowest bid</TableCell>
                <TableCell>Current bid close</TableCell>
                <TableCell>Forced close</TableCell>
                <TableCell>Status</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data?.items.map((rfq) => (
                <TableRow
                  key={rfq.id}
                  hover
                  onClick={() => navigate(`/auctions/${rfq.id}`)}
                  sx={{ cursor: 'pointer' }}
                >
                  <TableCell>
                    <Typography
                      component={Link}
                      to={`/auctions/${rfq.id}`}
                      onClick={(e) => e.stopPropagation()}
                      sx={{ fontWeight: 600, color: 'text.primary', textDecoration: 'none' }}
                    >
                      {rfq.name}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {rfq.reference_id}
                      {!isBuyer && ` · ${rfq.buyer_company}`}
                      {!rfq.is_british_auction && ' · No auto-extension'}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Money amount={rfq.current_lowest_bid} currency={rfq.currency} />
                  </TableCell>
                  <TableCell>
                    <Stack>
                      <span>
                        {formatDateTime(rfq.current_close_at)}
                        {rfq.extension_count > 0 && (
                          <Tooltip title={`Extended ${rfq.extension_count} time(s)`}>
                            <Chip
                              label={`+${rfq.extension_count}`}
                              size="small"
                              color="warning"
                              sx={{ ml: 1, height: 20 }}
                            />
                          </Tooltip>
                        )}
                      </span>
                      <Countdown rfq={rfq} />
                    </Stack>
                  </TableCell>
                  <TableCell>{formatDateTime(rfq.forced_close_at)}</TableCell>
                  <TableCell>
                    <LiveStatusBadge rfq={rfq} />
                  </TableCell>
                </TableRow>
              ))}
              {!isPending && data?.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} sx={{ py: 6, textAlign: 'center' }}>
                    <Typography sx={{ fontWeight: 600 }}>No auctions found</Typography>
                    <Typography color="text.secondary" sx={{ mb: isBuyer ? 2 : 0 }}>
                      {q || filterIdx
                        ? 'Try a different filter or search.'
                        : isBuyer
                          ? 'Create your first RFQ to start an auction.'
                          : 'When a buyer invites you to an RFQ it will appear here.'}
                    </Typography>
                    {isBuyer && !q && !filterIdx && (
                      <Button component={Link} to="/rfqs/new" variant="outlined">
                        Create RFQ
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        {data && data.total > size && (
          <TablePagination
            component="div"
            count={data.total}
            page={page - 1}
            rowsPerPage={size}
            rowsPerPageOptions={[size]}
            onPageChange={(_, p) => setParam({ page: p ? String(p + 1) : null })}
          />
        )}
      </Paper>
    </Stack>
  );
}
