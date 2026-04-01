# MASTER_INDEX — RLdC AiNalyzator v0.7 beta
*Kompletny indeks plików projektu: rola, stan, powiązania.*
*Ostatnia aktualizacja: 2026-04-01 (iter7 — HOLD→SPECULATIVE, watchlist 14 symboli, 18 widoków)*

---

## DOKUMENTY PROJEKTU (root)

| Plik | Rola | Stan |
|------|------|------|
| [README.md](README.md) | Instrukcja uruchomienia, opis projektu | Aktualny |
| [PROGRAM_REVIEW.md](PROGRAM_REVIEW.md) | Głęboki audyt kodu backend — każda funkcja | Aktualny |
| [TASK_QUEUE.md](TASK_QUEUE.md) | Kolejka zadań (stary format) | Archiwum |
| [requirements.txt](requirements.txt) | Zależności Pythona | Aktualny |
| [instrukcje.txt](instrukcje.txt) | Instrukcje operacyjne | Aktualny |

## DOKUMENTY (`docs/`)

| Plik | Rola | Stan |
|------|------|------|
| [docs/QUICK_START.md](docs/QUICK_START.md) | **🟢 Zacznij stąd** — jak uruchomić, adresy | Aktualny |
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | Plan projektu, kamienie milowe | Aktualny |
| [docs/ETAP_C_SYMBOL_TIERS_REPORT.md](docs/ETAP_C_SYMBOL_TIERS_REPORT.md) | Raport tierów symboli (CORE/ALTCOIN/SPECULATIVE) | Aktualny |
| [docs/IMPLEMENTATION_SUMMARY.md](docs/IMPLEMENTATION_SUMMARY.md) | Podsumowanie implementacji | Aktualny |
| [docs/C0_CHECKPOINT_REPORT.md](docs/C0_CHECKPOINT_REPORT.md) | Raport checkpoint C0 | Aktualny |
| [docs/COMPONENT_LIBRARY.md](docs/COMPONENT_LIBRARY.md) | Biblioteka komponentów UI | Aktualny |
| [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) | System designu (kolory, typografia, spacing) | Aktualny |

## ARCHIWUM (`docs/archive/`)

Starsze dokumenty przeniesione do archiwum:

| Plik | Rola |
|------|------|
| `docs/archive/START_HERE.md` | Dawny punkt wejścia |
| `docs/archive/CURRENT_STATE.md` | Dawny stan projektu |
| `docs/archive/FUNCTIONS_MATRIX.md` | Macierz ~108 funkcji |
| `docs/archive/OPEN_GAPS.md` | Lista braków |
| `docs/archive/SYSTEM_RULES.md` | Zasady systemu |
| `docs/archive/CHANGELOG_LIVE.md` | Dziennik zmian (sesje A-F) |
| `docs/archive/MASTER_INDEX.md` | Stary indeks |
| `docs/archive/MASTER_GAP_REPORT.md` | Raport statusu (starszy format) |
| `docs/archive/MASTER_PROMPT.md` | Główny prompt |
| `docs/archive/PROJECT_AUDIT_MASTER.md` | Masterplan audytu |
| `docs/archive/TRADING_GOAL.md` | Cel handlowy |
| `docs/archive/CORE_TRADING_PRIORITY.md` | Priorytety handlowe |
| `docs/archive/CHECKLIST_OPERACYJNA.md` | Checklista operacyjna |

---

## BACKEND (`backend/`)

### Rdzeń aplikacji

| Plik | Rola | Kluczowe klasy/funkcje |
|------|------|------------------------|
| [backend/app.py](backend/app.py) | FastAPI entry point, CORS, montowanie routerów, uruchomienie kolektora | `create_app()` |
| [backend/database.py](backend/database.py) | SQLite, 30 modeli SQLAlchemy, inicjalizacja DB | `get_db()`, `init_db()`, wszystkie modele ORM |
| [backend/__init__.py](backend/__init__.py) | Pakiet | — |

