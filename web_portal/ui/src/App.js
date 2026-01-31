import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function App() {
  const [trades, setTrades] = useState([]);
  const [analysis, setAnalysis] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [apiStatus, setApiStatus] = useState('nieznany');

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000); // Odświeżanie co 30 sekund
    return () => clearInterval(interval);
  }, []);

  const fetchData = async () => {
    try {
      const [healthRes, tradesRes, analysisRes] = await Promise.all([
        axios.get(`${API_URL}/health`),
        axios.get(`${API_URL}/api/trades?limit=10`),
        axios.get(`${API_URL}/api/analysis?limit=10`)
      ]);
      
      setApiStatus('zdrowy');
      setTrades(tradesRes.data);
      setAnalysis(analysisRes.data);
      setLoading(false);
    } catch (error) {
      console.error('Błąd podczas pobierania danych:', error);
      setApiStatus('błąd');
      setLoading(false);
    }
  };

  const createSampleTrade = async () => {
    try {
      const sampleTrade = {
        symbol: 'AAPL',
        action: 'KUP',
        quantity: 10,
        price: 150.50,
        total_value: 1505.00,
        status: 'ukończone'
      };
      await axios.post(`${API_URL}/api/trades`, sampleTrade);
      fetchData();
    } catch (error) {
      console.error('Błąd podczas tworzenia transakcji:', error);
    }
  };

  const createSampleAnalysis = async () => {
    try {
      const sampleAnalysis = {
        symbol: 'AAPL',
        analysis_type: 'Analiza trendu',
        result: 'Wykryto trend wzrostowy',
        confidence: 0.85
      };
      await axios.post(`${API_URL}/api/analysis`, sampleAnalysis);
      fetchData();
    } catch (error) {
      console.error('Błąd podczas tworzenia analizy:', error);
    }
  };

  const translateAction = (action) => {
    const translations = {
      'BUY': 'KUP',
      'SELL': 'SPRZEDAJ'
    };
    return translations[action] || action;
  };

  const translateStatus = (status) => {
    const translations = {
      'pending': 'oczekujące',
      'completed': 'ukończone',
      'cancelled': 'anulowane',
      'oczekujące': 'oczekujące',
      'ukończone': 'ukończone'
    };
    return translations[status] || status;
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>🤖 RLdC AiNalyzator</h1>
        <p>Analiza i Monitorowanie Transakcji oparte na AI</p>
        <div className={`status-indicator ${apiStatus}`}>
          Status API: {apiStatus}
        </div>
      </header>

      <nav className="navigation">
        <button 
          className={activeTab === 'dashboard' ? 'active' : ''} 
          onClick={() => setActiveTab('dashboard')}
        >
          Panel główny
        </button>
        <button 
          className={activeTab === 'trades' ? 'active' : ''} 
          onClick={() => setActiveTab('trades')}
        >
          Transakcje
        </button>
        <button 
          className={activeTab === 'analysis' ? 'active' : ''} 
          onClick={() => setActiveTab('analysis')}
        >
          Analizy
        </button>
      </nav>

      <main className="content">
        {loading ? (
          <div className="loading">Ładowanie...</div>
        ) : (
          <>
            {activeTab === 'dashboard' && (
              <div className="dashboard">
                <div className="stats-grid">
                  <div className="stat-card">
                    <h3>Łącznie transakcji</h3>
                    <div className="stat-value">{trades.length}</div>
                  </div>
                  <div className="stat-card">
                    <h3>Łącznie analiz</h3>
                    <div className="stat-value">{analysis.length}</div>
                  </div>
                  <div className="stat-card">
                    <h3>Status systemu</h3>
                    <div className="stat-value">{apiStatus}</div>
                  </div>
                </div>
                <div className="actions">
                  <button onClick={createSampleTrade} className="action-btn">
                    Dodaj przykładową transakcję
                  </button>
                  <button onClick={createSampleAnalysis} className="action-btn">
                    Dodaj przykładową analizę
                  </button>
                  <button onClick={fetchData} className="action-btn">
                    Odśwież dane
                  </button>
                </div>
              </div>
            )}

            {activeTab === 'trades' && (
              <div className="trades-section">
                <h2>Ostatnie transakcje</h2>
                {trades.length === 0 ? (
                  <p>Nie znaleziono transakcji. Kliknij "Dodaj przykładową transakcję" aby utworzyć jedną.</p>
                ) : (
                  <div className="table-container">
                    <table>
                      <thead>
                        <tr>
                          <th>Czas</th>
                          <th>Symbol</th>
                          <th>Akcja</th>
                          <th>Ilość</th>
                          <th>Cena</th>
                          <th>Wartość całkowita</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trades.map(trade => (
                          <tr key={trade.id}>
                            <td>{new Date(trade.timestamp).toLocaleString('pl-PL')}</td>
                            <td>{trade.symbol}</td>
                            <td className={`action ${trade.action.toLowerCase()}`}>
                              {translateAction(trade.action)}
                            </td>
                            <td>{trade.quantity}</td>
                            <td>${trade.price.toFixed(2)}</td>
                            <td>${trade.total_value.toFixed(2)}</td>
                            <td className={`status ${trade.status}`}>{translateStatus(trade.status)}</td>
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
                <h2>Ostatnie analizy</h2>
                {analysis.length === 0 ? (
                  <p>Nie znaleziono analiz. Kliknij "Dodaj przykładową analizę" aby utworzyć jedną.</p>
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
                            Pewność: {(item.confidence * 100).toFixed(0)}%
                          </div>
                        )}
                        <div className="timestamp">
                          {new Date(item.timestamp).toLocaleString('pl-PL')}
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
        <p>© {new Date().getFullYear()} RLdC AiNalyzator - System Analizy Transakcji</p>
      </footer>
    </div>
  );
}

export default App;
