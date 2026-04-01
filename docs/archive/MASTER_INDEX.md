# MASTER_INDEX — RLdC AiNalyzator v0.7 beta
*Kompletny indeks plików projektu: rola, stan, powiązania.*
*Ostatnia aktualizacja: 2026-03-28 (sesje D-F + ETAP 0 + ETAP 1 synchronizacja)*

> Aktualny stan projektu: **[CURRENT_STATE.md](CURRENT_STATE.md)**

---

## DOKUMENTY PROJEKTU (root)

| Plik | Rola | Stan |
|------|------|------|
| [START_HERE.md](START_HERE.md) | **🟢 Zacznij stąd** — jak uruchomić, adresy, co po restarcie | Aktualny |
| [CURRENT_STATE.md](CURRENT_STATE.md) | **Stan projektu** — co działa, co nie, co dalej | Aktualny |
| [README.md](README.md) | Instrukcja uruchomienia, opis projektu | Aktualny |
| [FUNCTIONS_MATRIX.md](FUNCTIONS_MATRIX.md) | Macierz ~108 funkcji — status end-to-end | Aktualny |
| [OPEN_GAPS.md](OPEN_GAPS.md) | 16 braków posortowanych wg priorytetu | Aktualny |
| [SYSTEM_RULES.md](SYSTEM_RULES.md) | Zasady systemu, reguły decyzyjne, bezpieczeństwo | Aktualny |
| [CHANGELOG_LIVE.md](CHANGELOG_LIVE.md) | Dziennik zmian w projekcie | ✅ Aktualny (sesje A-F + ETAP 0) |
| [MASTER_INDEX.md](MASTER_INDEX.md) | Ten plik — indeks całego projektu | Aktualny |
| [PROGRAM_REVIEW.md](PROGRAM_REVIEW.md) | Głęboki audyt kodu backend — każda funkcja | Aktualny (Sesja E) |
| [MASTER_GAP_REPORT.md](MASTER_GAP_REPORT.md) | Raport statusu + plan 4 pilarów (starszy format) | Archiwum |
| [MASTER_PROMPT.md](MASTER_PROMPT.md) | Główny prompt dla Copilota | Archiwum |
| [PROJECT_AUDIT_MASTER.md](PROJECT_AUDIT_MASTER.md) | Masterplan audytu | Archiwum |
| [TASK_QUEUE.md](TASK_QUEUE.md) | Kolejka zadań (stary format — zastąpiony przez CURRENT_STATE.md) | Archiwum |
| [TRADING_GOAL.md](TRADING_GOAL.md) | Cel handlowy projektu | Aktualny |
| [CORE_TRADING_PRIORITY.md](CORE_TRADING_PRIORITY.md) | Priorytety rdzenia handlowego | Aktualny |
| [requirements.txt](requirements.txt) | Zależności Pythona | Aktualny |
| [instrukcje.txt](instrukcje.txt) | Instrukcje operacyjne | Aktualny |

---

## BACKEND (`backend/`)

### Rdzeń aplikacji

| Plik | Rola | Kluczowe klasy/funkcje |
|------|------|------------------------|
| [backend/app.py](backend/app.py) | FastAPI entry point, CORS, montowanie routerów, uruchomienie kolektora | `create_app()` |
| [backend/database.py](backend/database.py) | SQLite, modele SQLAlchemy, inicjalizacja DB | `get_db()`, `init_db()`, wszystkie modele ORM |
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
| [backend/runtime_settings.py](backend/runtime_settings.py) | Dynamiczne ustawienia z DB | `get_setting()`, `upsert_overrides()` |
| [backend/system_logger.py](backend/system_logger.py) | Ogólne logowanie systemu | `log_event()` |
| [backend/experiments.py](backend/experiments.py) | Eksperymenty A/B, flagi | — |
| [backend/governance.py](backend/governance.py) | Governance: zatwierdzanie zleceń, raporty | `check_pending_approvals()` |

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

### Autentykacja i auth

| Plik | Rola |
|------|------|
| [backend/auth.py](backend/auth.py) | JWT auth, logowanie, tokeny |
| [backend/notification_hooks.py](backend/notification_hooks.py) | Hooki powiadomień (Telegram, webhooki) |
| [backend/reporting.py](backend/reporting.py) | Raporty CSV/PDF |

### Routery API (`backend/routers/`)

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

---

## FRONTEND (`web_portal/`)

### Konfiguracja

