# ENDPOINTS_AUDIT

## Stan
- Audyt wykonany na backend/routers/*.py.
- Brak brakujących routerów zarejestrowanych w kodzie.
- Kluczowe endpointy LIVE odpowiadają i są używane przez frontend.

## Krytyczne endpointy LIVE (source of truth)
- GET /api/account/capital-snapshot
- GET /api/account/trading-status
- GET /api/account/runtime-activity
- GET /api/account/system-status
- GET /api/portfolio/wealth
- GET /api/positions
- POST /api/orders
- GET /api/orders
- GET /api/orders/pending
- POST /api/orders/pending
- POST /api/orders/pending/{id}/confirm
- POST /api/orders/pending/{id}/reject
- POST /api/orders/pending/{id}/cancel
- POST /api/positions/{id}/close
- POST /api/positions/close-all

## Zmiany wykonane w sesji (live-only)
- Dodano: GET /api/account/runtime-activity
- Ujednolicono control state:
  - dodano live_trading_enabled alias
  - dodano trading_enabled alias
- Pending orders:
  - usunięto blokadę tylko DEMO dla create/confirm/reject/cancel
  - GET /api/orders/pending domyślnie mode=live
- Orders:
  - GET /api/orders domyślnie mode=live
  - GET /api/orders/export.csv domyślnie mode=live
- Positions:
  - POST /api/positions/close-all obsługuje mode=live i mode=demo

## Inwentarz routerów (skrót)
- account.py: 90+ endpointów (analytics, runtime, health pipeline)
- control.py: state, hold-status, operator-queue
- orders.py: orders, pending, stats, export
- positions.py: close, close-all, analysis, goals, sync
- portfolio.py: wealth, summary, forecast, live-sync
- signals.py: latest/top/best/wait/trace/readiness/expectations
- market.py: scanner, ticker, klines, ranges, allowed-symbols
- debug.py: consistency, exits, logs
- telegram_intel.py: state, messages, evaluate-goal

## Uwagi ryzyka
- Endpointy reset DEMO nadal istnieją (celowo, serwisowo), ale nie są elementem standardowego flow LIVE.
- Część endpointów analytics/historycznych ma tryb demo/live i nie jest krytyczna dla wykonania zleceń.
