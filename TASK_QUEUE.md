# TASK_QUEUE — RLdC Trading Bot

## ZADANIA OTWARTE

### CRITICAL

*Brak otwartych zadań krytycznych.*

### HIGH

*Brak otwartych zadań wysokiego priorytetu.*

### MEDIUM

*Brak otwartych zadań średniego priorytetu.*

### LOW

*Brak otwartych zadań niskiego priorytetu.*

### DONE (zamknięte w sesji 12)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-19 | `entry-readiness open_positions=0` mimo BTCEUR w DB → zmieniono licznik na `len(open_positions)` | `signals.py` | DONE |
| T-20 | SELL entry ENTRY_ALLOWED bez otwartej pozycji → `ENTRY_BLOCKED_SELL_NO_POSITION` | `signals.py` | DONE |
| T-21 | AVAX/EGLD/PEPE/ARB jako `ENTRY_ALLOWED` mimo `symbol_not_in_any_tier` w collectorze → tier-gate + fix źródła `symbol_tiers` (`runtime_ctx` zamiast pustego `config`) | `signals.py` | DONE |
| T-22 | `start_dev.sh` zawsze startował `next dev` mimo istnienia buildu prod → auto-wykrycie `.next/BUILD_ID` | `scripts/start_dev.sh` | DONE |

### DONE (zamknięte w sesji 11)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-18 | Spam logów heurystyki ATR co 60s → throttle 600s + detekcja zmian zestawu symboli | `collector.py` | DONE (sesja 11) |

### DONE (zamknięte w sesji 10)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-16 | `_load_watchlist` ignorowała ENV WATCHLIST gdy Binance balances non-empty → ETH/SOL/SHIB/WLFI poza watchlistą | `collector.py` | DONE (sesja 10) |
| T-17 | `range_map` nie uzupełniał brakujących symboli po zmianie watchlisty → ciche pomijanie ETH/SOL/SHIB/WLFI | `collector.py` | DONE (sesja 10) |

### DONE (zamknięte w sesji 9)

| ID | Zadanie | Plik/Moduł | Status |
|----|---------|------------|--------|
| T-15 | Bot nie otworzył żadnej pozycji LIVE — fix dust-positions blokujących wejścia | `signals.py`, `positions.py`, `collector.py` | DONE (sesja 9) |
| T-05 | CORS allow_origins=["*"] → domeny produkcyjne | `app.py` | DONE (sesja 9) |
| T-07 | Usunięcie nieużywanego widgetu AccountSummary | `widgets/AccountSummary.tsx` | DONE (sesja 9) |

### DONE (zamknięte w sesjach 1-8)

| ID | Zadanie | Zamknięte |
|----|---------|----------|
| T-01 | LIVE CostLedger actual Binance fees | sesja 1 |
| T-02 | Periodyczny sync DB↔Binance | sesja 1 |
| T-03 | Telegram /confirm /reject | (już było) |
| T-04 | Qty sizing: prowizja w alokacji | sesja 2 |
| T-06 | Telegram governance stubs | (już było) |
| T-08 | Telegram /ip komenda (Cloudflare) | sesja 3 |
| T-09 | Telegram /ai komenda (OpenAI status) | sesja 3 |
| T-11 | Aliasy kompatybilności endpointów (404 → 200) + reset środowiska | sesja 4 |
| T-12 | Stabilizacja collectora: brak flappingu watchlisty + cooldown mismatch | sesja 5 |
| T-13 | LIVE baseline pozycji: entry_price/PnL z DB lub Binance myTrades | sesja 6 |
| T-10 | Naprawa 19 faili smoke (governance/promotion/rollback) | sesja 7 |
| T-14 | Fix critical collector bugs: fake LIVE SELL orders, entry_readiness open_count, _error check | sesja 8 |
---

## HISTORIA CHECKPOINTÓW

### CHECKPOINT (sesja 8 — poprawki collector + entry readiness)

**4 krytyczne bugi naprawione w collector.py i signals.py:**
- **Bug C** (`_execute_confirmed_pending_orders`): sprawdzenie `result.get("_error")` — Binance NOTIONAL reject był fałszywie traktowany jako sukces (truthy dict omijał `if not result:`)
- **Bug B** (`_load_trading_config` live mode): exit engine zarządza TYLKO pozycjami z bot-otwartymi BUY orders — pre-existing Binance holdings pominięte
- **Bug D** (`entry_readiness` open_count): live mode liczy tylko bot-otwarte (0 BUY = 0 open_count vs max 3) — wcześniej 5 synced > 3 max = blokada wszystkich wejść
- **Bug D2** (`entry_readiness` cash): live mode używa `_build_live_spot_portfolio` (171.30 EUR realne) — wcześniej zawsze 10000 EUR z demo state
- **DB cleanup**: 27 fake live SELL pending_orders + 27 fake live SELL orders usunięte; SL/TP z 5 synced positions live wyczyszczone