### Logika biznesowa

| Plik | Rola | Kluczowe funkcje |
|------|------|-----------------|
| [backend/analysis.py](backend/analysis.py) | Generowanie sygnałów AI/heurystycznych, prognozy, insights | `maybe_generate_insights_and_blog()`, `persist_insights_as_signals()`, `AI_PROVIDER` |
| [backend/collector.py](backend/collector.py) | Kolektor cyklu (60s): zbiera dane, generuje sygnały, podejmuje decyzje | `Collector`, `run_once()`, `_learn_from_history()`, `_load_persisted_symbol_params()` |
| [backend/risk.py](backend/risk.py) | Metryki ryzyka, drawdown, limity | `get_risk_metrics()` |
| [backend/accounting.py](backend/accounting.py) | Snapshotty equity, historia konta | `take_snapshot()` |
| [backend/binance_client.py](backend/binance_client.py) | Wrapper Binance REST API | `BinanceClient`, `get_price()`, `get_portfolio()` |
| [backend/recommendations.py](backend/recommendations.py) | Rekomendacje per symbol | `get_recommendations()` |
| [backend/correlation.py](backend/correlation.py) | Korelacje między symbolami | `compute_correlations()` |
| [backend/trading_effectiveness.py](backend/trading_effectiveness.py) | Skuteczność handlowa (fill rate, avg return) | metryki |
| [backend/tuning_insights.py](backend/tuning_insights.py) | Optymalizacja parametrów strategii | tuning |
| [backend/reevaluation_worker.py](backend/reevaluation_worker.py) | Worker do ponownej oceny pozycji | — |
| [backend/runtime_settings.py](backend/runtime_settings.py) | Dynamiczne ustawienia z DB, konfiguracja tierów | `get_setting()`, `upsert_overrides()`, `build_symbol_tier_map()` |
| [backend/system_logger.py](backend/system_logger.py) | Ogólne logowanie systemu | `log_event()` |
| [backend/experiments.py](backend/experiments.py) | Eksperymenty A/B, flagi | — |
| [backend/governance.py](backend/governance.py) | Governance: zatwierdzanie zleceń, raporty | `check_pending_approvals()` |
| [backend/telegram_intelligence.py](backend/telegram_intelligence.py) | Interpretacja i archiwizacja wiadomości Telegram | `log_telegram_event()`, klasyfikacja wiadomości |

### Przepływy (flows)

| Plik | Rola |
|------|------|
| [backend/promotion_flow.py](backend/promotion_flow.py) | Promocja strategii do produkcji |
| [backend/rollback_flow.py](backend/rollback_flow.py) | Rollback strategii |
| [backend/review_flow.py](backend/review_flow.py) | Recenzja wyników |
| [backend/rollback_decision.py](backend/rollback_decision.py) | Logika decyzji rollback |
| [backend/post_promotion_monitoring.py](backend/post_promotion_monitoring.py) | Monitoring po promocji |
| [backend/post_rollback_monitoring.py](backend/post_rollback_monitoring.py) | Monitoring po rollback |
| [backend/candidate_validation.py](backend/candidate_validation.py) | Walidacja kandydatów strategii |
| [backend/policy_layer.py](backend/policy_layer.py) | Warstwa polityk: co wolno botowi robić |
| [backend/operator_console.py](backend/operator_console.py) | Konsola operatora |

### Autentykacja i powiadomienia

| Plik | Rola |
|------|------|
| [backend/auth.py](backend/auth.py) | JWT auth, logowanie, tokeny |
| [backend/notification_hooks.py](backend/notification_hooks.py) | Hooki powiadomień (Telegram, webhooki) |
| [backend/reporting.py](backend/reporting.py) | Raporty CSV/PDF |

### Routery API (`backend/routers/`) — 10 routerów

