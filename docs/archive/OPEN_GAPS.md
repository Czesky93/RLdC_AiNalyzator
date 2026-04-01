# OPEN_GAPS — RLdC AiNalyzator v0.7 beta
*Lista wszystkich brakujących funkcji, posortowana wg priorytetu.*
*Zasada: priorytety nadane wg realnego wpływu na użyteczność i możliwość handlowania.*
*Ostatnia aktualizacja: 2026-03-28 (po sesjach A-F + ETAP 0)*

> Pełny aktualny stan projektu: patrz [CURRENT_STATE.md](CURRENT_STATE.md)

---

## GAP-01 — Symbol Detail Panel (Kliknięcie w symbol)

**Priorytet**: 🔴 KRYTYCZNY  
**Status**: ✅ DONE (sesja B)  

---

## GAP-02 — Forecast Overlay na Wykresie

**Priorytet**: 🔴 KRYTYCZNY  
**Status**: ✅ DONE (sesja B) + EMA/RSI (sesja C)  

---

## GAP-03 — Forecast Accuracy Tracking

**Priorytet**: 🔴 WYSOKI  
**Status**: ✅ DONE (sesja C)  

---

## GAP-04 — Akcje Handlowe w UI (KUP / SPRZEDAJ / ZAMKNIJ)

**Priorytet**: 🔴 WYSOKI  
**Status**: ✅ DONE (sesja B)  

---

## GAP-05 — Cel Użytkownika (persistacja backendu)

**Priorytet**: 🟡 WYSOKI  
**Status**: ✅ DONE (sesja C)  

---

## GAP-06 — Widoki Martwe w Sidebar (Alerty, Wiadomości, Ekonomia, Raporty, Statystyki)

**Priorytet**: ✅ DONE  
**Status**: ✅ DONE (ETAP 2) — Economics/Alerty/Wiadomości wyświetlają EmptyState "Moduł w przygotowaniu" zamiast fałszywych danych proxy. macro-reports i reports: tak samo.

---

## GAP-07 — Synchronizacja Danych (auto-refresh)

**Priorytet**: 🟡 WYSOKI  
**Status**: ✅ DONE (sesja B) — większość widoków ma refresh. Pozostałe problemy:
- Historia zleceń (Backtest View) — brak auto-refresh
- SymbolDetailPanel — pobiera dane raz przy otwarciu (ceny zamrożone)

**Pozostały zakres**:
- Backtest View: dodać `setInterval` lub `refreshMs` do fetchów
- SymbolDetailPanel: dodać `refreshMs=15000` do wewnętrznych useFetch

---

## GAP-08 — Drawdown Real Binance

**Priorytet**: 🟡 ŚREDNI  
**Status**: ✅ DONE (sesja C)  

---

## GAP-09 — Indykatory Techniczne na Wykresie

**Priorytet**: ✅ DONE  
**Status**: ✅ DONE (ETAP 2) — EMA20/EMA50 + mini RSI(14) dodane bezpośrednio do widgetu TradingView.tsx (ComposedChart). Dostępne na wszystkich dashboardach DashboardV2, ClassicDashboard i WLFI. Legenda + ciągły wskaźnik RSI z oznaczeniem kupno/wykupienie.

---

## GAP-10 — Historia Decyzji na Symbol

**Priorytet**: 🟡 ŚREDNI  
**Status**: ✅ DONE (sesja C) — endpoint `/api/positions/decisions/{symbol}` + UI w SymbolDetailPanel  

---

## GAP-11 — Whale Data / Duże transakcje

**Priorytet**: 💡 NISKI  
**Status**: ❌ NOT_STARTED  
**Problem**: Planowany element analizy, nie istnieje ani w backendzie ani frontend.  
**Uwaga**: NIE wdrażać do czasu ukończenia priorytetów 1-5.

---

## GAP-12 — Synchronizacja Bot/User (Co grasz?)

**Priorytet**: 💡 NISKI  
**Status**: ❌ NOT_STARTED  
**Problem**: Bot może handlować spekulacyjnym i long-termowym trybem jednocześnie bez rozróżnienia w UI. Użytkownik nie wie "czy to moje zlecenie czy bota".  
**Wymagany zakres**: Oznaczenie źródła zlecenia: "BOT_AUTO" vs "USER_MANUAL" vs "AI_REKOMENDACJA"

