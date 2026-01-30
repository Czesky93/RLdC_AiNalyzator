import { createTheme } from '@mui/material/styles';

/**
 * Professional Trading Dashboard Theme
 * Dark mode with Cyberpunk Green/Red accents
 * Inspired by professional trading terminals like Bloomberg Terminal
 */
const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#00ff41', // Cyberpunk Green
      light: '#39ff6d',
      dark: '#00cc34',
      contrastText: '#000000',
    },
    secondary: {
      main: '#ff0055', // Cyberpunk Red
      light: '#ff3377',
      dark: '#cc0044',
      contrastText: '#ffffff',
    },
    background: {
      default: '#0a0a0a', // Almost black
      paper: '#1a1a1a', // Dark grey
    },
    text: {
      primary: '#ffffff',
      secondary: '#b0b0b0',
    },
    success: {
      main: '#00ff41',
      light: '#39ff6d',
      dark: '#00cc34',
    },
    error: {
      main: '#ff0055',
      light: '#ff3377',
      dark: '#cc0044',
    },
    warning: {
      main: '#ffaa00',
      light: '#ffbb33',
      dark: '#cc8800',
    },
    info: {
      main: '#00aaff',
      light: '#33bbff',
      dark: '#0088cc',
    },
    divider: '#2a2a2a',
  },
  typography: {
    fontFamily: [
      'Roboto Mono',
      'Roboto',
      'Consolas',
      'Monaco',
      'monospace',
    ].join(','),
    h1: {
      fontSize: '2.5rem',
      fontWeight: 700,
      letterSpacing: '-0.01562em',
    },
    h2: {
      fontSize: '2rem',
      fontWeight: 600,
      letterSpacing: '-0.00833em',
    },
    h3: {
      fontSize: '1.75rem',
      fontWeight: 600,
    },
    h4: {
      fontSize: '1.5rem',
      fontWeight: 500,
    },
    h5: {
      fontSize: '1.25rem',
      fontWeight: 500,
    },
    h6: {
      fontSize: '1rem',
      fontWeight: 500,
    },
    body1: {
      fontSize: '0.95rem',
      letterSpacing: '0.00938em',
    },
    body2: {
      fontSize: '0.875rem',
      letterSpacing: '0.01071em',
    },
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#1a1a1a',
          borderRadius: '8px',
          border: '1px solid #2a2a2a',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#1a1a1a',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          borderRadius: '6px',
          fontWeight: 500,
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#141414',
          borderRight: '1px solid #2a2a2a',
        },
      },
    },
  },
  shape: {
    borderRadius: 8,
  },
});

export default theme;