| Plik | Prefix | Kluczowe endpointy |
|------|--------|--------------------|
| [backend/routers/account.py](backend/routers/account.py) | `/api/account` | `/kpi`, `/summary`, `/system-status`, `/risk`, `/demo/reset-balance`, `/snapshots` |
| [backend/routers/market.py](backend/routers/market.py) | `/api/market` | `/scanner`, `/klines/{symbol}`, `/forecast/{symbol}`, `/summary`, `/ranges`, `/analyze/{symbol}` |
| [backend/routers/orders.py](backend/routers/orders.py) | `/api/orders` | `GET /`, `POST /`, `/{id}/confirm`, `/{id}/reject`, `/pending`, `/stats`, `/export.csv` |
| [backend/routers/positions.py](backend/routers/positions.py) | `/api/positions` | `GET /`, `/{id}/close`, `/analysis` |
| [backend/routers/signals.py](backend/routers/signals.py) | `/api/signals` | `/latest`, `/top5`, `/top10`, `/best-opportunity` |
| [backend/routers/portfolio.py](backend/routers/portfolio.py) | `/api/portfolio` | `GET /?mode=demo\|live` |
| [backend/routers/control.py](backend/routers/control.py) | `/api/control` | `/status`, `/start`, `/stop`, `/settings` |
| [backend/routers/blog.py](backend/routers/blog.py) | `/api/blog` | `/list`, `/post/{id}` |
| [backend/routers/debug.py](backend/routers/debug.py) | `/api/debug` | `/state-consistency` |
| [backend/routers/telegram_intel.py](backend/routers/telegram_intel.py) | `/api/telegram-intel` | `/state`, `/messages`, `/evaluate-goal`, `/log-event` |

---

## FRONTEND (`web_portal/`)

### Konfiguracja

| Plik | Rola |
|------|------|
| [web_portal/package.json](web_portal/package.json) | Zależności Next.js **16.1.6**, React 19.2.4 |
| [web_portal/next.config.js](web_portal/next.config.js) | Konfiguracja Next.js (rewrites, env) |
| [web_portal/tailwind.config.js](web_portal/tailwind.config.js) | Tailwind v4 config |
| [web_portal/tsconfig.json](web_portal/tsconfig.json) | TypeScript config |

### Aplikacja (`web_portal/src/`)

| Plik | Rola |
|------|------|
| [web_portal/src/app/layout.tsx](web_portal/src/app/layout.tsx) | Root layout Next.js |
| [web_portal/src/app/page.tsx](web_portal/src/app/page.tsx) | Strona główna — renderuje `<Dashboard>` |
| [web_portal/src/lib/api.ts](web_portal/src/lib/api.ts) | Klient API — wszystkie wywołania do backendu |
| [web_portal/src/styles/globals.css](web_portal/src/styles/globals.css) | Globalne style |

### Komponenty (`web_portal/src/components/`)

| Plik | Rola | Stan |
|------|------|------|
| [web_portal/src/components/Dashboard.tsx](web_portal/src/components/Dashboard.tsx) | Root komponent — Sidebar + Topbar + MainContent | ✅ |
| [web_portal/src/components/MainContent.tsx](web_portal/src/components/MainContent.tsx) | **5764L — WSZYSTKIE widoki**; router 18 widoków + SymbolDetailPanel + ForecastChart + BestOpportunityCard | ✅ Pełny |
| [web_portal/src/components/Sidebar.tsx](web_portal/src/components/Sidebar.tsx) | **18 pozycji** nawigacji, przełącznik DEMO/LIVE | ✅ |
| [web_portal/src/components/Topbar.tsx](web_portal/src/components/Topbar.tsx) | Górny pasek: tytuł, tryb, ustawienia | ✅ |

### Widoki Sidebar (18 pozycji — `MainContent.tsx`)

