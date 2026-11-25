import Box from '@mui/material/Box';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import type { LiveState } from './liveClient';

const LABEL: Record<LiveState, { text: string; color: string; hint: string }> = {
  live: { text: 'Live', color: 'success.main', hint: 'Updates arrive instantly' },
  connecting: { text: 'Connecting…', color: 'warning.main', hint: 'Opening live connection' },
  reconnecting: {
    text: 'Reconnecting…',
    color: 'warning.main',
    hint: 'Live connection lost; refreshing periodically until it is back',
  },
  idle: { text: 'Offline', color: 'text.disabled', hint: 'Refreshing periodically' },
};

export function LiveIndicator({ state }: { state: LiveState }) {
  const l = LABEL[state];
  return (
    <Tooltip title={l.hint}>
      <Box
        role="status"
        aria-label={`Connection: ${l.text}`}
        sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}
      >
        <Box
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            bgcolor: l.color,
            ...(state === 'live' && {
              animation: 'livePulse 2s ease-in-out infinite',
              '@keyframes livePulse': { '50%': { opacity: 0.35 } },
            }),
          }}
        />
        <Typography variant="caption" color="text.secondary">
          {l.text}
        </Typography>
      </Box>
    </Tooltip>
  );
}
