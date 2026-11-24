import AppBar from '@mui/material/AppBar';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Container from '@mui/material/Container';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';

import { useAuth } from '@/features/auth/AuthContext';
import { ROLE_LABEL, type Role } from '@/features/auth/types';

interface NavItem {
  to: string;
  label: string;
  roles?: Role[];
}

const NAV: NavItem[] = [
  { to: '/auctions', label: 'Auctions' },
  { to: '/rfqs/new', label: 'Create RFQ', roles: ['BUYER', 'ADMIN'] },
  { to: '/system', label: 'System', roles: ['ADMIN', 'BUYER'] },
];

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('');
}

export function Layout() {
  const { user, hasRole, logout } = useAuth();
  const navigate = useNavigate();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  const visibleNav = NAV.filter((n) => !n.roles || hasRole(...n.roles));

  async function handleLogout() {
    setAnchor(null);
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AppBar position="sticky" elevation={0}>
        <Toolbar sx={{ gap: 1 }}>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1, fontWeight: 700 }}>
            RFQ Auctions
          </Typography>
          {visibleNav.map((item) => (
            <Button
              key={item.to}
              component={NavLink}
              to={item.to}
              color="inherit"
              sx={{ '&.active': { bgcolor: 'rgba(255,255,255,0.15)' } }}
            >
              {item.label}
            </Button>
          ))}
          {user && (
            <>
              <IconButton
                onClick={(e) => setAnchor(e.currentTarget)}
                aria-label="Account menu"
                aria-haspopup="menu"
                sx={{ ml: 1 }}
              >
                <Avatar sx={{ width: 32, height: 32, fontSize: 14, bgcolor: 'secondary.main' }}>
                  {initials(user.full_name)}
                </Avatar>
              </IconButton>
              <Menu
                anchorEl={anchor}
                open={!!anchor}
                onClose={() => setAnchor(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                transformOrigin={{ vertical: 'top', horizontal: 'right' }}
              >
                <Box sx={{ px: 2, py: 1, minWidth: 220 }}>
                  <Typography sx={{ fontWeight: 600 }}>{user.full_name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {user.email}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    {user.company_name}
                  </Typography>
                  <Chip label={ROLE_LABEL[user.role]} size="small" color="primary" />
                </Box>
                <Divider />
                <MenuItem onClick={handleLogout}>Sign out</MenuItem>
              </Menu>
            </>
          )}
        </Toolbar>
      </AppBar>
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Outlet />
      </Container>
    </Box>
  );
}
