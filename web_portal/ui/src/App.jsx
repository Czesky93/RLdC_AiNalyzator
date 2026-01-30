import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider, CssBaseline } from '@mui/material';
import theme from './theme';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';

// Placeholder components for other routes
const PlaceholderPage = ({ title }) => (
  <div style={{ padding: '20px' }}>
    <h2 style={{ color: '#00ff41' }}>{title}</h2>
    <p style={{ color: '#b0b0b0' }}>This page is under construction.</p>
  </div>
);

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/strategies" element={<PlaceholderPage title="AI Strategies" />} />
            <Route path="/portfolio" element={<PlaceholderPage title="Portfolio" />} />
            <Route path="/quantum" element={<PlaceholderPage title="Quantum Lab" />} />
            <Route path="/health" element={<PlaceholderPage title="System Health" />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
