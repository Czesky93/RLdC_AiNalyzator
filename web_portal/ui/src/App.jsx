import { useEffect, useMemo, useState } from "react";
import {
    createBlogPost,
    createDemoOrder,
    deleteBlogPost,
    fetchBlog,
    fetchDemoOrders,
    fetchDemoSummary,
    fetchKlines,
    fetchLiveAccount,
    fetchLiveOrders,
    fetchLivePositions,
    fetchLogs,
    fetchMarketSummary,
    fetchSummary,
    publishBlogPost,
    sendTelegramAlert
} from "./api";
import MarketChart from "./components/MarketChart";

const MENU = [
  "Dashboard",
  "Rynek",
  "Trade Desk",
  "Portfolio",
  "Strategie",
  "AI & Sygnały",
  "Ryzyko",
  "Backtest/Demo",
  "Alerty",
  "Raporty",
  "Ustawienia"
];

const formatNumber = (value) => {
  if (value === null || value === undefined) return "–";
  if (Number.isNaN(Number(value))) return value;
  return Number(value).toLocaleString("pl-PL", { maximumFractionDigits: 2 });
};

export default function App() {
  const [summary, setSummary] = useState(null);
  const [market, setMarket] = useState([]);
  const [klines, setKlines] = useState([]);
  const [demoSummary, setDemoSummary] = useState(null);
  const [demoOrders, setDemoOrders] = useState([]);
  const [account, setAccount] = useState(null);
  const [orders, setOrders] = useState([]);
  const [positions, setPositions] = useState([]);
  const [blog, setBlog] = useState([]);
  const [logs, setLogs] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [status, setStatus] = useState("Ładowanie danych...");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [actionInfo, setActionInfo] = useState("Gotowość operacyjna");
  const [alertMessage, setAlertMessage] = useState("");
  const [demoForm, setDemoForm] = useState({
    symbol: "BTCUSDT",
    side: "BUY",
    qty: 0.01,
    price: 0,
    status: "NEW"
  });
  const [blogForm, setBlogForm] = useState({ title: "", content: "" });

  const marketSymbols = useMemo(() => market.map((m) => m.symbol), [market]);
  const lastSignal = summary?.ostatnia_analiza ?? null;

  const refreshCore = async () => {
    try {
      const [summaryData, demoSummaryData, demoOrdersData, blogData, logData] = await Promise.all([
        fetchSummary(),
        fetchDemoSummary(),
        fetchDemoOrders(),
        fetchBlog(),
        fetchLogs(30)
      ]);
      setSummary(summaryData);
      setDemoSummary(demoSummaryData);
      setDemoOrders(demoOrdersData);
      setBlog(blogData);
      setLogs(logData);
    } catch (error) {
      setStatus("Błąd pobierania danych podstawowych");
    }
  };

  const refreshLive = async () => {
    try {
      const [accountData, ordersData, positionsData] = await Promise.all([
        fetchLiveAccount(),
        fetchLiveOrders(),
        fetchLivePositions()
      ]);
      setAccount(accountData);
      setOrders(ordersData);
      setPositions(positionsData);
    } catch (error) {
      setStatus("Brak danych LIVE (sprawdź klucze Binance)");
    }
  };

  useEffect(() => {
    refreshCore();
    refreshLive();
  }, []);

  useEffect(() => {
    let timeout = 2000;
    let cancelled = false;

    const loadMarket = async () => {
      try {
        const data = await fetchMarketSummary();
        if (!cancelled) {
          setMarket(data.dane || []);
          setStatus("Dane rynkowe aktualne");
          timeout = 2000;
        }
      } catch (error) {
        if (!cancelled) {
          setStatus("Błąd danych rynkowych – ponawiam...");
          timeout = Math.min(timeout * 2, 30000);
        }
      }
      if (!cancelled) {
        setTimeout(loadMarket, timeout);
      }
    };

    loadMarket();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      refreshLive();
      fetchLogs(30).then(setLogs).catch(() => null);
    }, 15000);
    return () => clearInterval(interval);
  }, [autoRefresh]);

  useEffect(() => {
    if (!selectedSymbol) return;
    fetchKlines(selectedSymbol, "1h")
      .then((data) => setKlines(data.klines || []))
      .catch(() => null);
  }, [selectedSymbol]);

  const handleCreateDemo = async () => {
    try {
      await createDemoOrder({
        ...demoForm,
        qty: Number(demoForm.qty),
        price: Number(demoForm.price)
      });
      setActionInfo("Dodano zlecenie demo");
      await refreshCore();
    } catch (error) {
      setActionInfo("Błąd dodawania zlecenia demo");
    }
  };

  const handleCreateBlog = async () => {
    if (!blogForm.title || !blogForm.content) {
      setActionInfo("Uzupełnij tytuł i treść wpisu");
      return;
    }
    try {
      await createBlogPost(blogForm);
      setBlogForm({ title: "", content: "" });
      setActionInfo("Dodano wpis do bloga");
      await refreshCore();
    } catch (error) {
      setActionInfo("Błąd zapisu wpisu bloga");
    }
  };

  const handlePublishBlog = async (postId) => {
    try {
      await publishBlogPost(postId);
      setActionInfo("Opublikowano wpis");
      await refreshCore();
    } catch (error) {
      setActionInfo("Błąd publikacji wpisu");
    }
  };

  const handleDeleteBlog = async (postId) => {
    try {
      await deleteBlogPost(postId);
      setActionInfo("Usunięto wpis");
      await refreshCore();
    } catch (error) {
      setActionInfo("Błąd usuwania wpisu");
    }
  };

  const handleSendAlert = async () => {
    if (!alertMessage) {
      setActionInfo("Wpisz treść alertu");
      return;
    }
    try {
      await sendTelegramAlert(alertMessage);
      setAlertMessage("");
      setActionInfo("Wysłano alert Telegram");
    } catch (error) {
      setActionInfo("Błąd wysyłki alertu Telegram");
    }
  };

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">RLDC</span>
          <small>Centrum sterowania</small>
        </div>
        <nav className="menu">
          {MENU.map((item, index) => (
            <button key={item} className={`menu-item ${index === 0 ? "active" : ""}`}>
              <span>{item}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="status-pill">
            <span className="dot" /> LIVE {account ? "AKTYWNY" : "NIEAKTYWNY"}
          </div>
          <p className="muted">Wersja 0.7 beta</p>
        </div>
      </aside>

      <div className="content">
        <header className="topbar">
          <div className="title-block">
            <h1>RLdC AiNalyzer</h1>
            <p>{status}</p>
          </div>
          <div className="top-actions">
            <button className="ghost" onClick={() => setAutoRefresh((prev) => !prev)}>
              Auto-odświeżanie: {autoRefresh ? "ON" : "OFF"}
            </button>
            <button className="ghost" onClick={refreshCore}>Odśwież dane</button>
            <button className="primary">STOP TRADING</button>
          </div>
        </header>

        <section className="metrics">
          <div className="metric-card">
            <p>Kapitał operacyjny</p>
            <h3>{formatNumber(demoSummary?.wartosc ?? 0)} PLN</h3>
            <span className="trend up">+1.8% dziś</span>
          </div>
          <div className="metric-card">
            <p>Transakcje / Analizy</p>
            <h3>
              {summary?.trades ?? 0} / {summary?.analysis ?? 0}
            </h3>
            <span className="trend">Aktywność systemu</span>
          </div>
          <div className="metric-card">
            <p>Wypełnione zlecenia</p>
            <h3>{demoSummary?.wypelnione ?? 0}</h3>
            <span className="trend">Tryb demo</span>
          </div>
          <div className="metric-card">
            <p>Aktywne instrumenty</p>
            <h3>{market.length}</h3>
            <span className="trend up">Monitoring LIVE</span>
          </div>
        </section>

        <section className="grid-main">
          <div className="panel chart-panel">
            <div className="panel-head">
              <div>
                <h3>Rynek LIVE</h3>
                <p>BTC/ETH + wybrane instrumenty</p>
              </div>
              <div className="panel-actions">
                <label>
                  Instrument
                  <select value={selectedSymbol} onChange={(e) => setSelectedSymbol(e.target.value)}>
                    {marketSymbols.map((symbol) => (
                      <option key={symbol} value={symbol}>
                        {symbol}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
            <MarketChart data={klines} />
            <div className="table compact">
              <div className="table-row header">
                <span>Symbol</span>
                <span>Cena</span>
                <span>Zmiana %</span>
                <span>Wolumen</span>
              </div>
              {market.map((row) => (
                <div className="table-row" key={row.symbol}>
                  <span>{row.symbol}</span>
                  <span>{formatNumber(row.last_price)}</span>
                  <span className={row.change_percent >= 0 ? "up" : "down"}>
                    {formatNumber(row.change_percent)}
                  </span>
                  <span>{formatNumber(row.volume)}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel side-panel">
            <h3>Decyzje i ryzyko</h3>
            <div className="risk-block">
              <p>Ostatni sygnał</p>
              <div className="signal">
                <span>{lastSignal?.indicator ?? "Brak"}</span>
                <strong>{lastSignal?.symbol ?? "—"}</strong>
              </div>
              <div className="progress">
                <span>Ryzyko dzienne</span>
                <div className="bar"><div className="bar-fill" style={{ width: "42%" }} /></div>
              </div>
              <div className="progress">
                <span>Użycie kapitału</span>
                <div className="bar"><div className="bar-fill" style={{ width: "68%" }} /></div>
              </div>
            </div>
            <div className="risk-block">
              <p>Pozycje aktywne</p>
              <div className="pill-row">
                <span className="pill">{positions?.length ?? 0} instrumentów</span>
                <span className="pill">{orders?.length ?? 0} zleceń</span>
              </div>
              <p className="muted">Tryb read-only</p>
            </div>
            <div className="risk-block">
              <p>Alerty systemowe</p>
              <ul className="alert-list">
                <li>Synchronizacja rynku: {status}</li>
                <li>Tryb LIVE: {account ? "aktywny" : "wyłączony"}</li>
                <li>Bot Telegram: dostępny</li>
              </ul>
            </div>
            <div className="risk-block">
              <p>Komunikacja i kontrola</p>
              <div className="form-grid">
                <input
                  value={alertMessage}
                  onChange={(e) => setAlertMessage(e.target.value)}
                  placeholder="Treść alertu Telegram"
                />
                <button className="primary" onClick={handleSendAlert}>Wyślij alert</button>
              </div>
              <p className="muted">{actionInfo}</p>
            </div>
          </div>

          <div className="panel">
            <h3>Historia zleceń demo</h3>
            <div className="form-grid">
              <input
                value={demoForm.symbol}
                onChange={(e) => setDemoForm((prev) => ({ ...prev, symbol: e.target.value.toUpperCase() }))}
                placeholder="Symbol (np. BTCUSDT)"
              />
              <select value={demoForm.side} onChange={(e) => setDemoForm((prev) => ({ ...prev, side: e.target.value }))}>
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
              <input
                type="number"
                value={demoForm.qty}
                onChange={(e) => setDemoForm((prev) => ({ ...prev, qty: e.target.value }))}
                placeholder="Ilość"
              />
              <input
                type="number"
                value={demoForm.price}
                onChange={(e) => setDemoForm((prev) => ({ ...prev, price: e.target.value }))}
                placeholder="Cena"
              />
              <select value={demoForm.status} onChange={(e) => setDemoForm((prev) => ({ ...prev, status: e.target.value }))}>
                <option value="NEW">NEW</option>
                <option value="FILLED">FILLED</option>
                <option value="CANCELED">CANCELED</option>
              </select>
              <button className="primary" onClick={handleCreateDemo}>Dodaj zlecenie demo</button>
            </div>
            <div className="table">
              <div className="table-row header five">
                <span>Symbol</span>
                <span>Strona</span>
                <span>Ilość</span>
                <span>Cena</span>
                <span>Status</span>
              </div>
              {demoOrders.slice(0, 8).map((row) => (
                <div className="table-row five" key={row.id}>
                  <span>{row.symbol}</span>
                  <span>{row.side}</span>
                  <span>{formatNumber(row.qty)}</span>
                  <span>{formatNumber(row.price)}</span>
                  <span>{row.status}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel">
            <h3>Portfolio LIVE</h3>
            <pre className="code-block">
              {JSON.stringify(account?.balances ?? [], null, 2)}
            </pre>
          </div>

          <div className="panel">
            <h3>Otwarte zlecenia</h3>
            <pre className="code-block">{JSON.stringify(orders ?? [], null, 2)}</pre>
          </div>

          <div className="panel">
            <h3>Blog i notatki analityczne</h3>
            <div className="form-grid vertical">
              <input
                value={blogForm.title}
                onChange={(e) => setBlogForm((prev) => ({ ...prev, title: e.target.value }))}
                placeholder="Tytuł wpisu"
              />
              <textarea
                rows={4}
                value={blogForm.content}
                onChange={(e) => setBlogForm((prev) => ({ ...prev, content: e.target.value }))}
                placeholder="Treść analizy / notatki"
              />
              <button className="primary" onClick={handleCreateBlog}>Zapisz wpis</button>
            </div>
            {blog.length === 0 ? <p className="muted">Brak wpisów.</p> : null}
            {blog.slice(0, 3).map((post) => (
              <article key={post.id} className="blog">
                <h4>{post.title}</h4>
                <p>{post.content}</p>
                <small>Status: {post.status}</small>
                <div className="blog-actions">
                  <button className="ghost" onClick={() => handlePublishBlog(post.id)}>Publikuj</button>
                  <button className="ghost" onClick={() => handleDeleteBlog(post.id)}>Usuń</button>
                </div>
              </article>
            ))}
          </div>

          <div className="panel">
            <h3>Logi systemowe</h3>
            <div className="log-list">
              {logs.length === 0 ? <p className="muted">Brak logów.</p> : null}
              {logs.map((item, index) => (
                <div key={`${item.timestamp}-${index}`} className="log-item">
                  <span>{item.timestamp}</span>
                  <strong>{item.level}</strong>
                  <span>{item.message}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
