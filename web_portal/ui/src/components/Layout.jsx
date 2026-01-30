import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Box,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  AppBar,
  IconButton,
  Divider,
} from '@mui/material';
import DashboardIcon from '@mui/icons-material/Dashboard';
import PsychologyIcon from '@mui/icons-material/Psychology';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import ScienceIcon from '@mui/icons-material/Science';
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';
import MenuIcon from '@mui/icons-material/Menu';

const DRAWER_WIDTH = 280;

const navigationItems = [
  { text: 'Dashboard', icon: <DashboardIcon />, path: '/' },
  { text: 'AI Strategies', icon: <PsychologyIcon />, path: '/strategies' },
  { text: 'Portfolio', icon: <AccountBalanceWalletIcon />, path: '/portfolio' },
  { text: 'Quantum Lab', icon: <ScienceIcon />, path: '/quantum' },
  { text: 'System Health', icon: <MonitorHeartIcon />, path: '/health' },
];

export default function Layout({ children }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = React.useState(false);

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const drawer = (
    <Box>
      <Toolbar sx={{ 
        backgroundColor: '#0a0a0a',
        borderBottom: '1px solid #2a2a2a',
        minHeight: '80px !important',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <Box sx={{ textAlign: 'center' }}>
          <Typography 
            variant="h5" 
            sx={{ 
              fontWeight: 700,
              color: '#00ff41',
              letterSpacing: '0.05em',
              textShadow: '0 0 10px rgba(0, 255, 65, 0.5)',
            }}
          >
            RLdC AI
          </Typography>
          <Typography 
            variant="caption" 
            sx={{ 
              color: '#b0b0b0',
              letterSpacing: '0.15em',
              fontSize: '0.7rem',
            }}
          >
            ANALYZER v1.0
          </Typography>
        </Box>
      </Toolbar>
      <Divider sx={{ backgroundColor: '#2a2a2a' }} />
      <List sx={{ px: 2, py: 3 }}>
        {navigationItems.map((item) => {
          const isActive = location.pathname === item.path;
          return (
            <ListItem key={item.text} disablePadding sx={{ mb: 1 }}>
              <ListItemButton
                onClick={() => navigate(item.path)}
                sx={{
                  borderRadius: '8px',
                  backgroundColor: isActive ? 'rgba(0, 255, 65, 0.1)' : 'transparent',
                  borderLeft: isActive ? '3px solid #00ff41' : '3px solid transparent',
                  '&:hover': {
                    backgroundColor: 'rgba(0, 255, 65, 0.05)',
                  },
                  py: 1.5,
                }}
              >
                <ListItemIcon sx={{ 
                  color: isActive ? '#00ff41' : '#b0b0b0',
                  minWidth: '40px',
                }}>
                  {item.icon}
                </ListItemIcon>
                <ListItemText 
                  primary={item.text}
                  primaryTypographyProps={{
                    fontSize: '0.95rem',
                    fontWeight: isActive ? 600 : 400,
                    color: isActive ? '#00ff41' : '#ffffff',
                  }}
                />
              </ListItemButton>
            </ListItem>
          );
        })}
      </List>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      {/* AppBar for mobile */}
      <AppBar
        position="fixed"
        sx={{
          display: { sm: 'none' },
          backgroundColor: '#141414',
          borderBottom: '1px solid #2a2a2a',
        }}
      >
        <Toolbar>
          <IconButton
            color="inherit"
            aria-label="open drawer"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2 }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" noWrap component="div" sx={{ color: '#00ff41' }}>
            RLdC AI Analyzer
          </Typography>
        </Toolbar>
      </AppBar>

      {/* Drawer - permanent on desktop, temporary on mobile */}
      <Box
        component="nav"
        sx={{ width: { sm: DRAWER_WIDTH }, flexShrink: { sm: 0 } }}
      >
        {/* Mobile drawer */}
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': { 
              boxSizing: 'border-box', 
              width: DRAWER_WIDTH,
            },
          }}
        >
          {drawer}
        </Drawer>
        
        {/* Desktop drawer */}
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': { 
              boxSizing: 'border-box', 
              width: DRAWER_WIDTH,
            },
          }}
          open
        >
          {drawer}
        </Drawer>
      </Box>

      {/* Main content */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: { sm: `calc(100% - ${DRAWER_WIDTH}px)` },
          backgroundColor: '#0a0a0a',
          minHeight: '100vh',
        }}
      >
        <Toolbar sx={{ display: { sm: 'none' } }} />
        {children}
      </Box>
    </Box>
  );
}
