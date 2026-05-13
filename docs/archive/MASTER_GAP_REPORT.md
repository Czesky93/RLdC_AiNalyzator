# MASTER_GAP_REPORT — RLdC AiNalyzator v0.7 beta
*Ostatnia aktualizacja: 2026-03-31*

> **Cel projektu:** Bot tradingowy zarabiający pieniądze.  
> Demo: 500 EUR. Realne konto Binance: widoczne i analizowane równolegle.  
> AI → KUP / SPRZEDAJ / CZEKAJ z uzasadnieniem.

---

## LEGENDA STATUSÓW

| Status | Znaczenie |
|--------|-----------|
| ✅ DONE | Działa poprawnie, testowane |
| 🟡 PARTIAL | Działa częściowo — brakuje kluczowego kawałka |
| 🔴 BROKEN | Nie działa / błąd / fake data |
| 💀 STUB | Pusty plik / klasa bez implementacji |
| 🖼️ UI_ONLY | Widoczne w UI, ale backend nie dostarcza danych |
| ⚠️ DEBT | Działa, ale dług techniczny hamuje dalszy rozwój |

---

## BACKEND — STATUS PLIKÓW

### Rdzeń systemu

| Plik | Rozmiar | Status | Opis |
|------|---------|--------|------|
| `collector.py` | 2272L / 39fn | ✅ DONE | Zbiera dane Binance co 60s, WebSocket TP/SL, wątek demon |
| `database.py` | 937L / 16fn | ✅ DONE | Wszystkie modele ORM, init_db, migracje schema |
| `runtime_settings.py` | 1028L / 43fn | ✅ DONE | Konfiguracja runtime, symbol tiers, build_symbol_tier_map |
| `accounting.py` | 557L / 19fn | ✅ DONE | compute_demo_account_state, replay zleceń, initial_balance z DB |
| `analysis.py` | 672L / 20fn | ✅ DONE | RSI, EMA, ATR, MACD, Bollinger, sygnały heurystyczne |
| `risk.py` | 227L / 4fn | 🟡 PARTIAL | throttle_signal ✅, daily_drawdown ⚠️ (w LIVE zawsze 0.0) |
| `binance_client.py` | 426L / 20fn | ✅ DONE | REST + WebSocket, order_book, klines, place_order |
| `app.py` | 222L / 5fn | ✅ DONE | FastAPI startup, background tasks, CORS |

### Governance pipeline

| Plik | Rozmiar | Status | Opis |
|------|---------|--------|------|
| `experiments.py` | 457L / 15fn | ✅ DONE | Tworzenie/ewaluacja eksperymentów |
| `recommendations.py` | 217L / 8fn | ✅ DONE | Generowanie rekomendacji z eksperymentów |
| `review_flow.py` | 143L / 6fn | ✅ DONE | Recenzja operator/auto przez SLA |
| `promotion_flow.py` | 209L / 11fn | ✅ DONE | Awansowanie rekomendacji do runtime |
| `post_promotion_monitoring.py` | 248L / 12fn | ✅ DONE | PnL tracking po promocji, trigger rollback |
| `rollback_decision.py` | 246L / 11fn | ✅ DONE | Decyzja o rollbacku |
| `rollback_flow.py` | 158L / 8fn | ✅ DONE | Cofanie konfiguracji |
| `post_rollback_monitoring.py` | 278L / 12fn | ✅ DONE | Monitorowanie po rollbacku |
| `policy_layer.py` | 498L / 13fn | ✅ DONE | Mapowanie werdyktów na akcje |
| `governance.py` | 464L / 12fn | ✅ DONE | Freeze enforcement, incident lifecycle, SLA |
| `reevaluation_worker.py` | 339L / 11fn | ✅ DONE | Cykl ponownej ewaluacji eksperymentów |
| `operator_console.py` | 309L / 12fn | ✅ DONE | Kolejka operatorska |

### Analityka i raportowanie

| Plik | Rozmiar | Status | Opis |
|------|---------|--------|------|
| `trading_effectiveness.py` | 788L / 14fn | ✅ DONE | Win rate, PnL per symbol, fee tracking |
| `correlation.py` | 707L / 18fn | ✅ DONE | Macierz korelacji, diversification_score |
| `tuning_insights.py` | 566L / 10fn | ✅ DONE | Parametry tuningu, statystyki kandydatów |
| `candidate_validation.py` | 514L / 14fn | 🟡 PARTIAL | Walidacja kandydatów ✅, ODŁĄCZONA od collectora |
| `reporting.py` | 188L / 9fn | ✅ DONE | Generowanie raportów tekstowych |
| `notification_hooks.py` | 373L / 19fn | ✅ DONE | Hooki zdarzeń (Telegram, log) |
| `system_logger.py` | 51L / 2fn | ✅ DONE | Logger do DB |