**Weryfikacja:**
- `entry-readiness?mode=live`: can_enter=True, open=0/3, cash=171.3 EUR ✅
- `positions/analysis?mode=live`: 5 pozycji, total_pnl=0.35 EUR ✅
- Pętla SL ARBEUR zatrzymana: 0 fake SELLs w ostatnich 5 min ✅


### CHECKPOINT (1 kwietnia 2026, iteracja 4)

Bot aktywnie handluje w demo! 2 otwarte pozycje: BTCEUR + ETHEUR.
Tryb **AGGRESSIVE** — obniżone progi wejścia, max 5 pozycji.

**Iter4 — DEMO straty fix (diagnoza + 5 napraw):**
- **Diagnoza:** Bot tracił z powodu za ciasnych TP/SL (0.57-0.69% SL), za krótkiego cooldownu (120s), braku RSI filtra soft-buy, braku eskalacji po SL.
- **ATR multipliers:** stop 1.3→2.0, take 2.2→3.5, trail 1.0→1.5 (oba miejsca w collector.py)
- **SL cooldown eskalacja:** Po SL → loss_streak++, cooldown rośnie do 7200s, win_streak=0
- **TP win tracking:** Po TP → loss_streak=0, win_streak++, cooldown reset
- **Soft buy RSI filter:** Wejścia miękkie wymagają RSI < 55 (anty-overextension)
- **Profil aggressive:** confidence 0.45→0.50, score 4.0→4.5, cooldown 120→300s

**Iter3:** WAL mode + async→def threadpool fix + enabled_strategies kill-switch.
181/181 testów. 0 błędów TypeScript. 0 problemów krytycznych.

---

## ZASADA GŁÓWNA

> WLFI to osobna pozycja HOLD. Demo i rozwój tradingu na ETH/SOL/BTC/BNB działają cały czas niezależnie.

---

## 3 RÓWNOLEGŁE TORY

### TOR A — WLFI (HOLD)

- **Trzymamy.** Nie sprzedajemy wcześniej.
- **Jedyny warunek:** całość WLFI warta minimum **300 EUR.**
- Bot nie robi: SL/TP, alarmy drawdown, nowe wejścia.
- Bot robi: sprawdza wartość co cykl → alert gdy >= 300 EUR → `/confirm`.
- Stan: ~3 260 szt × ~0.09 EUR ≈ 292 EUR. Cel blisko.

### TOR B — DEMO (AKTYWNY)

- **500 EUR wirtualnych** — BTCEUR (58878 EUR) + ETHEUR (1820 EUR) otwarte.
- Bot: zbiera dane, wchodzi w pozycje auto-potwierdzone, zarządza TP/SL.
- Diagnostyka dostępna: `/api/signals/execution-trace` + widok UI "Diagnostyka".

### TOR C — REAL TRADING (czeka na kapitał)

- Przygotowany logicznie (te same zasady co demo).
- Ruszy kiedy pojawi się EUR: po sprzedaży WLFI lub po wpłacie.
- Zasady: max 1 pozycja, max 2 trade'y/dzień, /confirm na każdym.

---

## CO BOT ROBI W KODZIE — STAN PO NAPRAWACH

| Funkcja | Status |
|---------|--------|
| Demo trading enabled (DB) | ✅ |
| Auto-confirm pending orders w demo | ✅ NAPRAWIONE |
| Position sizing z max_cash_pct_per_trade | ✅ NAPRAWIONE |
| is_extreme gate — tylko bonus, nie blokada | ✅ NAPRAWIONE |
| Router nie zatruwa sygnałów w DB | ✅ NAPRAWIONE |
| Symbol tiers: CORE (BTC/ETH/SOL/BNB) + ALTCOIN | ✅ |
| HOLD tier (WLFI): blokuje nowe wejścia | ✅ |
| RSI gate permisywny (65 kupno / 35 sprzedaż) | ✅ NAPRAWIONE (31.03) |
| Tolerancja cenowa 3% do zakresu AI | ✅ |
| Heuristic ranges (List→Dict fix) | ✅ NAPRAWIONE (31.03) |
| Leakage gate min 5 trade'ów | ✅ NAPRAWIONE (31.03) |
| Expectancy gate min 5 trade'ów | ✅ NAPRAWIONE (31.03) |
| Retencja DB batch + VACUUM | ✅ NAPRAWIONE (31.03) |
| trading_aggressiveness (safe/balanced/aggressive) | ✅ NOWE (01.04) |
| max_open_positions = 5 (aggressive) | ✅ NOWE (01.04) |
| KANDYDAT_DO_WEJŚCIA / WEJŚCIE_AKTYWNE UI labels | ✅ NOWE (01.04) |
| Dynamiczne progi best-opportunity z profilu | ✅ NOWE (01.04) |
| Telegram idle alert co 30 min | ✅ NOWE (01.04) |
| RuntimeSetting description crash fix | ✅ NAPRAWIONE (01.04) |
| enabled_strategies kill-switch w collectorze | ✅ NOWE (01.04) |
| strategy_name=default w DecisionTrace | ✅ NOWE (01.04) |
| Konsolidacja 13 plików MD → docs/archive/ | ✅ NOWE (01.04) |
| titleOverride "Market" → "Wykres rynku" | ✅ NOWE (01.04) |
| ATR stop 1.3→2.0, take 2.2→3.5, trail 1.0→1.5 | ✅ NAPRAWIONE (01.04 iter4) |
| SL cooldown eskalacja (loss_streak→7200s) | ✅ NOWE (01.04 iter4) |
| TP win tracking (loss_streak=0, win_streak++) | ✅ NOWE (01.04 iter4) |
| Soft buy RSI<55 filter (anty-overextension) | ✅ NOWE (01.04 iter4) |
| Profil aggressive: conf 0.50, score 4.5, cd 300s | ✅ NAPRAWIONE (01.04 iter4) |
| execution-trace endpoint | ✅ NOWE |
| UI panel Diagnostyka | ✅ NOWE |

