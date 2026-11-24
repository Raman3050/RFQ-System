import Chip from '@mui/material/Chip';
import Grid from '@mui/material/Grid';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

import { useAuth } from '@/features/auth/AuthContext';
import { ROLE_LABEL } from '@/features/auth/types';

interface Card {
  title: string;
  body: string;
  phase: number;
}

const BUYER_CARDS: Card[] = [
  {
    title: 'Create an RFQ',
    body: 'Set bid start, close and forced-close times, plus the auction trigger window (X) and extension (Y).',
    phase: 2,
  },
  {
    title: 'Watch auctions live',
    body: 'See the L1/L2/L3 leaderboard, every quote, and each automatic time extension with its reason.',
    phase: 3,
  },
  {
    title: 'Measure savings',
    body: 'Compare opening vs final L1 price and see how extensions improved your pricing.',
    phase: 8,
  },
];

const SUPPLIER_CARDS: Card[] = [
  {
    title: 'Your invitations',
    body: 'RFQs you have been invited to quote on, with their bidding windows.',
    phase: 2,
  },
  {
    title: 'Submit and lower bids',
    body: 'Quote carrier, freight, origin and destination charges, transit time and validity.',
    phase: 3,
  },
  {
    title: 'Track your rank',
    body: 'See your live rank and the current L1 price, and when the auction gets extended.',
    phase: 5,
  },
];

/** Role-specific landing page. Becomes the auction listing in Phase 2. */
export function HomePage() {
  const { user } = useAuth();
  if (!user) return null;
  const cards = user.role === 'SUPPLIER' ? SUPPLIER_CARDS : BUYER_CARDS;

  return (
    <Stack spacing={3}>
      <div>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 0.5 }}>
          <Typography variant="h4" component="h1">
            Welcome, {user.full_name.split(' ')[0]}
          </Typography>
          <Chip label={ROLE_LABEL[user.role]} color="primary" size="small" />
        </Stack>
        <Typography color="text.secondary">{user.company_name}</Typography>
      </div>
      <Grid container spacing={2}>
        {cards.map((c) => (
          <Grid key={c.title} size={{ xs: 12, md: 4 }}>
            <Paper variant="outlined" sx={{ p: 3, height: '100%' }}>
              <Typography variant="h6" gutterBottom>
                {c.title}
              </Typography>
              <Typography color="text.secondary" sx={{ mb: 2 }}>
                {c.body}
              </Typography>
              <Chip label={`Phase ${c.phase}`} size="small" variant="outlined" />
            </Paper>
          </Grid>
        ))}
      </Grid>
    </Stack>
  );
}