| ID widoku | Etykieta | Opis |
|-----------|----------|------|
| `dashboard` | Panel główny | KPI, equity curve, market overview, top sygnały |
| `position-analysis` | Decyzje | Karty decyzji per symbol z analizą AI |
| `execution-trace` | Diagnostyka | Trace cyklu kolektora, kroki decyzyjne |
| `telegram-intel` | Telegram AI | Wiadomości Telegram + inteligencja AI |
| `trade-desk` | Zlecenia | Tworzenie/zatwierdzanie/odrzucanie zleceń |
| `exit-diagnostics` | Diagnostyka wyjść | Analiza jakości wyjść (exit quality) |
| `portfolio` | Portfel | Balans portfela, pozycje demo/live |
| `strategies` | Strategie | Przegląd strategii handlowych |
| `ai-signals` | AI Sygnały | Najnowsze sygnały AI z scoringiem |
| `risk` | Ryzyko | Metryki ryzyka, drawdown, limity |
| `backtest` | Historia | Historia zamkniętych pozycji |
| `economics` | Ekonomia | Proxy ekonomiczne przez Market Proxy |
| `alerts` | Alerty | System alertów cenowych/eventowych |
| `news` | Wiadomości | Wiadomości rynkowe przez Market Proxy |
| `macro-reports` | Raporty | Raporty makroekonomiczne (CPI, GDP, Fed) |
| `reports` | Statystyki | Podsumowania, eksporty CSV |
| `logs` | Logi | Logi systemowe |
| `settings` | Ustawienia | Konfiguracja runtime settings |

### Widgety (`web_portal/src/components/widgets/`)

| Plik | Rola | Endpoint | Stan |
|------|------|----------|------|
| [AccountMetrics.tsx](web_portal/src/components/widgets/AccountMetrics.tsx) | Metryki konta (equity, cash, PnL) | `/api/account/kpi` | ✅ |
| [AccountSummary.tsx](web_portal/src/components/widgets/AccountSummary.tsx) | Podsumowanie konta | `/api/account/summary` | ✅ |
| [DecisionRisk.tsx](web_portal/src/components/widgets/DecisionRisk.tsx) | Karta decyzji + ryzyko | `/api/positions/analysis` | ✅ |
| [DecisionsRiskPanel.tsx](web_portal/src/components/widgets/DecisionsRiskPanel.tsx) | Panel zbiorczy decyzji + ryzyko | `/api/positions/analysis` | ✅ |
| [EquityCurve.tsx](web_portal/src/components/widgets/EquityCurve.tsx) | Wykres krzywej equity | `/api/account/snapshots` | ✅ |
| [MarketInsights.tsx](web_portal/src/components/widgets/MarketInsights.tsx) | Insights z AI/heurystyki | `/api/signals/latest` | ✅ |
| [MarketOverview.tsx](web_portal/src/components/widgets/MarketOverview.tsx) | Przegląd rynku | `/api/market/summary` | ✅ |
| [OpenOrders.tsx](web_portal/src/components/widgets/OpenOrders.tsx) | Otwarte zlecenia | `/api/orders/pending` | ✅ |
| [Orderbook.tsx](web_portal/src/components/widgets/Orderbook.tsx) | Tabela zleceń | `/api/orders` | ✅ |
| [PositionsTable.tsx](web_portal/src/components/widgets/PositionsTable.tsx) | Tabela pozycji z close 25/50/100% | `/api/positions` | ✅ |
| [TradingView.tsx](web_portal/src/components/widgets/TradingView.tsx) | Wykres świecowy Recharts | `/api/market/klines/{symbol}` | ✅ |

---

## TELEGRAM BOT (`telegram_bot/`)

| Plik | Rola | Stan |
|------|------|------|
| [telegram_bot/bot.py](telegram_bot/bot.py) | Bot Telegram — 18 komend, alerty, integracja z backendem | ✅ Działa |

---

## SKRYPTY (`scripts/`)

| Plik | Rola |
|------|------|
| `scripts/start_dev.sh` | Start backend + frontend |
| `scripts/stop_dev.sh` | Stop procesów |
| `scripts/status_dev.sh` | Status procesów |

