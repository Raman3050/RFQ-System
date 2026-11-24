import Button from '@mui/material/Button';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { Link } from 'react-router-dom';

export function ForbiddenPage() {
  return (
    <Paper variant="outlined" sx={{ p: 4 }}>
      <Typography variant="h5" component="h1" gutterBottom>
        Not available for your role
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Your account doesn’t have access to this page.
      </Typography>
      <Button component={Link} to="/auctions" variant="outlined">
        Back to auctions
      </Button>
    </Paper>
  );
}