| Plik | Rola |
|------|------|
| [web_portal/package.json](web_portal/package.json) | Zależności Next.js 14 |
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
| [web_portal/src/components/MainContent.tsx](web_portal/src/components/MainContent.tsx) | **2882L — WSZYSTKIE widoki**; router widoków + SymbolDetailPanel + ForecastChart + BestOpportunityCard + WlfiStatusCard | ✅ Pełny |
| [web_portal/src/components/Sidebar.tsx](web_portal/src/components/Sidebar.tsx) | 15 pozycji nawigacji, stan aktywnego widoku | ✅ |
| [web_portal/src/components/Topbar.tsx](web_portal/src/components/Topbar.tsx) | Górny pasek: tytuł, tryb, ustawienia | ✅ |

### Widgety (`web_portal/src/components/widgets/`)

| Plik | Rola | Endpoint | Stan |
|------|------|----------|------|
| [AccountMetrics.tsx](web_portal/src/components/widgets/AccountMetrics.tsx) | Metryki konta (equity, cash, PnL) | `/api/account/kpi` | ✅ |
| [AccountSummary.tsx](web_portal/src/components/widgets/AccountSummary.tsx) | Podsumowanie konta | `/api/account/summary` | ✅ |
| [DecisionRisk.tsx](web_portal/src/components/widgets/DecisionRisk.tsx) | Karta decyzji + ryzyko | `/api/positions/analysis` | ✅ |
| [DecisionsRiskPanel.tsx](web_portal/src/components/widgets/DecisionsRiskPanel.tsx) | Panel zbiorczy decyzji + ryzyko | `/api/positions/analysis` | 🟡 |
| [EquityCurve.tsx](web_portal/src/components/widgets/EquityCurve.tsx) | Wykres krzywej equity | `/api/account/snapshots` | ✅ |
| [MarketInsights.tsx](web_portal/src/components/widgets/MarketInsights.tsx) | Insights z AI/heurystyki | `/api/signals/latest` | ✅ |
| [MarketOverview.tsx](web_portal/src/components/widgets/MarketOverview.tsx) | Przegląd rynku | `/api/market/summary` | ✅ |
| [OpenOrders.tsx](web_portal/src/components/widgets/OpenOrders.tsx) | Otwarte zlecenia | `/api/orders/pending` | 🟡 brak refresh |
| [Orderbook.tsx](web_portal/src/components/widgets/Orderbook.tsx) | Tabela zleceń | `/api/orders` | ✅ |
| [PositionsTable.tsx](web_portal/src/components/widgets/PositionsTable.tsx) | Tabela pozycji z close 25/50/100% | `/api/positions` | ✅ |
| [TradingView.tsx](web_portal/src/components/widgets/TradingView.tsx) | Wykres świecowy Recharts | `/api/market/klines/{symbol}` | 🟡 brak forecast/RSI/EMA |

---

## MODUŁY SPECJALISTYCZNE (root)

| Katalog | Rola | Stan |
|---------|------|------|
| `ai_trading/` | AI trading core (puste / stub) | 🔴 Stub |
| `blockchain_analysis/` | Analiza blockchaina (stub) | 🔴 Stub |
| `hft_engine/` | Silnik HFT (pusty) | 🔴 Stub |
| `infrastructure/` | Infrastruktura (pusty) | 🔴 Stub |
| `portfolio_management/` | Zarządzanie portfelem (stub) | 🔴 Stub |
| `quantum_optimization/` | Optymalizacja kwantowa (stub) | 🔴 Stub |
| `recommendation_engine/` | Silnik rekomendacji (stub) | 🔴 Stub |
| `telegram_bot/` | Bot Telegram — komendy, alerty (18 komend, bezpieczeństwo naprawione Sesja E) | 🟡 Działa |
| `scripts/` | Skrypty startowe: `start_dev.sh`, `stop_dev.sh`, `status_dev.sh` | ✅ Nowy (ETAP 0) |

---

## TESTY (`tests/`)

| Plik | Rola | Stan |
|------|------|------|
| [tests/test_smoke.py](tests/test_smoke.py) | Testy smoke — wszystkie endpointy, logika | **175/175 ✅** |

---

## BAZA DANYCH

| Element | Opis |
|---------|------|
| `trading_bot.db` | Główna baza SQLite (gitignore) |
| `trading_bot.db.bak.20260326_134234` | Backup z 2026-03-26 |
| Modele ORM | `Order`, `Position`, `Signal`, `MarketData`, `AccountSnapshot`, `BlogPost`, `RuntimeSetting`, `SystemLog` |

---

## KONFIGURACJA ŚRODOWISKA

| Element | Gdzie | Opis |
|---------|-------|------|
| `.env` | root (gitignore) | `SECRET_KEY`, `BINANCE_*`, `OPENAI_API_KEY`, `TELEGRAM_*`, `LIVE_TRADING` |
| `AI_PROVIDER=auto` | `backend/analysis.py` hardcoded default | auto = heurystyka gdy brak OpenAI key |
| `DISABLE_COLLECTOR=true` | env var dla testów | Wyłącza kolektor w pytest |

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
