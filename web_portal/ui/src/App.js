import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function App() {
  const [trades, setTrades] = useState([]);
  const [analysis, setAnalysis] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [apiStatus, setApiStatus] = useState('unknown');

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30 seconds
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      const [healthRes, tradesRes, analysisRes] = await Promise.all([
        axios.get(`${API_URL}/health`),
        axios.get(`${API_URL}/api/trades?limit=10`),
        axios.get(`${API_URL}/api/analysis?limit=10`)
      ]);
      
      setApiStatus('healthy');
      setTrades(tradesRes.data);
      setAnalysis(analysisRes.data);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching data:', error);
      setApiStatus('error');
      setLoading(false);
    }
  };

  const createSampleTrade = async () => {
    try {
      const sampleTrade = {
        symbol: 'AAPL',
        action: 'BUY',
        quantity: 10,
        price: 150.50,
        total_value: 1505.00,
        status: 'completed'
      };
      await axios.post(`${API_URL}/api/trades`, sampleTrade);
      fetchData();
    } catch (error) {
      console.error('Error creating trade:', error);
    }
  };

  const createSampleAnalysis = async () => {
    try {
      const sampleAnalysis = {
        symbol: 'AAPL',
        analysis_type: 'Trend Analysis',
        result: 'Bullish trend detected',
        confidence: 0.85
      };
      await axios.post(`${API_URL}/api/analysis`, sampleAnalysis);
      fetchData();
    } catch (error) {
      console.error('Error creating analysis:', error);
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>🤖 RLdC AiNalyzator</h1>
        <p>AI-Powered Trading Analysis & Monitoring</p>
        <div className={`status-indicator ${apiStatus}`}>
          API Status: {apiStatus}
        </div>
      </header>

      <nav className="navigation">
        <button 
          className={activeTab === 'dashboard' ? 'active' : ''} 
          onClick={() => setActiveTab('dashboard')}
        >
          Dashboard
        </button>
        <button 
          className={activeTab === 'trades' ? 'active' : ''} 
          onClick={() => setActiveTab('trades')}
        >
          Trades
        </button>
        <button 
          className={activeTab === 'analysis' ? 'active' : ''} 
          onClick={() => setActiveTab('analysis')}
        >
          Analysis
        </button>
      </nav>

      <main className="content">
        {loading ? (
          <div className="loading">Loading...</div>
        ) : (
          <>
            {activeTab === 'dashboard' && (
              <div className="dashboard">
                <div className="stats-grid">
                  <div className="stat-card">
                    <h3>Total Trades</h3>
                    <div className="stat-value">{trades.length}</div>
                  </div>
                  <div className="stat-card">
                    <h3>Total Analysis</h3>
                    <div className="stat-value">{analysis.length}</div>
                  </div>
                  <div className="stat-card">
                    <h3>System Status</h3>
                    <div className="stat-value">{apiStatus}</div>
                  </div>
                </div>
                <div className="actions">
                  <button onClick={createSampleTrade} className="action-btn">
                    Add Sample Trade
                  </button>
                  <button onClick={createSampleAnalysis} className="action-btn">
                    Add Sample Analysis
                  </button>
                  <button onClick={fetchData} className="action-btn">
                    Refresh Data
                  </button>
                </div>
              </div>
            )}

            {activeTab === 'trades' && (
              <div className="trades-section">
                <h2>Recent Trades</h2>
                {trades.length === 0 ? (
                  <p>No trades found. Click "Add Sample Trade" to create one.</p>
                ) : (
                  <div className="table-container">
                    <table>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Symbol</th>
                          <th>Action</th>
                          <th>Quantity</th>
                          <th>Price</th>
                          <th>Total Value</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trades.map(trade => (
                          <tr key={trade.id}>
                            <td>{new Date(trade.timestamp).toLocaleString()}</td>
                            <td>{trade.symbol}</td>
                            <td className={`action ${trade.action.toLowerCase()}`}>
                              {trade.action}
                            </td>
                            <td>{trade.quantity}</td>
                            <td>${trade.price.toFixed(2)}</td>
                            <td>${trade.total_value.toFixed(2)}</td>
                            <td className={`status ${trade.status}`}>{trade.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {activeTab === 'analysis' && (
              <div className="analysis-section">
                <h2>Recent Analysis</h2>
                {analysis.length === 0 ? (
                  <p>No analysis found. Click "Add Sample Analysis" to create one.</p>
                ) : (
                  <div className="analysis-grid">
                    {analysis.map(item => (
                      <div key={item.id} className="analysis-card">
                        <div className="analysis-header">
                          <span className="symbol">{item.symbol}</span>
                          <span className="type">{item.analysis_type}</span>
                        </div>
                        <div className="analysis-result">{item.result}</div>
                        {item.confidence && (
                          <div className="confidence">
                            Confidence: {(item.confidence * 100).toFixed(0)}%
                          </div>
                        )}
                        <div className="timestamp">
                          {new Date(item.timestamp).toLocaleString()}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </main>

      <footer className="App-footer">
        <p>© 2024 RLdC AiNalyzator - Trading Analysis System</p>
      </footer>
    </div>
  );
}

export default App;
