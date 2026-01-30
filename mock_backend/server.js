const express = require('express');
const cors = require('cors');

const app = express();
const PORT = 8000;

// Enable CORS for all routes
app.use(cors());
app.use(express.json());

// Generate sample equity history data
function generateEquityHistory() {
  const data = [];
  const startDate = new Date();
  startDate.setDate(startDate.getDate() - 30); // 30 days ago
  
  let equity = 100000; // Start with $100k
  
  for (let i = 0; i < 30; i++) {
    const date = new Date(startDate);
    date.setDate(date.getDate() + i);
    
    // Simulate random equity changes
    const change = (Math.random() - 0.45) * 2000; // Slight upward bias
    equity += change;
    
    data.push({
      timestamp: date.toISOString(),
      equity: Math.round(equity * 100) / 100
    });
  }
  
  return data;
}

// Generate sample trade history
function generateTradeHistory() {
  const symbols = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN', 'NVDA', 'META'];
  const trades = [];
  
  for (let i = 0; i < 10; i++) {
    const symbol = symbols[Math.floor(Math.random() * symbols.length)];
    const side = Math.random() > 0.5 ? 'Buy' : 'Sell';
    const price = Math.random() * 500 + 50;
    const profitLoss = (Math.random() - 0.4) * 1000; // Slight profit bias
    
    trades.push({
      symbol,
      side,
      price: Math.round(price * 100) / 100,
      profitLoss: Math.round(profitLoss * 100) / 100
    });
  }
  
  return trades;
}

// API Routes

// Dashboard stats endpoint
app.get('/api/dashboard/stats', (req, res) => {
  const stats = {
    balance: 125432.50,
    totalPnL: 25432.50,
    winRate: 0.68 // 68%
  };
  
  res.json(stats);
});

// Equity history endpoint
app.get('/api/dashboard/equity-history', (req, res) => {
  const equityData = generateEquityHistory();
  res.json(equityData);
});

// Trade history endpoint
app.get('/api/dashboard/trade-history', (req, res) => {
  const trades = generateTradeHistory();
  res.json(trades);
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'OK', message: 'Mock Trading API is running' });
});

// Start server
app.listen(PORT, () => {
  console.log(`Mock Trading API server running on http://localhost:${PORT}`);
  console.log(`API endpoints available at http://localhost:${PORT}/api/dashboard/*`);
});
