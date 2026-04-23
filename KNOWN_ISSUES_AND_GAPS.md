# KNOWN_ISSUES_AND_GAPS

## CRITICAL
- Brak otwartych krytycznych blockerów po tej sesji (wg smoke + TS + endpoint checks).

## HIGH
- Brak.

## MEDIUM
- README zawiera historyczne sekcje DEMO i wymaga dalszego porządkowania narracji pod full-LIVE.
- Część typów frontendu nadal ma union mode 'demo'|'live' (kompatybilność), mimo że shell działa live-only.

## LOW
- W kodzie pozostają endpointy serwisowe DEMO (reset demo, demo account state) jako funkcje maintenance.
- close-all w LIVE wykonuje Binance sell i zwraca wynik; dalsza synchronizacja pozycji zależy od cyklu synchronizacji danych.

## Uwagi jakościowe
- Smoke tests: 220/220 pass.
- TypeScript: 0 błędów.
- Runtime diagnostics: dostępne przez /api/account/runtime-activity i panel w Command Center.
