# HANDOFF_FOR_EXTERNAL_REVIEW

## Cel
Przekazanie projektu do niezależnego przeglądu technicznego i operacyjnego (LIVE Binance + WWW).

## Co sprawdzić w pierwszej kolejności
1. /api/account/trading-status (blockers, available_to_trade, status_color)
2. /api/account/runtime-activity (heartbeat: collector/ws/worker, last decision/order)
3. /api/account/capital-snapshot (source_of_truth, sync_status, equity/free_cash)
4. /api/positions?mode=live i /api/orders?mode=live
5. UI: Command Center -> TradingStatusPanel + RuntimeActivityPanel

## Komendy weryfikacyjne
```bash
# Backend tests
python3 -m pytest tests/test_smoke.py -q --tb=short

# Frontend TS
cd web_portal && node_modules/.bin/tsc --noEmit

# Szybkie sanity endpointów
curl "http://localhost:8000/api/account/trading-status?mode=live"
curl "http://localhost:8000/api/account/runtime-activity?mode=live"
curl "http://localhost:8000/api/account/capital-snapshot?mode=live"
```

## Wynik sesji przekazania
- TypeScript: OK (0 błędów)
- Smoke: 220 passed
- Demo guards w kluczowych akcjach UI: usunięte
- Pending/order flow: live-ready
- Runtime panel: wdrożony

## Zakres zmian do weryfikacji przez reviewera
- backend/routers/account.py
- backend/routers/control.py
- backend/routers/orders.py
- backend/routers/positions.py
- web_portal/src/components/MainContent.tsx
- web_portal/src/components/Topbar.tsx
- tests/test_smoke.py

## Kryterium akceptacji
- Brak rozjazdu między trading-status, runtime-activity i stanem UI.
- Akcje manualne w LIVE (pending/close) działają i zwracają poprawne statusy.
- Brak regresji w smoke tests.
