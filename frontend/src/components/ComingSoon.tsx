import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';

export function ComingSoon({ title, phase }: { title: string; phase: number }) {
  return (
    <Paper variant="outlined" sx={{ p: 4 }}>
      <Typography variant="h5" gutterBottom>
        {title}
      </Typography>
      <Typography color="text.secondary">Arrives in Phase {phase}.</Typography>
    </Paper>
  );
}