---

## TESTY (`tests/`)

| Plik | Rola | Stan |
|------|------|------|
| [tests/test_smoke.py](tests/test_smoke.py) | Testy smoke — endpointy, logika, modele (4136L) | **181/181 ✅** |

---

## BAZA DANYCH

| Element | Opis |
|---------|------|
| `trading_bot.db` | Główna baza SQLite, tryb WAL (gitignore) |
| `trading_bot.db.bak.20260326_134234` | Backup z 2026-03-26 |

### Modele ORM (30 modeli w `database.py`)

| Model | Tabela |
|-------|--------|
| `MarketData` | `market_data` |
| `Kline` | `klines` |
| `Signal` | `signals` |
| `Order` | `orders` |
| `Position` | `positions` |
| `ExitQuality` | `exit_quality` |
| `AccountSnapshot` | `account_snapshots` |
| `Alert` | `alerts` |
| `SystemLog` | `system_logs` |
| `BlogPost` | `blog_posts` |
| `TelegramMessage` | `telegram_messages` |
| `PendingOrder` | `pending_orders` |
| `RuntimeSetting` | `runtime_settings` |
| `ConfigSnapshot` | `config_snapshots` |
| `Experiment` | `experiments` |
| `ExperimentResult` | `experiment_results` |
| `Recommendation` | `recommendations` |
| `RecommendationReview` | `recommendation_reviews` |
| `ConfigPromotion` | `config_promotions` |
| `PromotionMonitoring` | `promotion_monitoring` |
| `ConfigRollback` | `config_rollbacks` |
| `RollbackMonitoring` | `rollback_monitoring` |
| `PolicyAction` | `policy_actions` |
| `Incident` | `incidents` |
| `DecisionTrace` | `decision_traces` |
| `ForecastRecord` | `forecast_records` |
| `CostLedger` | `cost_ledger` |
| `UserExpectation` | `user_expectations` |
| `DecisionAudit` | `decision_audit` |
| `GoalAssessment` | `goal_assessments` |

---

## KONFIGURACJA ŚRODOWISKA

| Element | Gdzie | Opis |
|---------|-------|------|
| `.env` | root (gitignore) | `SECRET_KEY`, `BINANCE_*`, `OPENAI_API_KEY`, `TELEGRAM_*`, `LIVE_TRADING`, `WATCHLIST` |
| `AI_PROVIDER=auto` | `backend/analysis.py` hardcoded default | auto = heurystyka gdy brak OpenAI key |
| `DISABLE_COLLECTOR=true` | env var dla testów | Wyłącza kolektor w pytest |

### Tiery symboli (runtime_settings `symbol_tiers`)

| Tier | Symbole | Modyfikatory |
|------|---------|-------------|
| CORE | BTC/EUR, ETH/EUR, SOL/EUR, XRP/EUR, BTC/USDC, ETH/USDC, SOL/USDC, XRP/USDC | domyślne (conf+0, edge+0, risk×1.0) |
| ALTCOIN | SXT/USDC, SHIB/EUR, SHIB/USDC, ETC/USDC | conf +0.05, edge +0.5, risk ×0.5, max 3 trades/dzień |
| SPECULATIVE | WLFI/EUR, WLFI/USDC | conf +0.10, edge +1.0, risk ×0.3, max 2 trades/dzień |

---

## URUCHOMIENIE

```bash
# START (zalecane — jeden skrypt robi wszystko)
bash scripts/start_dev.sh

# STATUS
bash scripts/status_dev.sh

# STOP
bash scripts/stop_dev.sh

# Backend ręcznie
.venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000

# Frontend ręcznie
cd web_portal && npx next dev --hostname 0.0.0.0 --port 3000

# Testy
DISABLE_COLLECTOR=true .venv/bin/python -m pytest tests/ -v
```