---

## GAP-13 — Best Trade Engine (najlepsza okazja)

**Priorytet**: ✅ DONE  
**Status**: ✅ DONE (sesja F)  
**Zrealizowane**: Endpoint `GET /api/signals/best-opportunity` + widget `BestOpportunityCard` w dashboardzie.  
Scoring: confidence×10, trend±1.5, RSI±1.5, R/R+1.0, HOLD-3.0. Zwraca: BUY/SELL/CZEKAJ z uzasadnieniem i `runner_up`.

---

## GAP-14 — Stabilne uruchamianie projektu

**Priorytet**: ✅ DONE  
**Status**: ✅ DONE (ETAP 0)  
**Zrealizowane**: `scripts/start_dev.sh`, `scripts/stop_dev.sh`, `scripts/status_dev.sh`, `START_HERE.md`.  
Skrypty wykrywają czy procesy już działają, zapisują PIDy, weryfikują HTTP 200 po starcie.

---

## GAP-15 — SymbolDetailPanel: zamrożone dane

**Priorytet**: ✅ DONE  
**Status**: ✅ DONE (ETAP 2) — `refreshMs` dodany do wszystkich 4 useFetch wewnątrz `SymbolDetailPanel`: analysis/signals co 30s, accuracy/decisions co 60s.

---

## GAP-16 — TradingView: brak timeframe switch

**Priorytet**: ✅ DONE  
**Status**: ✅ DONE (sesja B/TradingView.tsx) — Widget TradingView.tsx zawiera już state `timeframe` i przyciski `1m | 5m | 15m | 1h | 4h | 1d`. Parametr `&tf=${timeframe}` przekazywany do `/api/market/kline`. Weryfikacja ETAP 2 potwierdziła działanie.

---

## GAP-19 — Pełny widok portfela Binance z prognozą

**Priorytet**: ✅ DONE  
**Status**: ✅ DONE (ETAP 5)  
**Zrealizowane**: Backend `GET /api/portfolio/wealth` + `GET /api/portfolio/forecast`; frontend `PortfolioView` z KPI, wykresem equity, prognozą 1h/2h/7d, tabelą składu. `SymbolDetailPanel` rozszerzony o ilość/wartość/zmiana%.  

---

## PLAN WDROŻENIA (zaktualizowany 2026-03-28 — ETAP 5)

| Gap | Priorytet | Status | Estymacja |
|-----|-----------|--------|-----------|
| GAP-15: SymbolDetailPanel auto-refresh | ✅ DONE | ✅ ETAP 2 | — |
| GAP-16: Timeframe switch | ✅ DONE | ✅ (TradingView widget) | — |
| GAP-06: Martwe widoki EmptyState | ✅ DONE | ✅ ETAP 2 | — |
| GAP-09: RSI/EMA overlay TradingView | ✅ DONE | ✅ ETAP 2 | — |
| GAP-17: Globalny przełącznik DEMO/LIVE | ✅ DONE | ✅ ETAP 3 | — |
| GAP-18: Backend LIVE graceful fallback | ✅ DONE | ✅ ETAP 4 | — |
| GAP-19: Pełny widok portfela + prognoza | ✅ DONE | ✅ ETAP 5 | — |
| GAP-07: Backtest auto-refresh | 🟡 P2 | 🟡 PARTIAL | Mały |
| GAP-11: Whale data | 💡 P6 | ❌ | Bardzo duży |
| GAP-12: Oznaczenia bot/user | 💡 P6 | ❌ | Mały |

---

## GAP-17 — Globalny przełącznik DEMO/LIVE

**Priorytet**: ✅ DONE  
**Status**: ✅ DONE (ETAP 3) — Jedno źródło prawdy w `Dashboard.tsx` (`useState<'live' | 'demo'>('demo')`). Topbar i Sidebar mają interaktywne przyciski DEMO (zielony) / LIVE TRADE (pomarańczowy). Wszystkie widżety i fetche używają dynamicznego `mode` — brak hardcoded `mode=demo` w URL-ach.  
**Pliki zmienione**: `Topbar.tsx`, `Sidebar.tsx`, `Dashboard.tsx`, `MainContent.tsx`, `OpenOrders.tsx`, `DecisionRisk.tsx`, `PositionsTable.tsx`, `DecisionsRiskPanel.tsx`.
