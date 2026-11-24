import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useState } from 'react';

import { fieldErrors } from '@/api/client';
import { EmailChipsField } from '@/components/EmailChipsField';
import { formatDateTime } from '@/lib/datetime';
import { EMAIL_RE } from '@/lib/emails';

import { useInviteSuppliers, useResendInvitation } from './api';
import type { RfqDetail } from './types';

export function InvitationsCard({ rfq }: { rfq: RfqDetail }) {
  const invitations = rfq.invitations ?? [];
  const invite = useInviteSuppliers(rfq.id);
  const resend = useResendInvitation(rfq.id);
  const [emails, setEmails] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const invalid = emails.filter((e) => !EMAIL_RE.test(e));
  const joined = invitations.filter((i) => i.status === 'JOINED').length;

  const sendInvites = async () => {
    setNotice(null);
    const before = rfq.invited_count;
    const updated = await invite.mutateAsync(emails);
    const added = updated.invited_count - before;
    setEmails([]);
    setNotice(
      added > 0
        ? `Invited ${added} supplier${added === 1 ? '' : 's'}.`
        : 'Everyone on that list was already invited.',
    );
  };

  const inviteError = invite.error
    ? (fieldErrors(invite.error).emails ?? invite.error.message)
    : null;

  return (
    <Paper variant="outlined" sx={{ p: { xs: 2, sm: 3 } }}>
      <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <Typography variant="h6" component="h2">
          Invited suppliers
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {joined} of {invitations.length} joined
        </Typography>
      </Stack>

      {invitations.length === 0 ? (
        <Typography color="text.secondary" sx={{ my: 2 }}>
          No suppliers invited yet. Only invited suppliers can see and bid on this RFQ.
        </Typography>
      ) : (
        <List dense disablePadding sx={{ my: 1 }}>
          {invitations.map((inv) => (
            <ListItem
              key={inv.email}
              disableGutters
              divider
              secondaryAction={
                rfq.permissions.can_invite && (
                  <Button
                    size="small"
                    disabled={resend.isPending && resend.variables === inv.email}
                    onClick={() =>
                      resend
                        .mutateAsync(inv.email)
                        .then(() => setNotice(`Invitation re-sent to ${inv.email}.`))
                    }
                  >
                    Resend
                  </Button>
                )
              }
            >
              <ListItemText
                sx={{ pr: 10 }}
                primary={
                  <Stack
                    direction="row"
                    spacing={1}
                    sx={{ alignItems: 'center', flexWrap: 'wrap' }}
                  >
                    <span>{inv.supplier_company ?? inv.email}</span>
                    <Chip
                      size="small"
                      label={inv.status === 'JOINED' ? 'Joined' : 'Awaiting sign-up'}
                      color={inv.status === 'JOINED' ? 'success' : 'default'}
                      variant="outlined"
                    />
                  </Stack>
                }
                secondary={
                  <>
                    {inv.supplier_name ? `${inv.supplier_name} · ${inv.email}` : inv.email}
                    {inv.last_notified_at && ` · emailed ${formatDateTime(inv.last_notified_at)}`}
                  </>
                }
              />
            </ListItem>
          ))}
        </List>
      )}

      {notice && (
        <Alert severity="success" onClose={() => setNotice(null)} sx={{ my: 1 }}>
          {notice}
        </Alert>
      )}
      {resend.error && <Alert severity="error">{resend.error.message}</Alert>}

      {rfq.permissions.can_invite && (
        <Stack spacing={1} sx={{ mt: 2 }}>
          <EmailChipsField
            label="Invite more suppliers"
            value={emails}
            onChange={setEmails}
            error={!!inviteError || invalid.length > 0}
            helperText={
              invalid.length
                ? `Fix invalid email: ${invalid[0]}`
                : (inviteError ?? 'New emails receive a sign-up link.')
            }
          />
          <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
            <Button
              variant="contained"
              disabled={emails.length === 0 || invalid.length > 0 || invite.isPending}
              onClick={() => void sendInvites().catch(() => undefined)}
            >
              {invite.isPending ? 'Sending…' : 'Send invitations'}
            </Button>
          </Stack>
        </Stack>
      )}
    </Paper>
  );
}
