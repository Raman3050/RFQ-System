import Alert from '@mui/material/Alert';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { useReadiness } from '@/api/health';

export function SystemStatusPage() {
  const { data, isPending, isError, error } = useReadiness();

  return (
    <Stack spacing={3}>
      <Typography variant="h4" component="h1">
        System status
      </Typography>

      {isPending && <CircularProgress aria-label="Loading status" />}

      {isError && <Alert severity="error">API unreachable: {error.message}</Alert>}

      {data && (
        <Paper variant="outlined" sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <Typography sx={{ fontWeight: 600 }}>Overall</Typography>
              <Chip
                label={data.status}
                color={data.status === 'ok' ? 'success' : 'warning'}
                size="small"
              />
            </Stack>
            {Object.entries(data.checks).map(([name, check]) => (
              <Stack key={name} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                <Typography sx={{ minWidth: 100, textTransform: 'capitalize' }}>{name}</Typography>
                <Chip
                  label={check.status === 'ok' ? 'ok' : (check.error ?? 'error')}
                  color={check.status === 'ok' ? 'success' : 'error'}
                  size="small"
                  variant="outlined"
                />
              </Stack>
            ))}
            {Object.entries(data.workers ?? {}).map(([name, w]) => (
              <Stack key={name} direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                <Typography sx={{ minWidth: 100, textTransform: 'capitalize' }}>
                  {name} worker
                </Typography>
                <Chip
                  label={
                    w.status === 'ok'
                      ? `ok · ${w.seconds_ago ?? 0}s ago`
                      : w.status === 'stale'
                        ? `stale · ${w.seconds_ago}s ago`
                        : w.status
                  }
                  color={
                    w.status === 'ok' ? 'success' : w.status === 'unknown' ? 'default' : 'warning'
                  }
                  size="small"
                  variant="outlined"
                />
              </Stack>
            ))}
            <Typography variant="body2" color="text.secondary">
              Server time: {new Date(data.server_time).toLocaleString()}
            </Typography>
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
