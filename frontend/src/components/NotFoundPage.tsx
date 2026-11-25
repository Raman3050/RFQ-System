import Button from '@mui/material/Button';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <Paper variant="outlined" sx={{ p: 4 }}>
      <Typography variant="h5" component="h1" gutterBottom>
        Page not found
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        The page you’re looking for doesn’t exist.
      </Typography>
      <Button component={Link} to="/auctions" variant="outlined">
        Back to auctions
      </Button>
    </Paper>
  );
}
