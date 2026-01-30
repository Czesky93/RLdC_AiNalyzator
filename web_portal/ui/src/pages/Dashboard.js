import React, { useState, useEffect } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import api from '../services/api';
import { formatCurrency, formatPercentage } from '../utils/format';
import './Dashboard.css';

const Dashboard = () => {
  // State management
  const [stats, setStats] = useState({
    balance: 0,
    totalPnL: 0,
    winRate: 0,
  });
  const [equityData, setEquityData] = useState([]);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Data fetching on component mount
  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Fetch all data in parallel
        const [statsData, equityHistoryData, tradeHistoryData] = await Promise.all([
          api.getDashboardStats(),
          api.getEquityHistory(),
          api.getTradeHistory(),
        ]);

        setStats(statsData);
        setEquityData(equityHistoryData);
        setTrades(tradeHistoryData);
      } catch (err) {
        console.error('Error fetching dashboard data:', err);
        setError(err.message || 'Failed to load dashboard data');
      } finally {
        setLoading(false);
      }
    };

    fetchDashboardData();
  }, []);

  // Format date for X-axis
  const formatDate = (timestamp) => {
    const date = new Date(timestamp);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  // Format currency for Y-axis
  const formatYAxis = (value) => {
    return `$${(value / 1000).toFixed(0)}k`;
  };

  if (loading) {
    return (
      <div className="dashboard">
        <div className="loading">Loading dashboard data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard">
        <div className="error">Error: {error}</div>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <h1>Trading Dashboard</h1>

      {/* KPI Cards Section */}
      <div className="kpi-cards">
        <div className="kpi-card">
          <h3>Current Balance</h3>
          <p className="kpi-value">{formatCurrency(stats.balance)}</p>
        </div>

        <div className="kpi-card">
          <h3>Total PnL</h3>
          <p
            className={`kpi-value ${
              stats.totalPnL >= 0 ? 'positive' : 'negative'
            }`}
          >
            {formatCurrency(stats.totalPnL)}
          </p>
        </div>

        <div className="kpi-card">
          <h3>Win Rate</h3>
          <p className="kpi-value">{formatPercentage(stats.winRate)}</p>
        </div>
      </div>

      {/* Equity Chart Section */}
      <div className="chart-section">
        <h2>Equity Curve</h2>
        <ResponsiveContainer width="100%" height={400}>
          <AreaChart
            data={equityData}
            margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatDate}
            />
            <YAxis tickFormatter={formatYAxis} />
            <Tooltip
              formatter={(value) => formatCurrency(value)}
              labelFormatter={formatDate}
            />
            <Area
              type="monotone"
              dataKey="equity"
              stroke="#8884d8"
              fill="#8884d8"
              fillOpacity={0.3}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Recent Trades Table Section */}
      <div className="trades-section">
        <h2>Recent Trades</h2>
        <table className="trades-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Price</th>
              <th>Profit/Loss</th>
            </tr>
          </thead>
          <tbody>
            {trades.length > 0 ? (
              trades.map((trade, index) => (
                <tr key={index}>
                  <td>{trade.symbol}</td>
                  <td>
                    <span className={`side ${trade.side.toLowerCase()}`}>
                      {trade.side}
                    </span>
                  </td>
                  <td>{formatCurrency(trade.price)}</td>
                  <td
                    className={
                      trade.profitLoss >= 0 ? 'positive' : 'negative'
                    }
                  >
                    {formatCurrency(trade.profitLoss)}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan="4" className="no-data">
                  No trades available
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default Dashboard;
