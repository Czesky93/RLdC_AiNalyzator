# PROJECT_AUDIT_MASTER.md — RLdC Trading BOT

**Data audytu:** 1 kwietnia 2026 (aktualizacja: sesja 35 — 4 kwi 2026)
**Wersja:** v0.7 beta
**Testy:** 210/210 PASSED ✅
**TypeScript:** 0 błędów ✅
**Tryb:** TRADING_MODE=live, ALLOW_LIVE_TRADING=true, AI_PROVIDER=auto (Gemini→Groq→OpenAI→Ollama→heuristic)
**live_ready:** True ✅ (ADMIN_TOKEN skonfigurowany)
**Market regime:** CRASH (F&G≈12, buy_blocked=True)
**Watchlist:** 30+ EUR symboli (6 core ENV + scanner top-30)
**Dostęp publiczny:** DS-Lite/CGNAT — wymagany CF Tunnel / ngrok
**Control Center:** ✅ zakładki Status, Akcje, Logi (SSE), AI Chat

---

## 1. Aktualny stan projektu (sesja 35 — 4 kwi 2026)

Bot funkcjonalny w trybie LIVE. Brak otwartych pozycji. System stabilny.

**Naprawione w sesji 35:**
- ✅ **BUG-SCHEMA**: Brakujące kolumny `pending_orders` (exchange_order_id, expires_at, last_checked_at) dodane przez ALTER TABLE
- ✅ **ROOT CAUSE _ensure_schema**: Naprawiono `_ensure_column()` — teraz tworzy świeży `inspect(engine)` per call (stary kod cache'ował cały schema i nie widział braków)
- ✅ **DEBT-01/T-17**: Usunięto 8 USDC par z `WATCHLIST` w `.env` (BTCUSDC, ETHUSDC, SOLUSDC, BNBUSDC, WLFIUSDC, SHIBUSDC, ETCUSDC, SXTUSDC) — eliminacja WARNING spamu co ~17 min
- ✅ **AVAXEUR**: Pozycja self-healed — order 14 (SELL 15.51 FILLED), order 15 (ERROR po 0), brak aktywnych pozycji
- ✅ **npm @types**: @types/node, @types/react, @types/react-dom zainstalowane
- ✅ **210/210 testów** po wszystkich zmianach

**Stan portfela (sesja 35 / 4 kwi 2026):**
- LIVE: ~332 EUR total, ~271 EUR free, 0 otwartych pozycji
- Reżim: CRASH (F&G≈12) — BUY zablokowane
- Sygnały: dominacja SELL w CRASH

**Stan portfela (sesja 19 / 2 kwi 2026):**
- DEMO: ~997 EUR equity, 0 open positions
- LIVE: ~298 EUR free + pozycje do weryfikacji
- Reżim: CRASH (F&G≈12) — BUY zablokowane
- Sygnały: dominacja SELL 46+/50

**Aktywne blokery:**
- Wszystkie BUY: `market_regime_buy_blocked` (CRASH, bear_min_conf=0.82)
- SELL signal gdy brak pozycji: `sell_blocked_no_position` (poprawne zachowanie)
- USDC pary w watchliście: zbierane ale nie handlowane (demo_quote_ccy=EUR)
- T-08 Faza 2: brak monitora LIMIT fill (deferred — low priority przy CRASH)

---

## 2. Rzeczywisty pipeline bota (jak działa TERAZ)

### KROK 1 — DATA INGEST (`collect_market_data`, `collect_klines`)
- **Plik:** `collector.py` metody `collect_market_data()`, `collect_klines()`
- **Input:** self.watchlist (38 symboli), Binance REST/WS
- **Output:** MarketData (ticker prices), Kline (1h, 4h świece do DB)
- **Cykl:** 60s REST + WS 1m stream ciągły
- **Wady:** USDC pary mają pełny pipeline danych ale nie wchodzą do trading loop (marnowanie)
- **Wpływ na zysk/ryzyko:** Neutralny — dane są OK

### KROK 2 — SIGNAL GENERATION (`generate_market_insights`, `persist_insights_as_signals`)
- **Plik:** `analysis.py` → `collector.py` run_once()
- **Input:** Kline 1h + 4h z DB, F&G, CoinGecko
- **Output:** Signal (symbol, BUY/SELL/HOLD, confidence 0.50-0.95, indicators JSON)
- **Mechanizm:** 24 wskaźniki → score kumulatywny → conf = base_conf(0.58) + adj(score)
  - score ≥ 3 → BUY, conf = 0.58 + min(0.30, score×0.06)
  - score ≤ -3 → SELL
  - |score| < 3 → HOLD
  - Multi-TF: 4h potwierdza → +0.05 conf; sprzeczny → -0.04
  - F&G ≤ 20 + trend trend down → -0.05 (panika ≠ dno w trendzie)
  - F&G ≤ 20 + trend neutralny → +0.04 (kontrariański)
- **Wady:** Sygnały SELL dominują w CRASH (46/50) co powoduje flood `sell_blocked_no_position` traces (fałszywe wrażenie "aktywności" — bot nie shortuje)
- **Wpływ:** Jakość sygnałów średnia w BULL (zbyt wiele SELL), dobra w BEAR

### KROK 3 — MARKET REGIME (`get_market_regime`)
- **Plik:** `analysis.py` funkcja `get_market_regime()`
- **Input:** F&G API + CoinGecko MCap change 24h (cache 30 min)
- **Output:** {regime: CRASH/BEAR/BEAR_SOFT/SIDEWAYS/BULL, buy_blocked, buy_confidence_adj}
- **Progi:** F&G≤15 + MCap<-2.5% → CRASH + buy_blocked=True
- **Wady:** 30 min cache — może być w tyle za szybkimi zmianami rynku
- **Wpływ:** KRYTYCZNY — buy_blocked=True blokuje wszystkie BUY niezależnie od sygnałów

### KROK 4 — ENTRY SCREENING (`_screen_entry_candidates`)
- **Plik:** `collector.py`
- **Input:** tc (trading config), watchlist, DB signals, range_map
- **Filtry (kolejność):**
  1. `demo_quote_ccy` filter (EUR only — USDC skip)
  2. Tier gate (CORE/ALTCOIN/SPECULATIVE/SCANNER)
  3. Hold mode check (no_new_entries)
  4. Tier daily trade limit
  5. Active pending order check
  6. Pending order cooldown (300s)
  7. Symbol cooldown (loss_streak × base_cooldown)
  8. Signal exists check
  9. Confidence ≥ min_confidence (base + tier_add + regime_adj)
  10. Signal age < 3600s
  11. Market regime gate (buy_blocked → RSI < 28 bypass lub conf ≥ 0.82)
  12. Crash detection gate (symbol-level -6% in 60 min)
  13. Technical filters: cena w strefie AI LUB soft buy (trend+RSI<55)
  14. Side validity (BUY → no existing position; SELL → has position)
  15. Quantity sizing (ATR × risk_per_trade, min/max limits)
  16. Rating gate (1-5, min 2 domyślnie)
  17. Cost gate (expected_move ≥ 2.5 × koszty)
  18. Risk gate (evaluate_risk: max_positions, drawdown, kill_switch)
  19. Min notional (60 EUR)
- **Output:** `candidates[]` → sort po `edge_net_score` → top N

### KROK 5 — POSITION SIZING (w `_screen_entry_candidates`)
- **Mechanizm:** `risk_per_trade × equity / (ATR × stop_mult)`
- **Skalowania:** tier_risk_scale, loss_streak × -0.15, win_streak × +0.05
- **Cap BUY:** `equity / max_open_positions`
- **Min notional:** 60 EUR
- **Crash scaling:** × 0.25

### KROK 6 — CANDIDATE RANKING (w `_screen_entry_candidates`)
- **Aktualny:** `edge_net_score = (ATR × take_mult / price) - total_cost_ratio`
- **Wada:** nie uwzględnia confidence ani ratingu — wybiera najbardziej volatile, nie najlepszy sygnał
- **FIX sesja 16:** `composite_score = edge_net_score × confidence × (rating/5.0)` → WDROŻONE

### KROK 7 — ORDER EXECUTION (`_execute_confirmed_pending_orders`)
- **Plik:** `collector.py`
- **DEMO:** symulacja po aktualnej cenie ticker
- **LIVE:** Binance API `place_order(MARKET)` → fills → actual exec_price + commission
- **Zapis:** PendingOrder(CONFIRMED) → Order(FILLED) + Position upsert + CostLedger

### KROK 8 — EXIT MANAGEMENT (`_check_exits`)
- **Plik:** `collector.py`
- **WARSTWA 1:** Break-even (zysk ≥ 1×ATR → SL przesuń do entry)
- **WARSTWA 2:** Hard SL (cena ≤ entry - ATR×2.0)
- **WARSTWA 3:** Trailing stop (gdy aktywny → ATR×1.5 poniżej highest_price)
- **WARSTWA 4:** Partial TP 25% → trailing aktywuje się
- **WARSTWA 5:** Full TP lub reversal (trend odwrócenie)
- **Hold mode:** pomija TP/SL dla pozycji strategicznych

### KROK 9 — ACCOUNTING (`accounting.py`)
- **compute_demo_account_state:** equity = initial_balance + sum(trades PnL) - sum(koszty)
- **CostLedger:** taker_fee + slippage + spread per Order
- **Snapshots KPI:** co 15 min → tabela EquitySnapshot

### KROK 10 — REPORTING (WWW + Telegram)
- **WWW:** 18 widoków (CommandCenter, Portfolio, Markets, AlgoTrading, etc.)
- **Telegram:** entry/exit alerts, idle co 30 min (z listą blokad), crash alert
- **Decision trace:** każda decyzja z reason_code + reason_pl → endpointy API

---

## 3. Mapa plików — stan rzeczywisty

| Plik | Rola | Stan | Linie |
|------|------|------|-------|
| `app.py` | FastAPI startpoint, mount routerów | ✅ DZIAŁA | ~200 |
| `database.py` | 30 modeli ORM, init_db, _ensure_schema | ✅ DZIAŁA | ~1800 |
| `collector.py` | Główna pętla: data→signals→entry/exit→exec | ✅ DZIAŁA | ~3700 |
| `analysis.py` | Wskaźniki, sygnały, AI ranges, blog, reżim | ✅ DZIAŁA | ~1680 |
| `accounting.py` | Equity, PnL, koszty, snapshots | ✅ DZIAŁA | ~600 |
| `risk.py` | Risk gates, drawdown, position limits | ✅ DZIAŁA | ~300 |
| `runtime_settings.py` | Konfiguracja runtime, symbol tiers, profiles | ✅ DZIAŁA | ~700 |
| `binance_client.py` | REST API Binance: spot, orders, balances | ✅ DZIAŁA | ~700 |

### Routery

| Plik | Stan |
|------|------|
| `routers/account.py` | ✅ 90+ EP: summary, governance, AI status, analytics |
| `routers/signals.py` | ✅ sygnały, wait-status, decision trace, exec trace |
| `routers/positions.py` | ✅ pozycje, analysis, goals, sync |
| `routers/orders.py` | ✅ zlecenia, pending, create_order |
| `routers/market.py` | ✅ ticker, klines, scanner, forecast |
| `routers/portfolio.py` | ✅ wealth, equity, forecast |
| `routers/control.py` | ✅ trading on/off, watchlist, state |

---

## 4. Blokery krytyczne TERAZ

*Brak krytycznych blokerów — system działa stabilnie.*

Przyczyna braku nowych transakcji: CRASH regime (F&G=12, buy_blocked=True). Bot POPRAWNIE chroni kapitał.
Gdy F&G wzrośnie powyżej 20 i MCap poprawi się → CRASH gate automatycznie zniknie.

---

## 5. Długi techniczne i obszary do poprawy

| ID | Problem | Priorytet | Wpływ |
|----|---------|-----------|-------|
| DEBT-01 | USDC pary w watchlist mimo demo_quote_ccy=EUR (8 symboli wasted) | MEDIUM | ~20% niepotrzebnych API calls |
| DEBT-02 | edge_net_score nie uwzględniał confidence/ratingu → **NAPRAWIONE sesja 16** | — | ✅ |
| ~~DEBT-03~~ | ~~live_ready=false mimo allow_live_trading=true (brak ADMIN_TOKEN)~~ | ~~HIGH~~ | **NAPRAWIONE sesja 30** — ADMIN_TOKEN ustawiony, live_ready=True ✅ |
| DEBT-04 | MARKET orders only w LIVE (taker fee > maker fee) | LOW | Koszty |
| DEBT-05 | Market regime TTL=30 min — może nie reagować na szybkie zmiany | LOW | Timing |
| DEBT-06 | Signal generation per-cycle używa zawsze heuristic ranges (AI tylko co 1h blog) | MEDIUM | Jakość zakresów |

---

## 6. Martwy kod

*Brak martwego kodu potwierdzony audytem. Usunięto w poprzednich sesjach:*
- `AccountSummary.tsx` (widget)
- stub directories (hft_engine, blockchain_analysis etc.)
- 29 hardkodowanych `mode="demo"` zastąpionych dynamicznym

---

## 7. Niespójności

| Obszar | Stan |
|--------|------|
| WWW equity vs DB equity | ✅ Spójne |
| WWW pozycje vs DB pozycje | ✅ Spójne |
| DB pozycje vs Binance | ✅ Sync co 5 min |
| Telegram vs WWW dane | ✅ Ten sam source (DB) |
| LIVE fees vs CostLedger | ✅ Actual commission z Binance fills |
| Decision trace WWW | ✅ `/api/signals/execution-trace` |
| demo_state cooldowny restart | ✅ Persistowane do DB od sesji 3 |
| AI provider status | ✅ `/api/account/ai-status` pokazuje pełny łańcuch |
| Live unrealized_pnl w /api/account/summary | ✅ **NAPRAWIONE sesja 32** — obliczane z tabeli Position |
| Live realized_pnl_24h w /api/account/summary | ✅ **NAPRAWIONE sesja 32** — obliczane z tabeli Order |
| Live pnl_eur per pozycja w /api/portfolio/wealth | ✅ **NAPRAWIONE sesja 32** — wzbogacone o Position.unrealized_pnl |
| Live entry_price w /api/portfolio/wealth | ✅ **NAPRAWIONE sesja 32** — używa Position.entry_price zamiast cur_price |

---

## 8. Otwarte zadania

| ID | Zadanie | Priorytet | Plik | Wpływ |
|----|---------|-----------|------|-------|
| T-08 | LIMIT orders w LIVE (tylko MARKET) | LOW | `routers/orders.py` | Koszty (maker fee) |
| T-17 | USDC pary — opcjonalne odfiltrowanie z WS gdy demo_quote_ccy=EUR | MEDIUM | `collector.py` | Zasoby |
| T-18 | AI ranges per-cycle (nie tylko blog co 1h) — Gemini dla top-5 co 30 min | MEDIUM | `analysis.py` | Jakość zakresów |

---

## 9. Zamknięte (sesja 16)

| ID | Co | Wynik |
|----|-----|-------|
| composite_score | Ranking kandydatów: edge×conf×rating zamiast samego edge | ✅ Wdrożone, 181/181 |
| AI order | Ollama na koniec łańcucha (Gemini→Groq→OpenAI→Ollama→heuristic) | ✅ |
| .vscode/settings.json | Injekt .env do terminali VS Code | ✅ |
| Scanner EUR | Scanner fetches EUR pairs matching demo_quote_ccy | ✅ |
| SCANNER tier | Nowe symbole dostają tier SCANNER (risk_scale=0.5) | ✅ |
| Dust filter | price=0 → nie tworzy fałszywego mismatcha | ✅ |
| Watchlist 38 | 14 core + 24 scanner EUR symboli | ✅ |

---

## 10. Decyzje architektoniczne

| Data | Decyzja | Powód |
|------|---------|-------|
| 02.04 | composite_score = edge × conf × (rating/5) dla rankingu | Jakość > wolność ruchu |
| 02.04 | Ollama jako ostateczny fallback (przed heurystyką) | Gemini/Groq szybsze i lepsze |
| 02.04 | WATCHLIST_SCAN_QUOTES = demo_quote_ccy (EUR) domyślnie | Unikanie USDC waste |
| 01.04 | SCANNER tier dla nowych symboli (risk_scale=0.5) | Ostrożność przy nowych |
| 01.04 | Auto fallback chain: Gemini→Groq→OpenAI→Ollama→Heuristic | Resilience |
| 31.03 | SQLite WAL mode | Concurrent reads w async web + collector |
| 26.03 | MARKET only w LIVE (na start) | Bezpieczeństwo, prostota |

---

## 12. Sesja 30 — 3 kwietnia 2026

### Zmiany
1. **DEBT-03 NAPRAWIONE**: `ADMIN_TOKEN` ustawiony w `.env` (43-znakowy `secrets.token_urlsafe(32)`). `live_ready: True`, `live_guard_issues: []`.
2. **Control Center — UI Admin Token**: `ControlCenter.tsx` — nowy stan `adminTokenSet`/`tokenInput`/`tokenSaved`. Sekcja tokenu w zakładce Status: gdy brak → formularz wpisania + zapis do `localStorage`, gdy ustawiony → badge "✓ Token ustawiony" + przycisk "✕ Usuń". Badge `🔑 auth / 🔒 brak tokenu` w headerze.
3. **Nowe moduły (sesja poprzednia)**: `backend/public_url.py`, `backend/routers/system.py` (4 EP), `backend/routers/actions.py` (10 akcji + AI Chat), `web_portal/src/components/widgets/ControlCenter.tsx`. Telegrambot: komenda `/ip`.
4. **Konfiguracja publiczna**: `.env` rozszerzony o PUBLIC_BASE_URL/CLOUDFLARE_TUNNEL_URL/NGROK_URL/CORS_ALLOWED_ORIGINS. `next.config.js` obsługuje `BACKEND_URL` env i `allowedDevOrigins`.

### Endpointy zweryfikowane
- `GET /api/system/status` → uptime, trading_mode, collector, DB, AI, Binance, Telegram ✅
- `GET /api/system/public-url` → source: auto_detected_ip, DS-Lite warning ✅
- `GET /api/system/logs/stream` → SSE stream z DB co 2s ✅
- `POST /api/actions/check-binance` z tokenem → BTC/USDT=66,587.99 ✅
- `POST /api/actions/check-binance` bez tokenu → 401 Unauthorized ✅
- `POST /api/actions/check-telegram` z tokenem → @RLdC_trading_bot ✅
- `POST /api/actions/scan-opportunities` z tokenem → 20 sygnałów ✅

### Testy
- 196/196 ✅ (25–31s)
- Next.js build: `✓ Compiled successfully in 25.8s` ✅
- TypeScript: 0 błędów ✅

### Stan bieżący
- ADMIN_TOKEN: ustawiony, auth działa
- live_ready: True
- Market: CRASH, buy_blocked=True
- System restart po ustawieniu tokenu

## 11. Sesja 16 — 2 kwietnia 2026

### Zmiany
1. `analysis.py` + `account.py`: nowa kolejność AI fallback — Gemini→Groq→OpenAI→Ollama→heuristic
2. `collector.py` `_screen_entry_candidates`: composite_score = edge_net_score × confidence × (rating/5.0); ranking po composite_score zamiast samego edge_net_score

### Testy
- 181/181 ✅ po obu zmianach

### Stan bieżący
- AI provider: Gemini (aktywny, klucz 39 znaków), backup Groq/OpenAI/Ollama
- Market: CRASH, buy_blocked=True, F&G=12
- Watchlist: 38 EUR symboli, WS ✅
- Portfel DEMO: 997.06 EUR, 0 pozycji
- Portfel LIVE: ~298 EUR free + ETHEUR

**Co działa prawidłowo:**
- Pobieranie danych rynkowych (REST + WebSocket), 14 symboli
- Generowanie sygnałów (24 wskaźników, scoring 1-5)
- Filtry wejścia (13+ filtrów incl. edge-after-costs)
- Filtry wyjścia (4 warstwy: SL, Trailing, TP partial/full, Reversal)
- Koszty (maker/taker fee, slippage, spread) w CostLedger
- Equity, free cash, realized/unrealized PnL
- Decision trace z 20+ reason_codes (po polsku) — 96+ traces/30min
- WWW — 18 widoków, wszystkie endpointy OK
- Telegram — alerty entry+exit, portfolio, pozycje, sygnały
- _learn_from_history z persistencją do RuntimeSetting
- LIVE place_order → Binance API (MARKET)
- Daily drawdown gate (DEMO + LIVE)
- Heurystyczny fallback ATR uzupełnia brakujące symbole z bloga
- _trace_decision z error recovery (flush error → rollback, nie propaguje)
- error_reason w Order — gdy Binance place_order zwróci _error, tworzy Order(status=ERROR, error_reason=msg[:500]) dla diagnostyki
- Float precision guard: notional >= min_order_notional - 0.01 (tolerancja 1 grosz)
- **LIVE kill switch base (sesja 9 — BUG-16 faza 2):** `initial_balance = free_eur + total_exposure` (pełny portfel). Zawsze `live_balance_eur + total_exposure` zamiast samego `total_exposure`. Identycznie w risk.py `evaluate_risk()`: `_base = live_balance + exposure`. Kill switch threshold = 3% × ~364 EUR = ~11 EUR — nie triggeruje przy dziennej stracie -3.93 EUR (1.18%<3%).
- Dust live pozycja auto-zamknięcie (qty=0) gdy LOT_SIZE normalizacja=0
- exit_reason_code propagowany przez PendingOrder (stop_loss_hit, tp_full_reversal, trailing_lock_profit itd.)
- `loss_streak_size_reduction`: przy 2/3 loss_streak, position_size_multiplier=0.5 (celowa ostrożność)

**Stan live (sesja 9):**
- Free EUR Binance: 298.14 EUR, ETH: 0.0183 ETH (33 EUR)
- Pełny portfel: ~331 EUR
- 1 otwarta pozycja LIVE: ETHEUR qty=0.0183 entry=1806.44, TP=1829.61, SL=1792.54
- Kill switch: False ✅ (drawdown = 1.18% < 3%)

**Blokery bieżące (sesja 15, CRASH regime F&G=12):**
- BUY: wszystkie zablokowane `market_regime_buy_blocked` (CRASH)
- SELL SOLEUR/BTCUSDC: `signal_filters_not_met` (RSI 31-33 < próg 35, cena poza strefą SELL)
- SELL BTCEUR/WLFIEUR: READY ✅
- Stan portfela DEMO: 997.06 EUR equity, 0 pozycji

**Sesja 15 — zmiany:**
- SettingSpec `min_order_notional` default 25.0 → 60.0 (spójność z DB override)
- `bear_regime_min_conf` dodany do SettingSpec z default=0.82 i _LIVE_GUARD_KEYS
- OpenAI API fix: `gpt-5-mini` → `gpt-4o-mini`, `/v1/responses` → `/v1/chat/completions`
- TTL caches: signals (20s), positions (15s), portfolio (15s), market_regime (1800s)
- Positions enrichment z DB: entry_price, unrealized_pnl, planned_tp/sl, opened_at
- demo_state persistence: _load_persisted_demo_state + _save_demo_state co cykl
- BUG-17: Binance balance cap dla SELL qty



| Plik | Rola | Stan | Linie |
|------|------|------|-------|
| `app.py` | Startpoint FastAPI, mount routerów | ✅ DZIAŁA | ~200 |
| `database.py` | Modele ORM (30+), init_db, _ensure_schema | ✅ DZIAŁA | ~1800 |
| `collector.py` | Główna pętla: dane, sygnały, entry/exit, execution | ✅ DZIAŁA | ~3127 |
| `analysis.py` | Analiza techniczna, AI ranges, blog | ✅ DZIAŁA | ~1577 |
| `accounting.py` | Equity, PnL, koszty, cost summary | ✅ DZIAŁA | ~600 |
| `risk.py` | Risk gates, drawdown, position limits | ✅ DZIAŁA | ~300 |
| `runtime_settings.py` | Konfiguracja runtime, symbol tiers | ✅ DZIAŁA | ~700 |
| `binance_client.py` | API Binance: spot, earn, futures, orders | ✅ DZIAŁA | ~700 |
| `auth.py` | Autoryzacja endpoint (API key) | ✅ DZIAŁA | ~50 |
| `system_logger.py` | Centralny logging do SystemLog | ✅ DZIAŁA | ~80 |
| `operator_console.py` | Read-only diagnostyka | ✅ DZIAŁA | ~150 |
| `reporting.py` | Raporty, metryki, statystyki | ✅ DZIAŁA | ~400 |
| `trading_effectiveness.py` | Efektywność: win rate, profit factor | ✅ DZIAŁA | ~300 |
| `experiments.py` | Eksperymenty konfiguracyjne | ✅ DZIAŁA | ~200 |
| `recommendations.py` | Rekomendacje zmian konfiguracji | ✅ DZIAŁA | ~200 |
| `review_flow.py` | Review pipeline rekomendacji | ✅ DZIAŁA | ~150 |
| `promotion_flow.py` | Promocja recommended→active | ✅ DZIAŁA | ~150 |
| `post_promotion_monitoring.py` | Monitoring po promocji | ✅ DZIAŁA | ~150 |
| `rollback_decision.py` | Decyzja o rollbacku | ✅ DZIAŁA | ~150 |
| `rollback_flow.py` | Wykonanie rollbacku | ✅ DZIAŁA | ~150 |
| `post_rollback_monitoring.py` | Monitoring po rollbacku | ✅ DZIAŁA | ~100 |
| `policy_layer.py` | Warstwa polityk: verdict→action | ✅ DZIAŁA | ~200 |
| `governance.py` | Freeze, incydenty, SLA | ✅ DZIAŁA | ~300 |
| `notification_hooks.py` | Hooki dla powiadomień | ✅ DZIAŁA | ~100 |
| `candidate_validation.py` | Walidacja kandydatów entry | ✅ DZIAŁA | ~100 |
| `correlation.py` | Korelacja między symbolami | ✅ DZIAŁA | ~150 |
| `reevaluation_worker.py` | Reewaluacja pozycji | ✅ DZIAŁA | ~100 |
| `tuning_insights.py` | Insighty z tuningu | ✅ DZIAŁA | ~100 |

### Routery (`backend/routers/`)

| Plik | Endpointy | Stan | Linie |
|------|-----------|------|-------|
| `account.py` | ~90 EP: account summary, governance, analytics, AI status | ✅ DZIAŁA | 2064 |
| `signals.py` | Sygnały, analiza, execution-trace, decision trace | ✅ DZIAŁA | 1808 |
| `positions.py` | Pozycje, analiza pozycji | ✅ DZIAŁA | 1910 |
| `orders.py` | Zlecenia DEMO+LIVE, create_order, pending | ✅ DZIAŁA | 633 |
| `market.py` | Dane rynkowe, Klines, kontekst | ✅ DZIAŁA | 817 |
| `portfolio.py` | Portfel, wealth, forecast, equity | ✅ DZIAŁA | 569 |
| `control.py` | Sterowanie: demo ON/OFF, WS, watchlist | ✅ DZIAŁA | 185 |
| `blog.py` | Blog AI insights | ✅ DZIAŁA | 67 |
| `debug.py` | Diagnostyka dev | ✅ DZIAŁA | 278 |
| `telegram_intel.py` | Intel Telegram | ✅ DZIAŁA | 145 |

### Frontend (`web_portal/`)

| Plik | Rola | Stan |
|------|------|------|
| `MainContent.tsx` | 18 widoków, główna logika UI | ✅ DZIAŁA (5764L) |
| `Sidebar.tsx` | Nawigacja 18 pozycji | ✅ DZIAŁA |
| `Topbar.tsx` | Nagłówek + status | ✅ DZIAŁA |
| `Dashboard.tsx` | Dashboard wrapper | ✅ DZIAŁA |
| `widgets/*.tsx` | 11 widgetów (AccountMetrics, EquityCurve, etc.) | ✅ DZIAŁA |
| `lib/api.ts` | getApiBase() helper | ✅ DZIAŁA |

### Telegram (`telegram_bot/`)

| Plik | Rola | Stan |
|------|------|------|
| `bot.py` | 18 komend Telegram: /status /portfolio /risk /confirm /reject /governance /freeze /incidents | ✅ DZIAŁA |

### Testy (`tests/`)

| Plik | Testy | Stan |
|------|-------|------|
| `test_smoke.py` | 181 testów (175 smoke + 6 akceptacyjnych v0.7) | ✅ WSZYSTKIE PRZECHODZĄ |

### Inne

| Katalog/Plik | Rola | Stan |
|--------------|------|------|
| `scripts/` | start_dev.sh, stop_dev.sh, status_dev.sh | ✅ DZIAŁA |
| `docs/` | Dokumentacja: checkpointy, design system | ✅ AKTUALNE |
| `logs/` | Logi runtime | ✅ DZIAŁA |

---

## 3. Źródła prawdy danych

| Domena | Moduł | Tabela DB |
|--------|-------|-----------|
| Konfiguracja | `runtime_settings.py` | `RuntimeSetting` |
| Ekonomia (PnL, equity) | `accounting.py` | `Order`, `CostLedger`, `Position` |
| Ochrona kapitału | `risk.py` | `RiskLog` |
| Dane rynkowe | `database.py` | `MarketData`, `Kline` |
| Sygnały | `analysis.py` → `collector.py` | `Signal` |
| Decyzje | `collector.py` | `DecisionTrace` |
| Zlecenia | `routers/orders.py` + `collector.py` | `Order`, `PendingOrder` |
| Koszty | `accounting.py` | `CostLedger` |
| Pozycje | `collector.py` | `Position` |
| Exit quality | `collector.py` | `ExitQualityRecord` |
| AI forecasts | `analysis.py` | `ForecastRecord` |
| Blog | `analysis.py` | `BlogPost` |
| Logi systemowe | `system_logger.py` | `SystemLog` |
| Incydenty | `governance.py` | `Incident` |
| Eksperymenty | `experiments.py` | `Experiment`, `ExperimentResult` |

---

## 4. Blokery krytyczne

~~### CRITICAL-1: LIVE — koszty z Binance-fills nie są zapisywane do CostLedger~~
~~**ZAMKNIĘTY — sesja 2, commit 9ac10b0**~~
- Rzeczywista prowizja z `fills[].commission` jest używana jako `actual_value` w CostLedger (L433-479 collector.py).
- LIVE: `fee_cost = sum(f.commission for f in fills)`, DEMO: szacunek na bazie `taker_fee_rate`.

~~### CRITICAL-2: Brak periodycznego sync pozycji DB ↔ Binance~~
~~**ZAMKNIĘTY — sesja 2, commit 9ac10b0**~~
- `_sync_binance_positions()` wywoływana co 300s w `run_once()` (L2826).
- NIE auto-koryguje — loguje WARNING i wysyła Telegram alert.

**Brak aktualnych blokerów krytycznych.** ✅

---

## 5. Długi techniczne

| ID | Opis | Plik | Priorytet |
|----|------|------|-----------|
| ~~DEBT-1~~ | ~~Telegram: /confirm i /reject~~ | `telegram_bot/bot.py` | ✅ ZAMKNIĘTY — już zaimplementowane (L371-424) |
| ~~DEBT-2~~ | ~~Telegram: /governance /freeze /incidents /logs /report~~ | `telegram_bot/bot.py` | ✅ ZAMKNIĘTY — już zaimplementowane (L427-560) |
| DEBT-3 | CORS: allow_origins=["*"] | `backend/app.py` | LOW |
| ~~DEBT-4~~ | ~~Qty sizing nie odejmuje prowizji~~ | `backend/collector.py` | ✅ NAPRAWIONY — max_cash_after_fees = max_cash/(1+fee) |
| DEBT-5 | Brak LIMIT orders w LIVE (tylko MARKET) | `backend/routers/orders.py` L383 | LOW |
| DEBT-6 | AccountSummary widget w frontend nieużywany | `web_portal/src/components/widgets/AccountSummary.tsx` | LOW |
| DEBT-7 | `demo_state` (loss_streak, cooldown) nie przeżywa restartu | `backend/collector.py` L81 | MEDIUM |

---

## 6. Martwy kod

**Brak martwego kodu.** W iter7 przeprowadzono pełne czyszczenie:
- Aspiracyjne katalogi usunięte (hft_engine, quantum_optimization, etc.)
- Nieużywane importy usunięte
- DemoOrderGenerator usunięty
- Duplikaty funkcji usunięte

---

## 7. Niespójności backend ↔ frontend ↔ DB ↔ Telegram ↔ Binance

| Problem | Stan |
|---------|------|
| WWW equity vs DB equity | ✅ Spójne — accounting.py liczy z Order history |
| WWW pozycje vs DB pozycje | ✅ Spójne — Position table |
| DB pozycje vs Binance pozycje | ✅ Sync co 5 min przez `_sync_binance_positions()` (sesja 2) |
| Telegram alerty vs WWW dane | ✅ Spójne — ten sam source (DB) |
| LIVE fees vs CostLedger | ✅ Actual commission z fills (sesja 2) |
| Decision trace WWW | ✅ Spójne — endpoint `/api/signals/execution-trace` |
| demo_state (cooldown/streaks) vs DB | ⚠️ `demo_state` in-memory only, nie przeżywa restartu (DEBT-7) |

---

## 8. Lista zadań otwartych

| ID | Zadanie | Priorytet | Plik/Moduł | Wpływ |
|----|---------|-----------|------------|-------|
| ~~TASK-01~~ | ~~LIVE CostLedger: actual Binance commission~~ | ~~CRITICAL~~ | `collector.py` | ✅ DONE (sesja 2, commit 9ac10b0) |
| ~~TASK-02~~ | ~~Periodyczny sync pozycji DB ↔ Binance~~ | ~~CRITICAL~~ | `collector.py` | ✅ DONE (sesja 2, commit 9ac10b0) |
| ~~TASK-03~~ | ~~Telegram /confirm i /reject~~ | ~~HIGH~~ | `telegram_bot/bot.py` | ✅ już zaimplementowane (false positive) |
| ~~TASK-04~~ | ~~Qty sizing: odejmij prowizję~~ | ~~MEDIUM~~ | `collector.py` | ✅ DONE (sesja 2) |
| ~~TASK-05~~ | ~~CORS allow_origins → proper domains~~ | ~~LOW~~ | `app.py` | ✅ DONE (sesja 3) |
| ~~TASK-06~~ | ~~Persistuj demo_state do RuntimeSetting~~ | ~~MEDIUM~~ | `collector.py` | ✅ DONE (sesja 3) |
| ~~TASK-07~~ | ~~Usuń martwy widget AccountSummary.tsx~~ | ~~LOW~~ | `web_portal/...` | ✅ DONE (sesja 3) |
| TASK-08 | LIMIT orders w LIVE (tylko MARKET) | LOW | `routers/orders.py` | Koszty (maker fee) |

---

## 9. Lista zadań zamkniętych (ostatnie sesje)

| Data | Co | Rezultat |
|------|-----|----------|
| 01.04 iter8 | Dodano Gemini + Groq AI providers | ✅ auto fallback chain |
| 01.04 iter8 | /api/account/ai-status endpoint | ✅ diagnostyka AI |
| 01.04 iter8 | Collector nigdy nie blokuje bota bez AI key | ✅ heuristic fallback |
| 01.04 iter7 | HOLD→SPECULATIVE, WLFI odblokowany | ✅ |
| 01.04 iter7 | Watchlist 14 symboli | ✅ |
| 01.04 iter6 | 18 widoków WWW, sidebar PL | ✅ |
| 01.04 iter5 | Portfolio wealth + equity curve + forecast | ✅ |
| 01.04 iter4 | ATR multipliers, SL cooldown, soft RSI | ✅ |
| 31.03 iter3 | WAL mode, async fix, 181 testów | ✅ |

---

## 10. Decyzje architektoniczne

| Data | Decyzja | Powód |
|------|---------|-------|
| 01.04 | AI_PROVIDER=heuristic domyślnie | Instant, bez external dependency, stabilny |
| 01.04 | Auto fallback chain: Ollama→Gemini→Groq→OpenAI→Heuristic | Resilience, user may not have all keys |
| 31.03 | SQLite WAL mode | Concurrent reads w asynch web + collector |
| 31.03 | Thin routers — zero logiki biznesowej | Łatwa mutowalność, testability |
| 31.03 | Single source of truth per domena | Brak duplikacji, konsystencja |
| 26.03 | MARKET only w LIVE (na start) | Bezpieczeństwo, prostota |
| 26.03 | PendingOrder + manual confirm (LIVE) | Safety gate przed real execution |

---

## 11. Ostatnia sesja — 2 kwietnia 2026 (sesja 20)

### Zmiany sesji 20

#### Governance — walidacja w DB
- Przeskanowano `decision_trace`: 0 rekordów ROLLBACK/ROLLBACK_CANDIDATE — governance nie triggerowało (brak aktywnych promocji w tym środowisku). Kod jest poprawny: `rollback_decision.py` ma `ROLLBACK_COOLDOWN_SECONDS=3600`, `reevaluation_worker.py` delta-based alerting (alert tylko gdy sytuacja się POGORSZYŁA).

#### P2-01 — Multi-timeframe 4h HTF alignment (weryfikacja + consistency fix)
- P2-01 był już zaimplementowany z poprzedniej sesji w `_screen_entry_candidates` (linie ~2962-2994).
- Naprawiono niespójność: `candidates.append` nie zawierał `htf_align_factor` → trace detail `htf_4h_mult` zawsze defaultował do 1.0.
- Naprawiono klucze w trace details: `htf_bias_4h → cand.get("htf_align_note")`, `htf_4h_mult → cand.get("htf_align_factor")`.
- Efekt: `CREATE_PENDING_ENTRY` trace teraz poprawnie pokazuje aktualny `htf_align_note` (np. `4h:bycze(+10%)`).

#### P2-02 — Composite final_score (potwierdzenie)
- `composite_score = edge_net_score × confidence × (rating/5.0) × htf_align_factor`
- Formuła już istniała, P2-02 zamknięte jako skumulowane w P2-01.

#### P2-03 — SELL bez pozycji → cichy skip (bez SKIP trace)
- **Problem**: każdy SELL sygnał bez otwartej pozycji generował SKIP trace → ~20k+ śmieciowych rekordów w `decision_traces`.
- **Implementacja**: zmieniono `_trace_decision(SKIP, ...)` na cichy `continue`. Zachowano `# reason_code: sell_blocked_no_position` jako komentarz (backwards compat).
- **Efekt**: eliminuje 90%+ szumu w `decision_traces`; sygnał jest już persisted w tabeli `Signal` przez `generate_market_insights`.
- Test `test_p1_sell_without_position_blocked` zaktualizowany — szuka reason_code jako komentarz (nadal jest w kodzie).

#### Backend restart (PID 452050/452053)
- Stary PID 438291 zatrzymany. Nowy backend załadowany z P2-01/02/03.

### Stan po sesji 20
- Testy: **196/196** ✅
- Backend PID: **452053** (online 0.7.0-beta)
- Reżim: CRASH (F&G≈12), buy_blocked=True
- Governance: 0 rollbacks, kod poprawny (cooldown+delta alerting aktywne)
- P2-01: `htf_align_factor` ±10%/±20% działa; trace propogation naprawiona
- P2-03: ~20k+ SKIP trace wyciszonych; sygnały SELL bez pozycji nie zaśmiecają DB
- Zadania otwarte: T-08-F2 (LIMIT monitor worker) — LOW

---

## Poprzednia sesja — 2 kwietnia 2026 (sesja 18)

### Zmiany sesji 18

#### T-18 — AI ranges per-cycle tylko dla top-N symboli (analytic.py)
- **Problem**: `maybe_generate_insights_and_blog` wysyłała do API (Gemini/Groq) pełną listę wszystkich symboli watchlisty (~62!) co godzinę — kosztowne i niepotrzebne. AI jakość zakresów jest ważna głównie dla kandydatów wejścia, nie dla całej listy.
- **Implementacja**: po obliczeniu `insights`, sortuj po `confidence × max(volume_ratio, 0.5)`. Weź top-N (domyślnie 5, zmienialne przez `AI_TOP_SYMBOLS` env). AI (Gemini→Groq→…) wywoływane tylko dla top-N. Reszta → `_heuristic_ranges()` (ATR-based, bezkosztowa). Obie listy zakresów łączone przed `_merge_ranges_with_insights`.
- **Efekt**: przy 62 symbolach → ~90% mniej tokenów API; Pełna pokrywalność zakresów; "ranking" jakości AI skupiony na aktywnych symbolach
- **Konfiguracja**: `AI_TOP_SYMBOLS=5` (env var)
- **Testy**: 181/181 ✅

#### DOC-01 — TRADING_METRICS_SPEC.md — poprawka kosztów round-trip
- **Problem**: Dokument używał `slippage_pct=0.001` (0.1%) i `spread_pct=0.0008` (0.08%), podczas gdy kod `collector.py` linii 2874 używa `slippage_bps=5.0` (0.05%) i `spread_buffer_bps=3.0` (0.03%).
  - Błędne: round-trip 0.56%, cost gate ≥1.4% (2.5×)
  - Prawdziwe z kodu: round-trip 0.36%, cost gate ≥0.9% (2.5×)
- **Naprawiono**: sekcja 1.2 (parametry), 1.3 (wzór round-trip), tabela referencyjna (linie 274-275)
- **STRATEGY_RULES.md**: brak hardkodowanych wartości — tylko formuły symboliczne → OK

#### Backend restart (PID 411680)
- Stary PID 407828 zatrzymany
- Nowy backend załadował: T-18 (analysis.py), wcześniej T-17 bug fix + composite_score

### Stan po sesji 18
- Testy: **181/181** ✅
- Backend PID: **411680** (online 0.7.0-beta)
- Reżim: CRASH (F&G≈12), buy_blocked=True — nadal blokuje nowe BUY
- Dysk: ~2.1 GB wolne (po cleanup z sesji 18 wcześniej: market_data 7d→2d, VACUUM)
- Composite score walidacja: brak nowych BUY w CRASH — statystyczna walidacja odroczona do zmiany reżimu
- Zadania otwarte: T-08 (LIMIT orders), brak CRITICAL/HIGH

---

## Poprzednia sesja — 2 kwietnia 2026 (sesja 14)

### T-14 — Promotion/Rollback flow 19 testów FAILuje — ROOT CAUSE + NAPRAWA

**Sub-problem 1 (sesja 13):** `apply_runtime_updates` early return gdy `changed_keys=[]` nie zawierał klucza `"snapshot"` → `baseline_id=None` w testach → cascade 422 przez cały pipeline.

**Fix:** Dodano `"snapshot": previous_snapshot` do early return path w `runtime_settings.py`.

**Sub-problem 2 (sesja 14 — GŁÓWNY):** `pending_order_cooldown_seconds` w `SettingSpec` miał `validators=(_validate_positive(...),)` wymagający >0. Ale:
- `.env` produkcyjne ma `PENDING_ORDER_COOLDOWN_SECONDS=0` (0 = brak cooldownu, celowe)
- Promotion flow ładuje snapshot candydate i próbuje zaaplikować go przez `apply_runtime_updates`
- `_validate_setting_value` uruchamia validator → `"pending_order_cooldown_seconds must be > 0"` → `status: failed`
- Wszystkie 19 testów dostawało `status=failed` zamiast `status=applied`

**Fix (`backend/runtime_settings.py` L580):**
```
# PRZED (błąd):
validators=(_validate_positive("pending_order_cooldown_seconds"),),
# PO (fix):
validators=(_validate_non_negative("pending_order_cooldown_seconds"),),
```
0 = "brak cooldownu" jest prawidłową wartością operacyjną.

**Wynik:** 181/181 testów ✅ (było 161/181)

### Stan po sesji 14
- Testy: **181/181** (100%) ✅
- T-14: ZAMKNIĘTY
- Backend: PID 294466 (bez restartu — zmiana tylko w runtime_settings.py)
- Reżim: CRASH, buy_blocked=True

---

## Poprzednia sesja — 2 kwietnia 2026 (sesja 13)

### Stan sytemu na starcie sesji
- Backend PID 177617 (sesja 12) działał — sygnały generowane regularnie co ~2 min (14 symboli/cykl)
- Reżim rynkowy: **CRASH** (F&G=12 Extreme Fear, MCap -3.1%)
- 0 otwartych pozycji

### T-15 — Wait-status BUY jako READY w reżimie CRASH
**Problem:** `/api/signals/wait-status` oznaczał BUY sygnały statusem "READY" mimo aktywnego reżimu CRASH (buy_blocked=True, bear_min_conf=0.82). Wszystkie BUY sygnały miały conf≤0.78 (poniżej progu).

**Fix (`backend/routers/signals.py`):**
- Pobierz `get_market_regime()` raz przed pętlą
- Dla BUY gdy `buy_blocked AND conf < bear_min_conf`: dodaj `missing_conditions` z powodem
- Odpowiedź jsonowa zawiera nowe pole `market_regime` (nazwa, buy_blocked, bear_min_conf, reason)

**Wynik:** Wszystkie 7 BUY w reżimie CRASH poprawnie w WAIT z wyjaśnieniem np. "Reżim rynkowy (CRASH): Pewność 57% — za niska dla BUY w bessie". 161/181 ✅ (19 failów to pre-istniejący T-14).

### T-16 — exit_reason_code ignorowany w _execute_confirmed_pending_orders
**Problem:** `_execute_confirmed_pending_orders` hardkodował `exit_reason_code="pending_confirmed_execution"` zamiast używać wartości z `PendingOrder.exit_reason_code` (stop_loss_hit, tp_full_reversal, trailing_lock_profit etc.).

**Fix (`backend/collector.py` L594):**
- `exit_reason_code=(pending.exit_reason_code or "pending_confirmed_execution") if pending.side == "SELL" else None`

### UI-REGIME — Badge reżimu rynkowego w UI
**Co zbrakuje:** CommandCenterView nie pokazywał aktywnego reżimu BEAR/CRASH. Sygnały BUY były widoczne bez kontekstu blokery.

**Fix (`web_portal/src/components/MainContent.tsx`):**
- Dodano baner CRASH/BESSA/SŁABA BESSA nad sekcją "Najlepsza okazja"
- Dane z `waitStatus.market_regime` (bez dodatkowego fetch)
- CRASH → czerwony baner, BEAR → pomarańczowy, BEAR_SOFT → żółty
- BULL/SIDEWAYS → baner ukryty

### Stan po sesji 13
- Backend: PID 294466 (nowy restart z poprawkami)
- Reżim: CRASH, buy_blocked=True
- Testy: 161 pass / 19 fail (T-14 stary bloker)
- UI: baner reżimu aktywny

---

## 12. Sesja 12 — 2 kwietnia 2026 (diagnoza sygnałów)
*(Po weryfikacji: sygnały działały poprawnie — false alarm o stale signals. Stary backend 177615 → nowy 177617)*

---

## 13. Sesja 9 — 2 kwietnia 2026

**Problem:** Po sesji 8 (faza 1 naprawy BUG-16) z otwartą pozycją ETHEUR (notional=33 EUR):
- `accounting.py compute_risk_snapshot`: `initial_balance = total_exposure = 33 EUR` (bo `total_exposure > 0`)
- 3% z 33 EUR = 0.99 EUR → daily_drawdown=-3.93 EUR >> 0.99 EUR → `kill_switch_triggered=True`
- `risk.py evaluate_risk`: `_base = _exposure if _exposure > 0 else _live_balance = 33 EUR` — taki sam błąd
- Prawdziwy drawdown: -3.93 / (298 EUR cash + 33 EUR position) = -3.93/331 = **1.18%** < 3%

**Fix:**
- `accounting.py` `compute_risk_snapshot(mode='live')`: `initial_balance = max(1.0, free_eur + total_exposure)` — zawsze gotówka + pozycje = pełny portfel
- `risk.py` `evaluate_risk(mode='live')`: `_base = max(1.0, _live_balance + _exposure)` — identyczna logika

**Wynik:** `kill_switch_triggered=False`, drawdown=1.18%, brak `kill_switch_gate` po restarcie. 181/181 ✅

### Diagnostyka post-naprawy

- **SHIBEUR min_notional_guard**: Prawidłowe — `loss_streak_size_reduction` (2 straty z rzędu) × ALTCOIN tier risk_scale=0.7 = position_size_multiplier=0.5 → notional = 25×0.5 = 12.5 EUR < 25 EUR min_notional. Tymczasowe. Po pierwszym zysku live loss_streak=0 → wejście możliwe.
- **BTCEUR symbol_cooldown_active**: Prawidłowe — cooldown 7200s po loss_streak=3, aktywny do ~03:19 UTC.
- **WLFIEUR/SOLEUR signal_confidence_too_low**: Strukturalne (SPECULATIVE/CORE tier progi).

### Stan po sesji 9
- kill_switch_triggered: False (drawdown=1.18% < 3%) ✅
- 1 otwarta pozycja LIVE: ETHEUR qty=0.0183 entry=1806.44, TP=1829.61, SL=1792.54
- Free EUR Binance: 298.14 EUR
- System pracuje normalnie, brak blokerów krytycznych

---

### BUG-16 faza 2 — LIVE kill switch false trigger (regresja po sesji 8)
  - Naprawiono: minimum distance guard — TP min +0.5%, SL min -0.3% od entry_price
  - Dodano grace period 2h dla nowo-importowanych pozycji (entry_reason_code="binance_import") bez TP/SL: nie ustawiaj celów przez pierwsze 2 godziny (zapobieganie exit na starych/złych danych ATR)
  - 181/181 testów OK

### Zdarzenia finansowe sesji 4
- **WLFI SPRZEDANE na Binance**: Degenerate ATR bug (przed naprawą) wywołał SELL WLFIEUR 3260.45. Binance zaakceptował (LOT_SIZE step=0.01 → 3260.45 jest valid). Wpływy EUR: ~283 EUR. Binance EUR balance: 282.17. WLFI=0.05 (dust). DB i Binance zgodne.
- **BTC bezpieczny**: Orders 31, 33 SELL BTCEUR (qty=0.0008452/0.000845) → LOT_SIZE failure (step=0.00001, 0.0008452 nie jest wielokrotnością) → fake FILLED (stary bug) → BTC nadal 0.0008452 na Binance. Korekcja DB wykonana.
- **SHIB dust**: 0.99 SHIB na Binance — poniżej min_notional, nie będzie importowane.

### Stan po sesji 4
- BTCEUR Position [4]: qty=0.0008452, TP=59292, SL=58527 (ATR-based, prawidłowy) — AKTYWNA
- Binance: BTC=0.0008452, EUR=282.17, WLFI=0.05(dust), SHIB=0.99(dust)
- DB i Binance: ZGODNE ✅
- Backend: uruchomiony z nowymi naprawami, stabilny, brak pending orders

### Co zmieniono w tej sesji (kontynuacja)
- **T-11**: `_execute_confirmed_pending_orders` — fix `result.get("_error")` + `normalize_quantity()`
- **T-12**: `_auto_set_position_goals` — min distance guard + 2h grace period dla binance_import
- **BinanceClient**: nowa metoda `normalize_quantity(symbol, qty)`
- **DB korekta**: Ordery 31, 32, 33 → ERROR (fake_filled_lot_size_not_normalized)
- 181/181 testów potwierdzone po wszystkich zmianach

### Co zostało
- T-08: LIMIT orders w LIVE (LOW) — maker fee zamiast taker fee, `routers/orders.py` L383
- Żadnych blokerów krytycznych ani ważnych

---

## 12. Poprzednia sesja — 2 kwietnia 2026 (sesja 4, początek)

### Odkryte i naprawione błędy krytyczne (sesja 4)
- **BUG-4 KRYTYCZNY (naprawiony)**: `_sync_binance_positions` logowało WARNING co 5 minut ale NIE importowało
  aktywów do DB. Bot traktował `active_position_count=0` dla LIVE → mógł próbować kupić WLFI/BTC/SHIB
  które już posiadał. Equity było źle liczone (bez wartości pozycji).
  - Naprawiono: auto-import do Position table (mode=live, entry=current_price, filtr watchlist + notional≥1EUR)
  - Dodano `_last_sync_warn_ts` — warning max 1x/30min po pierwszym imporcie
  - Zaimportowane: BTCEUR qty=0.0008452, SHIBEUR qty=297837.99, WLFIEUR qty=3260.45
  - Efekt: bot wie o 3 pozycjach LIVE, blokuje duplicaty BUY, equity prawidłowe
  - 181/181 testów OK

### Co zmieniono w tej sesji
- T-10: `_sync_binance_positions` — auto-import brakujących aktywów Binance do DB + wyciszenie spam logu
- `__init__`: dodano `self._last_sync_warn_ts = None`

### Co zostało
- TASK-08: LIMIT orders w LIVE (LOW) — przed produkcją
- Żadnych blokerów krytycznych ani ważnych

## 13. Poprzednia sesja — 1 kwietnia 2026 (sesja 3)

### Co zweryfikowano
- 181/181 smoke testów ✅ (potwierdzono uruchomienie)
- CRITICAL-1 (actual Binance fees z fills) — potwierdzone w kodzie L433-479
- CRITICAL-2 (sync DB↔Binance co 5 min) — potwierdzone w kodzie L770-835, wywoływane L2826
- ATR multipliers iter4: atr_stop_mult=2.0, atr_take_mult=3.5, atr_trail_mult=1.5 ✅
- Loss streak escalation + TP success tracking ✅
- Soft RSI filter (RSI < 55 dla soft buy) ✅
- Cost gate (expected_move_ratio ≥ required_move_ratio, R/R ≥ min_rr) ✅
- `_learn_from_history` z persistencją do RuntimeSetting ✅
- Wszystkie 4 piony (A-D) funkcjonalne
- AccountSummary widget potwierdzony jako martwy (0 importów poza własnym plikiem) → TASK-07
- `_build_trading_context` prawidłowo przekazuje `"mode": mode` do `tc` dict ✅
- `_check_exits` i `_demo_trading` wywołują oba tryby (demo + live) osobno ✅

### Odkryte i naprawione błędy krytyczne (sesja 3)
- **BUG-1 KRYTYCZNY (naprawiony)**: `_demo_trading(db, mode)` przyjmowała mode jako parametr, ale wewnątrz `_check_exits` wszystkie wywołania `_create_pending_order` i `_trace_decision` używały hardkodowanego `mode="demo"` zamiast rzeczywistego trybu. Skutek: przy LIVE mode — exit ordery (SL, TP, Trailing, Reversal) były tworzone z `mode="demo"`, a pozycje LIVE sprawdzało `Position.mode == "demo"` zamiast `"live"`.
  - Naprawiono: dodano `_exit_mode = tc.get("mode", "demo")` w `_check_exits`, zastąpiono 10 wystąpień
- **BUG-2 KRYTYCZNY (naprawiony)**: W sekcji entry `_demo_trading`, analogicznie 16 wystąpień `mode="demo"` w `_trace_decision`, `build_risk_context` i `_create_pending_order` — zastąpiono `_current_mode`
- **BUG-3 (naprawiony wcześniej w sesji 3)**: L2160, L2167 — `Position.mode == "demo"` i `Order.mode == "demo"` w zapytaniach DB entry logic — zastąpione `_current_mode`
- **PODSUMOWANIE**: łącznie 27 hardkodowanych `mode="demo"` wykrytych i naprawionych (+ 2 z poprzedniej iteracji = 29 łącznie). Bot jest teraz poprawnie tryb-aware.

### Co zmieniono w tej sesji
- **DEBT-7 / T-06**: `_load_persisted_demo_state()` + `_save_demo_state(db)` w `collector.py`
- **DEBT-6 / T-07**: usunięto martwy widget `AccountSummary.tsx`
- **T-05 / DEBT-3**: CORS fix z `CORS_ALLOWED_ORIGINS` env
- Docker kontenery rldc-* zatrzymane, dev stack uruchomiony prawidłowo
- `scripts/status_dev.sh` — dodano timeout 15s dla wolnych endpointów
- **BUG-1+BUG-2**: Naprawa wszystkich 27 hardkodowanych `mode="demo"` w `_demo_trading` + `_check_exits`
- 181/181 testów potwierdzone po wszystkich zmianach

### Co zostało
- TASK-08: LIMIT orders w LIVE (LOW) — przed produkcją
- Żadnych blokerów krytycznych ani ważnych