### Inne

| Plik | Rozmiar | Status | Opis |
|------|---------|--------|------|
| `auth.py` | 24L / 1fn | ✅ DONE | `require_admin` używane na 14+ endpointach w `account.py` |

---

## BACKEND — ROUTERY (API)

| Router | Endpointy | Status | Uwagi |
|--------|-----------|--------|-------|
| `account.py` | ~30+ EP | ✅ DONE | Analytics, control, demo reset, governance |
| `market.py` | 10+ EP | ✅ DONE | Klines, sygnały, scanner, forecast |
| `orders.py` | 8 EP | 🟡 PARTIAL | DEMO działa, LIVE → raises 403 (celowo) |
| `signals.py` | 4 EP | ✅ DONE | Top5/Top10 sygnały z analizy real-data |
| `positions.py` | 4 EP | ✅ DONE | Pozycje, analiza, hold cards |
| `portfolio.py` | 2 EP | 🟡 PARTIAL | Demo P&L ✅, Binance balance endpoint braknie synchronizacji |
| `control.py` | 4 EP | ✅ DONE | trading ON/OFF, tryb demo/live, websocket |
| `blog.py` | 2 EP | 💀 STUB | Reads files from /docs — nic nie zwraca |
| `account.py` `reset_demo` | patch L1756 | ✅ DONE | Kasuje Orders+CostLedger+PendingOrders+Positions+Snapshots |

---

## FRONTEND — STATUS KOMPONENTÓW

### Widoki główne (`web_portal/src/`)

| Komponent | Status | Opis |
|-----------|--------|------|
| `page.tsx` | ✅ DONE | Root — renderuje `<Dashboard>` |
| `layout.tsx` | ✅ DONE | Meta, fonts |
| `Dashboard.tsx` | ✅ DONE | Router widoków, integruje Sidebar+Topbar+MainContent |
| `Sidebar.tsx` | ✅ DONE | Nawigacja PL, 16 widoków |
| `Topbar.tsx` | ✅ DONE | Status połączenia, clock, demo indicator |
| `MainContent.tsx` | ✅ DONE | Routing do widoków incl. CommandCenterView |

### Widgety (`web_portal/src/components/widgets/`)

| Widget | Status | Real data? | Opis |
|--------|--------|-----------|------|
| `AccountMetrics.tsx` | ✅ DONE | ✅ Tak | Bilans demo, wartość portfela |
| `AccountSummary.tsx` | 🟡 PARTIAL | ⚠️ Demo only | Brak trybu live Binance |
| `EquityCurve.tsx` | 🟡 PARTIAL | ✅ z DB | Brak Binance equity, tylko demo snapshots |
| `MarketInsights.tsx` | ✅ DONE | ✅ Tak | Sygnały rynkowe z API |
| `MarketOverview.tsx` | ✅ DONE | ✅ Tak | Przegląd rynku, ceny |
| `OpenOrders.tsx` | ✅ DONE | ✅ Tak | Otwarte zlecenia z DB |
| `Orderbook.tsx` | 🟡 PARTIAL | ⚠️ Polling | Orderbook — nie WebSocket realtime |
| `PositionsTable.tsx` | ✅ DONE | ✅ Tak | Pozycje otwarte |
| `TradingView.tsx` | 🟡 PARTIAL | ✅ klines | Brak forecast overlay na wykresie |
| `DecisionRisk.tsx` | ✅ DONE | ✅ Tak | Sygnały ryzyka |
| `DecisionsRiskPanel.tsx` | ✅ DONE | ✅ Tak | Panel decyzji i ryzyka |

### Brakujące widoki (zrealizowane)

| Widok | Status | Opis |
|-------|--------|-----------|
| Symbol Detail Panel | ✅ DONE | `SymbolDetailPanel` — slide-in overlay z prawej, każdy symbol (sesja B) |
| Portfolio Binance View | 🟡 PARTIAL | Tabele Spot/Earn/Futures — brak łącznej wartości EUR |
| Forecast Accuracy Tracker | 🟡 PARTIAL | Tabela `ForecastRecord` w DB + endpoint; rzadko wypełniana |
| AI Summary „co robić” | ✅ DONE | BestOpportunityCard + rekomendacje w CommandCenterView |

---