---

## OTWARTE ZADANIA

| ID | Zadanie | Priorytet |
|----|---------|-----------|
| B | Unifikacja logiki kolektor↔UI (final-decisions) | ŚREDNI |
| - | ETAP F: pełny test kontrolowany (czekamy na 1 cykl TP/SL) | INFO |

---

## CZEGO NIE ROBIMY

- Nie dodajemy nowych modułów
- Nie ruszamy governance/policy/worker/console
- Nie mieszamy WLFI z demo/tradingiem
- Nie panikujemy przy spadkach WLFI

---

## CHECKPOINT (sesja 2 — pełna spójność frontendu API)

### Co zrobiono
- Przepisano hook `useFetch` w `MainContent.tsx`: URL budowany lazily w `useEffect`, prawdziwe komunikaty błędów (HTTP 404, brak połączenia, itp.)
- Podmieniono wszystkie 31 wywołań `useFetch` z `${API_BASE}/api/...` → `/api/...` (ścieżka relatywna)
- Naprawiono bezpośrednie wywołania `fetch('/api/...')` i `new URL('/api/...')` w handlerach akcji → `${getApiBase()}/api/...`
- `API_BASE` całkowicie wyeliminowane z frontendu: `EquityCurve.tsx`, `OpenOrders.tsx`, `Topbar.tsx`, `DecisionsRiskPanel.tsx`, `MainContent.tsx`
- Dodano brakujący komponent `RiskView` (sidebar miał link do widoku `risk`, ale handler nie istniał)
- `DecisionsView`: EUR zamiast `$`, kolorowanie PnL (zielony/czerwony)
- TypeScript: **brak błędów**, testy: **174/174 PASSED**

### Wynik
Portal w pełni spójny. Wszystkie widoki pobierają dane przez `getApiBase()`. Telefon/LAN działa.

### Przetestuj na telefonie
Otwórz `http://192.168.0.109:3000` i sprawdź: **Ryzyko, Rynki, Portfel, Strategie, AI Sygnały, Backtest**

---

## OSTATNI CHECKPOINT (26 marca 2026 — weryfikacja portalu)

### Co zrobiono
- Przediagnozowano wszystkie endpointy API używane przez frontend (20 URL-i).
- Wszystkie endpointy zwracają 200 i realne dane z bazy.
- Naprawiono `PositionsTable.tsx`:
  - `data.positions` → `data.data` (poprawne pole z API)
  - `API_BASE` → `getApiBase()` (bezpieczne dla LAN/telefonu)
  - `pnl` → `unrealized_pnl` (poprawna nazwa pola)
  - Usunięto twardo wpisane mocki w USD — teraz pokazuje realne pozycje DEMO
  - EUR zamiast $, `fmtPrice()` z dynamic precision dla małych kwot
- Naprawiono `positions.py` (`_analyze_position` + summary):
  - `round(value, 2)` → dynamiczna precyzja (6 dla  < 1 EUR, 4 dla < 100 EUR, 2 dla reszty)
  - Wyniki analizy WLFI (0.01 szt × 0.085 EUR) teraz pokazują 0.000849 EUR zamiast 0.0
- Testy: **174/174 PASSED**, TypeScript: brak błędów.

### Aktualny stan widoków portalu
| Widok | Status |
|-------|--------|
| Panel (Dashboard) | ✅ dane live, pozycje poprawne |
| Decyzje (position-analysis) | ✅ karta decyzyjna WLFI z powodami |
| Handel (trade-desk) | ✅ zlecenia + pozycje |
| Portfel | ✅ |
| AI Sygnały | ✅ |
| Rynki | ✅ |

### Następny krok (do wyboru)
1. Dopracować widok `PositionAnalysisView` — WLFI ma 0.01 szt; podsumowanie portfela powinno uwzględniać REAL (3260 szt WLFI).
2. Dodać nową demo-pozycję BTCEUR z aktualną ceną zakupu i sprawdzić, czy analiza sugeruje decyzję poprawnie.
3. Poprawić DashboardV2View — tabela "Positions" ma angielskie nagłówki (`Symbol`, `Side`, `Qty`).


