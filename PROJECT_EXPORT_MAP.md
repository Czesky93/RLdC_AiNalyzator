# PROJECT_EXPORT_MAP

## Zakres exportu do review zewnętrznego

### Backend (FastAPI)
- backend/app.py
- backend/collector.py
- backend/accounting.py
- backend/risk.py
- backend/runtime_settings.py
- backend/database.py
- backend/binance_client.py
- backend/routers/account.py
- backend/routers/control.py
- backend/routers/orders.py
- backend/routers/positions.py
- backend/routers/portfolio.py
- backend/routers/signals.py
- backend/routers/market.py

### Frontend (Next.js)
- web_portal/src/components/Dashboard.tsx
- web_portal/src/components/MainContent.tsx
- web_portal/src/components/Sidebar.tsx
- web_portal/src/components/Topbar.tsx
- web_portal/src/lib/api.ts

### Telegram
- telegram_bot/bot.py

### Testy i uruchamianie
- tests/test_smoke.py
- scripts/start_dev.sh
- scripts/stop_dev.sh
- scripts/status_dev.sh

### Dokumenty przekazania
- ENDPOINTS_AUDIT.md
- FRONTEND_VIEW_MAP.md
- LIVE_TRADING_FLOW.md
- CONFIG_AUDIT.md
- KNOWN_ISSUES_AND_GAPS.md
- HANDOFF_FOR_EXTERNAL_REVIEW.md

## Kluczowe artefakty operacyjne
- DB: trading_bot.db (SQLite)
- Logi dev: logs/dev/
- Runtime config: RuntimeSetting (DB) + ENV

## Potwierdzenie jakości (ta sesja)
- TypeScript: node_modules/.bin/tsc --noEmit -> OK
- Smoke: python3 -m pytest tests/test_smoke.py -q --tb=short -> 220 passed