## TRADING CORE — KRYTYCZNE LUKI (wpływ na zysk)

### 🔴 KRYTYCZNE — bot może nie handlować

| Problem | Plik | Opis | Fix |
|---------|------|------|-----|
| **`create_order` LIVE = 403** | `routers/orders.py` | Celowo zablokowane — bot nie może handlować LIVE | Osobna praca przy włączaniu live trading |

### 🟡 WAŻNE — wpływa na jakość decyzji

| Problem | Plik | Opis | Fix |
|---------|------|------|-----|
| **`daily_drawdown` w LIVE = 0.0** | `risk.py` | Risk gate dla live nie blokuje nadmiernych strat | Obliczyć na podstawie `AccountSnapshot` lub pozycji live |
| **`candidate_validation` odłączona** | `candidate_validation.py` | Walidacja kandydatów nie jest wywoływana w pętli collectora | Wywołać z `_screen_entry_candidates` |
| **Forecast vs actual** | — | `ForecastRecord` w DB, ale automatyczne porównanie po N minut rzadko działa | Docelowo: cron/worker po 15m |

### ⚠️ DŁUG TECHNICZNY

| Problem | Plik | Opis |
|---------|------|------|
| ✅ `datetime.utcnow()` | wszyscy | NAPRAWIONE — `utc_now_naive()` w `backend/database.py`, 203 zastąpienia w 26 plikach (sesja G) |
| ✅ `require_admin` nieużywane | `auth.py` | NAPRAWIONE — używane na 14+ endpointach w `account.py` |
| `blog.py` router | `routers/blog.py` | Martwy stub, zwraca puste listy |
| Stub katalogi | 7 katalogów | `hft_engine/`, `infrastructure/`, `quantum_optimization/`, `blockchain_analysis/`, `portfolio_management/`, `recommendation_engine/`, `ai_trading/` — tylko `__init__.py` lub `.gitkeep` |

---

## DANE — LIVE / CACHE / STALE / BRAK SYNC

| Dane | Źródło | Stan |
|------|--------|------|
| Ceny spot (BTCEUR, ETHEUR...) | Binance WebSocket | ✅ Realtime przez collectora |
| Klines (świece) | Binance REST | ✅ Co 60s, zapisywane do DB |
| Sygnały (RSI/EMA/ATR) | analysis.py | ✅ Real, nie random |
| Sygnały w DB | signals.py → DB | ✅ collector generuje heurystyczne sygnały co cykl |
| Pozycje demo | DB | ✅ Aktualne |
| Pozycje live | Binance REST | 🟡 Nie fetchowane automatycznie |
| Equity curve | AccountSnapshot | ✅ Co cykl collectora (demo) |
| Binance salda (spot) | Binance REST `/account` | 🟡 Na żądanie, brak auto-refresh |
| Orderbook | Binance WS/REST | 🟡 Polling w UI, nie WebSocket |
| AI forecast | analysis.py `forecast_price` | ✅ Heuristic (bez OpenAI) |
| Forecast accuracy | ForecastRecord w DB | 🟡 Tabela istnieje, porównanie rzadko aktywne |

---

## PLAN DOMKNIĘCIA — 4 PIONY

### PION A — LIVE DATA ✅ ZREALIZOWANE

- [x] **A1** — `collector.run_once()` generuje heurystyczne sygnały co cykl i zapisuje do DB (sesja 2026-03-26)
- [x] **A2** — Widget MarketInsights odświeża co 15s ✅

### PION B — PORTFEL (priorytet 2)
**Cel:** Użytkownik widzi demo i Binance obok siebie

- [ ] **B1** — Endpoint `/api/portfolio/live` → real Binance balance (GET /api/v3/account)  
  *Plik:* `backend/routers/portfolio.py`
  
- [ ] **B2** — Widget `AccountSummary.tsx` — zakładki: DEMO | LIVE  
  *Plik:* `web_portal/src/components/widgets/AccountSummary.tsx`
  
- [ ] **B3** — Equity curve live (Binance total value over time)  
  *Plik:* `web_portal/src/components/widgets/EquityCurve.tsx`

### PION C — SYMBOL DETAIL ✅ ZREALIZOWANE

- [x] **C1** — Endpointy `/api/market/ticker/{symbol}`, `/api/market/forecast/{symbol}`, `/api/positions/analysis`, `/api/signals/latest` — łącznie dostarczają wszystkich danych panelu
- [x] **C2** — `SymbolDetailPanel` w `MainContent.tsx`: wykres (ForecastChart) + forecast overlay + buy/sell + RSI (sesja B)
- [x] **C3** — onClick we wszystkich 9 głównych widokach (sesja B)
- [x] **GAP-15** — Auto-refresh co 15s + `DataStatus` w nagłówku (sesja G, 2026-03-31)

