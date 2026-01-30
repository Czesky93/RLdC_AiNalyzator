import React, { useEffect, useState } from 'react';
import {
  Box,
  Grid,
  Card,
  CardContent,
  Typography,
  CircularProgress,
  Alert,
} from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import AccountBalanceWalletIcon from '@mui/icons-material/AccountBalanceWallet';
import PsychologyIcon from '@mui/icons-material/Psychology';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import axios from 'axios';

// Mock chart data for portfolio performance
const mockChartData = [
  { date: '01/25', value: 118500 },
  { date: '01/26', value: 120200 },
  { date: '01/27', value: 119800 },
  { date: '01/28', value: 122400 },
  { date: '01/29', value: 123500 },
  { date: '01/30', value: 125847 },
];

const KPICard = ({ title, value, subtitle, icon, trend, trendValue }) => {
  const isPositive = trend === 'up';
  const TrendIcon = isPositive ? TrendingUpIcon : TrendingDownIcon;
  const trendColor = isPositive ? '#00ff41' : '#ff0055';

  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 500 }}>
            {title}
          </Typography>
          <Box sx={{ 
            backgroundColor: 'rgba(0, 255, 65, 0.1)', 
            borderRadius: '8px', 
            p: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            {icon}
          </Box>
        </Box>
        <Typography variant="h4" sx={{ fontWeight: 700, mb: 1 }}>
          {value}
        </Typography>
        {subtitle && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            {trendValue && (
              <>
                <TrendIcon sx={{ fontSize: '1.2rem', color: trendColor }} />
                <Typography variant="body2" sx={{ color: trendColor, fontWeight: 600 }}>
                  {trendValue}
                </Typography>
              </>
            )}
            <Typography variant="body2" color="text.secondary">
              {subtitle}
            </Typography>
          </Box>
        )}
      </CardContent>
    </Card>
  );
};

export default function Dashboard() {
  const [portfolio, setPortfolio] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [portfolioRes, statusRes] = await Promise.all([
          axios.get('http://localhost:8000/portfolio'),
          axios.get('http://localhost:8000/status'),
        ]);
        setPortfolio(portfolioRes.data);
        setStatus(statusRes.data);
        setError(null);
      } catch (err) {
        console.error('Error fetching data:', err);
        setError('Unable to connect to API. Please ensure the backend server is running on port 8000.');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    // Refresh data every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <CircularProgress sx={{ color: '#00ff41' }} />
      </Box>
    );
  }

  return (
    <Box>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ fontWeight: 700, color: '#ffffff', mb: 1 }}>
          Trading Dashboard
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Real-time portfolio overview and AI trading insights
        </Typography>
      </Box>

      {error && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {/* KPI Cards */}
      <Grid container spacing={3} sx={{ mb: 4 }}>
        <Grid item xs={12} sm={6} md={4}>
          <KPICard
            title="Total Balance"
            value={portfolio ? `$${portfolio.total_balance.toLocaleString()}` : '$125,847'}
            subtitle="across all assets"
            icon={<AccountBalanceWalletIcon sx={{ color: '#00ff41', fontSize: '1.8rem' }} />}
            trend="up"
            trendValue="+8.2%"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <KPICard
            title="Daily P&L"
            value={portfolio ? `$${portfolio.daily_pnl.toLocaleString()}` : '$2,346'}
            subtitle="today's performance"
            icon={<TrendingUpIcon sx={{ color: '#00ff41', fontSize: '1.8rem' }} />}
            trend="up"
            trendValue={portfolio ? `+${portfolio.daily_pnl_percent}%` : '+1.90%'}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={4}>
          <KPICard
            title="Active AI Agents"
            value={status ? status.active_agents : '3'}
            subtitle="strategies running"
            icon={<PsychologyIcon sx={{ color: '#00ff41', fontSize: '1.8rem' }} />}
          />
        </Grid>
      </Grid>

      {/* Portfolio Performance Chart */}
      <Card sx={{ mb: 4 }}>
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ mb: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 0.5 }}>
              Portfolio Performance
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Last 7 days performance overview
            </Typography>
          </Box>
          <Box sx={{ width: '100%', height: 350 }}>
            <ResponsiveContainer>
              <AreaChart data={mockChartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00ff41" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#00ff41" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
                <XAxis 
                  dataKey="date" 
                  stroke="#b0b0b0"
                  style={{ fontSize: '0.85rem' }}
                />
                <YAxis 
                  stroke="#b0b0b0"
                  style={{ fontSize: '0.85rem' }}
                  tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1a1a1a',
                    border: '1px solid #2a2a2a',
                    borderRadius: '8px',
                    color: '#ffffff',
                  }}
                  formatter={(value) => [`$${value.toLocaleString()}`, 'Balance']}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#00ff41"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorValue)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </Box>
        </CardContent>
      </Card>

      {/* Recent AI Signals */}
      <Card>
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ mb: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 0.5 }}>
              Latest AI Signals
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Real-time trading signals from AI strategies
            </Typography>
          </Box>
          <Box sx={{ 
            display: 'flex', 
            justifyContent: 'center', 
            alignItems: 'center', 
            minHeight: '150px',
            border: '2px dashed #2a2a2a',
            borderRadius: '8px',
          }}>
            <Typography variant="body1" color="text.secondary">
              Signal visualization will be displayed here
            </Typography>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