### PION D — DECISION ENGINE (w toku)

- [x] **D1** — `_learn_from_history` persists do `RuntimeSetting('learning_symbol_params')` (sesja 2026-03-26)
- [ ] **D2** — `daily_drawdown` w LIVE: obliczyć z pozycji — `backend/risk.py` (otwarte)
- [x] **D3** — Tabela `ForecastRecord` w DB + zapis przy generowaniu; automatyczne porównanie po N minut 🟡 PARTIAL
- [ ] **D4** — AI summary dla całego portfela (otwarte)

---

## AKTUALNY STAN TESTÓW

```
175/175 PASSED  ✅
Coverage: backend routes (smoke tests)
DISABLE_COLLECTOR=true required
```

**Braki w testach:**
- Brak testów E2E (frontend → backend)
- Brak testów dla `accounting.py` replay logic
- Brak testów dla `telegram_bot/bot.py`
- Brak testu reset demo → sprawdzenie equity = 500

---

## CHANGELOG (sesja 2026-03-26)

### Naprawione bugi
1. ✅ **Reset demo**: `reset_demo_balance` teraz usuwa `Order` + `CostLedger` + `PendingOrder` + `Position` + `AccountSnapshot`. Initial balance persists do `RuntimeSetting('demo_initial_balance')`. `compute_demo_account_state()` czyta z DB.
2. ✅ **Telegram /stop**: Teraz faktycznie wywołuje `POST /api/control` (wcześniej nic nie robiło)
3. ✅ **Telegram auth**: `_check_auth()` sprawdza `TELEGRAM_CHAT_ID` na wszystkich komendach
4. ✅ **Telegram API_BASE_URL**: Używa zmiennej ENV zamiast hardcoded `localhost:8000`
5. ✅ **DemoOrderGenerator**: Klasa generująca losowe zlecenia usunięta z `orders.py`
6. ✅ **import random**: Usunięty z `portfolio.py`
7. ✅ **orders.py MARKET price**: `random.uniform(50,50000)` → ostatnia cena z `MarketData.price`
8. ✅ **Signal persistence (PION A)**: `signals.py` `/top5`, `/top10`, `/latest` fallback teraz wywołują `persist_insights_as_signals(db, ...)` — sygnały trafiają do DB
9. ✅ **Sygnały w cyklu collectora**: `collector.run_once()` teraz co cykl generuje heurystyczne sygnały i zapisuje do DB (nie czeka na OpenAI ani wywołanie API)
10. ✅ **AI_PROVIDER default**: Zmieniono z `openai` na `auto` — przy braku klucza OpenAI automatycznie używa heurystyki
11. ✅ **_learn_from_history persistencja (PION D)**: `symbol_params` zapisywane do `RuntimeSetting('learning_symbol_params')` i wczytywane przy starcie collectora (`_load_persisted_symbol_params`)

### Stan po zmianach
- 174/174 testów ✅
- TypeScript: 0 błędów ✅
- Collector generuje sygnały bez OpenAI, co każdy cykl ✅
- symbol_params przeżywa restart ✅

---

## CHANGELOG (sesje 2026-03-29 i 2026-03-31)

### Naprawione / zrealizowane
1. ✅ **`utc_now_naive()` helper** (sesja G, 2026-03-29): nowa funkcja w `backend/database.py`; 203 zastąpienia `datetime.now(timezone.utc).replace(tzinfo=None)` w 26 plikach; 0 deprecation warnings
2. ✅ **Rekurencja `utc_now_naive()`**: skrypt masowego replacementu podmienił też `return` wewnątrz definicji — naprawione ręcznie
3. ✅ **`require_admin` używane**: weryfikacja potwierdziła 14+ endpointów w `account.py` (m.in. L370, L777, L843, L906) — nie jest martwym kodem
4. ✅ **GAP-15: Auto-refresh w SymbolDetailPanel** (sesja G, 2026-03-31): `analysis` i `signals` odświeżane co 15s, ticker (`/api/market/ticker/{symbol}`) co 15s, `DataStatus` w nagłówku panelu z czasem ostatniej aktualizacji

### Stan (2026-03-31)
- 175/175 testów ✅
- TypeScript: 0 błędów ✅
- 0 deprecation warnings (`utc_now_naive`) ✅
- SymbolDetailPanel: live price + auto-refresh 15s ✅
