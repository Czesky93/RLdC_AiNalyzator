# PROGRAM REVIEW — Pełny audyt v0.7 beta

**Data audytu:** 2026-03-26 | **Ostatnia aktualizacja:** 2026-04-01 (iter10 — diagnoza strat; fix min_notional; demo włączone)  
**Wersja:** v0.7-beta  
**Testy:** 181/181 ✅ (175 smoke + 6 akceptacyjnych) | TypeScript: 0 błędów ✅ | Endpointy: 34/34 ✅  
**Autor przeglądu:** GitHub Copilot (Claude Sonnet 4.6)

---

## WYNIKI AUDYTU 2026-03-31

### METRYKI CODEBASE

| Metryka | Wartość |
|---------|---------|
| Pliki Python (.py) | 44 |
| Łączna liczba linii Python | ~28 900 |
| Pliki TypeScript (.tsx/.ts) | 15 (src/) |
| Łączna liczba linii TS | ~5 800 |
| Testy | 181/181 ✅ |
| TypeScript errors | 0 ✅ |
| Deprecation warnings w backendzie | 0 ✅ |
| Deprecation warnings w testach | 14 ⚠️ |
| Tabele DB | 30 |
| Rozmiar DB | 275 MB ⚠️ |

### NAJWIĘKSZE PLIKI

| Plik | Linie | Rola |
|------|-------|------|
| `tests/test_smoke.py` | 4 138 | Testy end-to-end + 6 akceptacyjnych |
| `backend/collector.py` | 3 127 | Rdzeń silnika tradingowego |
| `backend/routers/account.py` | 2 058 | Governance + analytics |
| `backend/routers/signals.py` | 1 808 | Sygnały + entry-readiness |
| `backend/routers/positions.py` | 1 910 | Pozycje + goals + sync |
| `web_portal/src/components/MainContent.tsx` | 5 764 | Cały front-end (18 widoków) |

---

## STATUSY PROBLEMÓW Z POPRZEDNICH AUDYTÓW

### ✅ NAPRAWIONE (potwierdzone audytem 2026-03-31)

| Problem | Poprzedni status | Aktualny stan |
|---------|-----------------|---------------|
| `_candidates` — podwójna definicja w market.py | 🔴 PROBLEM | ✅ Przemianowane na `_asset_to_candidates`, jedna definicja |
| `require_admin` — nieużywane | 🔴 PROBLEM | ✅ Używane na ~15 endpointach account.py |
| `import random` w portfolio.py | ⚠️ WAŻNE | ✅ Usunięte |
| `config_snapshot_payload_report` — zwracało `{}` | 🔴 PROBLEM | ✅ Wywołuje `get_config_snapshot(db, snapshot_id)` |
| `binance_client.py` — brak `place_order` | 🔴 KRYTYCZNE | ✅ `place_order()` zaimplementowane (L365) z error handling |
| `orders.py:create_order` — LIVE nie wywoływał Binance | 🔴 KRYTYCZNE | ✅ Wywołuje `binance.place_order()` w trybie LIVE |
| Stub dirs `hft_engine/`, `blockchain_analysis/` itd. | 🔴 PROBLEM | ✅ Wszystkie usunięte |
| `datetime.utcnow()` w backendzie (203 wystąpień) | ⚠️ DEPRECATED | ✅ 0 wystąpień w kodzie produkcyjnym |
| Bot nie otwierał pozycji DEMO — 5 blokerów | 🔴 KRYTYCZNE | ✅ Wszystkie 5 naprawione |
| `demo_min_signal_confidence=0.75` za wysoki | 🔴 BLOKER | ✅ Zmieniony na `0.55` |
| `pending_order_cooldown_seconds=3600` | 🔴 BLOKER | ✅ Zmieniony na `300` (5 min) |
| `cooldown_after_loss_streak_minutes=60` | 🔴 BLOKER | ✅ Zmieniony na `15` |
| Brak fallback ATR gdy brak zakresów AI | 🔴 BLOKER | ✅ `_load_trading_config` — heurystyczny fallback |
| Pending orders wymagały /confirm | 🔴 BLOKER | ✅ `demo_require_manual_confirm=False` — auto-execute |
| `_heuristic_ranges()` → `.items()` crash | 🔴 KRYTYCZNE | ✅ Zwraca `List[Dict]`, iteracja po liście (31.03) |
| `leakage_gate_symbol` blokuje z <5 trade'ami | 🔴 BLOKER | ✅ Min 5 zamkniętych transakcji (31.03) |
| `expectancy_gate_symbol` blokuje z <5 trade'ami | 🔴 BLOKER | ✅ Min 5 zamkniętych transakcji (31.03) |
| RSI buy gate 60.0 za ciasny | 🔴 BLOKER | ✅ Zmieniony na 65.0 kupno / 35.0 sprzedaż (31.03) |
| `_purge_stale_data` — jedno masowe DELETE | ⚠️ WAŻNE | ✅ Batch delete 5000 wierszy + VACUUM (31.03) |
| `ROZWAŻ_ZAKUP` — niejasna etykieta w UI | ⚠️ WAŻNE | ✅ Zamienione na `KANDYDAT_DO_WEJŚCIA` / `WEJŚCIE_AKTYWNE` (01.04) |
| Hardcoded MIN_SCORE=6.0 w best-opportunity | ⚠️ WAŻNE | ✅ Dynamiczne progi z profilu agresywności (01.04) |
| Brak trybu agresywności | ⚠️ WAŻNE | ✅ `trading_aggressiveness` setting: safe/balanced/aggressive (01.04) |
| `max_open_positions=3` za mało | ⚠️ WAŻNE | ✅ Domyślnie 5, profilowy override (01.04) |
| Brak Telegram idle alert | ⚠️ WAŻNE | ✅ Co 30 min gdy brak nowych wejść — podsumowanie blokad (01.04) |
| RuntimeSetting 'description' kwarg crash | 🔴 PROBLEM | ✅ Usunięto nieistniejący parametr (01.04) |
| `enabled_strategies` ignorowane w collectorze | 🔴 KRYTYCZNE | ✅ Collector sprawdza `enabled_strategies` — kill switch + `strategy_name` w DecisionTrace (01.04) |
| API timeout podczas cyklu collectora | 🔴 KRYTYCZNE | ✅ SQLite WAL mode + async def→def (threadpool) — 0 timeoutów przy 10 równoczesnych requestach (01.04) |
| LIVE pozycje puste mimo portfela Binance | 🔴 KRYTYCZNE | ✅ `_get_live_spot_positions()` — Binance jako źródło prawdy |
| `best-opportunity` fałszywe CZEKAJ | 🔴 KRYTYCZNE | ✅ Iteracja kandydatów z bramkami, CZEKAJ tylko gdy WSZYSTKIE zablok. |
| Effective universe = tylko MarketData | ⚠️ WAŻNE | ✅ 4-tier fallback: watchlist → MarketData → ENV → Binance spot |
| Diagnostyka ignorowała Binance LIVE | ⚠️ WAŻNE | ✅ `state-consistency` porównuje Binance vs local |
| Brak goal evaluatora | ⚠️ WAŻNE | ✅ `POST /api/positions/goals/evaluate` — realism, required_move_pct |
| Frontend TradeDeskView pusty LIVE | 🔴 KRYTYCZNE | ✅ Renderuje "LIVE Spot" z Binance data |
| Frontend PositionAnalysisView null PnL | ⚠️ WAŻNE | ✅ Null-safe rendering, "LIVE Spot" badge |
| Telegram wiadomość exit bez PnL | ⚠️ WAŻNE | ✅ Strukturalny format: `[TRYB]`, cena wejścia/teraz, PnL% |
| Telegram wiadomość entry bez ranku | ⚠️ WAŻNE | ✅ Strukturalny format: rank, edge score, `[TRYB]` prefix |
| Brak testów akceptacyjnych LIVE/DEMO | ⚠️ WAŻNE | ✅ 6 nowych testów akceptacyjnych (181/181) |
| DEMO straty — za ciasne TP/SL + brak cooldown | 🔴 KRYTYCZNE | ✅ ATR stop 1.3→2.0, take 2.2→3.5, trail 1.0→1.5; SL cooldown eskalacja (loss_streak→7200s); TP win tracking; soft buy RSI<55 filter; aggressive profile: confidence 0.50, score 4.5, cooldown 300s (01.04 iter4) |
| Bot nie przełącza kapitału gdy brak wolnych środków | 🔴 KRYTYCZNE | ✅ `_maybe_rotate_capital()` — zamyka najgorszą pozycję gdy available_cash < min_notional, po rotacji odświeża tc (01.04 iter5) |
| Brak zewnętrznych źródł danych rynkowych | ⚠️ WAŻNE | ✅ Fear & Greed Index (alternative.me) + CoinGecko global — cache 5-10 min, bez klucza API; modyfikują confidence ±0.02-0.04 (01.04 iter5) |
| Brak retry logic w `binance_client.py` | ⚠️ WAŻNE | ✅ `@_binance_retry` dekorator: exp. backoff 1→2→4s, max 3 próby; obsługuje -1003/-1015/429/503 + requests.ConnectionError/Timeout; dodany do get_ticker_price/get_klines/get_orderbook/get_balances (01.04 iter5) |
| `decision_traces` nie objęte retencją (róśt DB) | ⚠️ WAŻNE | ✅ Dodano do `_purge_stale_data` z retencją 30 dni (01.04 iter5) |
| Brak automatycznych celów TP/SL dla otwartych pozycji | ⚠️ WAŻNE | ✅ `_auto_set_position_goals()` — AI ustawia `planned_tp/sl` dla pozycji bez celu: entry+ATR×3.5; HTF 4h +30% gdy mocny trend; wywołanie w `_demo_trading()` po `_check_hold_targets` (02.04 iter6) |
| `_check_exits` brak integracji z forecast | ⚠️ WAŻNE | ✅ `forecast_bullish` — query ForecastRecord (1h, ≤2h stary, WZROST, >0.5% wyżej); modyfikuje `trend_strong=True` → częściowe TP zamiast pełnego zamknięcia; propagowane do DecisionTrace (02.04 iter7) |
| `reset_demo_state` nie resetuje wszystkich in-memory timestamps | ⚠️ WAŻNE | ✅ Dodano `_last_idle_alert_ts=None` i `last_snapshot_ts=None` — pełny reset in-memory po demo/reset-balance (02.04 iter7) |
| `_maybe_rotate_capital` zamykała zyskowne pozycje | 🔴 KRYTYCZNE | ✅ Guard: pomiń rotację gdy `pnl_pct ≥ 0` (02.04 iter8) |
| `demo_trading_enabled` cicho wyłączone — bot nie handlował | 🔴 KRYTYCZNE | ✅ Przywrócono `true`; wznowiono trading DEMO z 497 EUR (01.04 iter10) |
| `_screen_entry_candidates` bez early-return przy braku gotówki | ⚠️ WAŻNE | ✅ `return` gdy `available_cash < min_order_notional` — brak 500+ zbędnych SKIP/cykl (01.04 iter10) |
| `min_notional_guard` (433×) — ATR-sizing za małe dla BTC/ETH | ⚠️ WAŻNE | ✅ Floor qty do `min_order_notional/price` po ATR+max_cash_pct gdy stać nas (01.04 iter10) |

---

## AKTUALNA LISTA PROBLEMÓW

### 🔴 KRYTYCZNE

*Brak otwartych problemów krytycznych.*

### ⚠️ WAŻNE

*Brak otwartych problemów ważnych.*

### 💡 NISKI PRIORYTET

**8. CORS `allow_origins=["*"]`**

- `backend/app.py:76` — otwarte dla wszystkich origin
- Akceptowalne w fazie DEMO/dev, niedopuszczalne w produkcji
- Przed live: ogranicz do `["http://localhost:3000", "https://twoja-domena.pl"]`

**9. Dwie ścieżki Telegram**

- `notification_hooks.py` — REST do Telegram Bot API
- `telegram_bot/bot.py` — python-telegram-bot
- Różne formaty wiadomości, możliwe duplikaty przy incydentach
- Wskazane: unified message formatter

**10. `AccountSummary.tsx` widget — używa `/api/account/summary`**

- Widget istnieje ale NIE jest renderowany nigdzie w MainContent.tsx
- Endpoint `/api/account/summary` nadal działa
- Widget stary, niespójny ze stanem systemu (nie propaguje `mode` dynamicznie)
- Wskazane: usunąć widget lub zaktualizować do `/api/portfolio/wealth`

**11. `candidate_validation.py` — warstwa prezentacyjna, NIE trading**

- Importowany w `account.py` do wyświetlania feeds (tuning suggestions) w UI
- Celowo NIE podłączony do collectora — pipeline eksperymentów jest semi-manualny w v0.7
- Pętla tuning → eksperyment → wdrożenie będzie domknięta autonomicznie w v0.8+

---

## 2. `backend/collector.py` (3 127 linii, 44 funkcje)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `__init__` | ✅ | Inicjalizacja watchlist, WS, flags |
| `_load_persisted_symbol_params` | ✅ | Wczytuje parametry z DB |
| `_runtime_context` | ✅ | Kontekst z runtime_settings |
| `_trace_decision` | ✅ | Persists ślad decyzji do DB |
| `_load_watchlist` | ✅ | ENV lub MarketData z DB |
| `_candidates` (L182, nested) | ✅ | Nested helper w `_load_watchlist` |
| `_has_openai_key` | ✅ | Jednolinijkowy helper |
| `_log_openai_missing` | ✅ | Loguje gdy brak klucza |
| `_log_no_watchlist` | ✅ | Loguje gdy pusta watchlist |
| `_refresh_watchlist_if_due` | ✅ | Co 5 min z CandidatePortfolio |
| `reset_demo_state` | ✅ | Pełny reset: demo_state + 5 timestamps (iter7) |
| `_create_pending_order` | ✅ | Pełna obsługa PendingOrder + auto-confirm |
| `_send_telegram_alert` | ✅ | REST alert Telegram z error handling |
| `_execute_confirmed_pending_orders` | ✅ | Realizuje BUY/SELL, liczy koszty |
| `_save_exit_quality` | ✅ | MFE/MAE/efektywność TP/SL |
| `_mark_to_market_positions` | ✅ | Aktualizuje current_price, unrealized_pnl |
| `_persist_demo_snapshot_if_due` | ✅ | Co 15 min AccountSnapshot |
| `_demo_trading` | ✅ | Orkiestruje: exits → hold → entries → brake |
| `_load_trading_config` | ✅ | Wszystkie parametry + ATR fallback gdy brak AI ranges |
| `_check_exits` | ✅ | ATR TP/SL + forecast_bullish integracja (iter7) |
| `_check_hold_targets` | ✅ | Tryb HOLD z docelową wartością EUR |
| `_auto_set_position_goals` | ✅ | AI auto-cel: entry+ATR×3.5; HTF 4h bias +30% (iter6) |
| `_screen_entry_candidates` | ✅ | Soft-buy entry; auto-confirm; 7 bramek + rating gate (entry_score_below_min) (iter9) |
| `_apply_daily_loss_brake` | ✅ | Blokuje trading po przekroczeniu drawdown |
| `_detect_crash` | ✅ | Wykrywa crash w oknie czasowym |
| `collect_market_data` | ✅ | Binance REST → MarketData |
| `collect_klines` | ✅ | Binance REST → Kline |
| `run_once` | ✅ | Poprawna sekwencja cyklu (2× `_execute_confirmed_pending_orders`) |
| `_check_forecast_accuracy` | ✅ | Weryfikuje dokładność prognoz |
| `_purge_stale_data` | ✅ | Czyści batch: market_data(7d), signals(7d), system_logs(14d), klines(30d), decision_traces(30d) + VACUUM |
| `_learn_from_history` | ✅ | Per-symbol kalibracja przez RuntimeSetting |
| `_ws_streams/handle/loop` | ✅ | WebSocket Binance |
| `start_ws/stop_ws/start/stop` | ✅ | Lifecycle management |

---

## 3. `backend/routers/signals.py` (1 808 linii, 11 endpointów)

| Endpoint / Funkcja | Status | Uwagi |
|---------|--------|-------|
| `GET /latest` | ✅ | DB → fallback live |
| `GET /top10` | ✅ | Live, sort wg confidence |
| `GET /top5` | ✅ | BUY/SELL filter |
| `GET /best-opportunity` | ✅ | BUY/SELL/CZEKAJ z confidence + reason |
| `GET /wait-status` | ✅ | Kiedy wejść; diagnoza Cel Użytkownika |
| `GET /final-decisions` | ✅ | Per-symbol rekomendacja z full context |
| `GET /execution-trace` | ✅ | Historia blokad entry |
| `GET /expectations` | ✅ | Cele użytkownika |
| `POST /expectations` | ✅ | Ustaw cel |
| `DELETE /expectations/{id}` | ✅ | Usuń cel |
| `GET /entry-readiness` | ✅ | *nowy* — can_enter_now, ready/blocked count, reason_pl |
| `_build_live_signals` | ✅ | Real RSI+EMA analiza |
| `_score_opportunity` | ✅ | Score: confidence×10, trend±1.5, RSI±1.5 |
| `_final_action_resolver` | ✅ | Resolver KUP/SPRZEDAJ/CZEKAJ |
| `_assess_goal_realism` | ✅ | Ocena realistyczności celu |

---

## 4. `backend/routers/market.py` (817 linii, 10 endpointów)

| Endpoint | Status | Uwagi |
|---------|--------|-------|
| `GET /summary` | ✅ | Agregacja z DB |
| `GET /kline` | ✅ | Świece OHLCV |
| `GET /ticker/{symbol}` | ✅ | Binance + fallback DB |
| `GET /orderbook/{symbol}` | ✅ | |
| `GET /ranges` | ✅ | Zakresy AI/heurystyczne |
| `GET /quantum` | ✅ | Risk-parity weights |
| `GET /analyze/{symbol}` | ✅ | Live analiza RSI/EMA/ATR |
| `GET /scanner` | ✅ | Top N symboli wg score |
| `GET /forecast/{symbol}` | ✅ | Prognoza ceny |
| `GET /allowed-symbols` | ✅ | Symbole z pełnym coverage danych |
| `_asset_to_candidates` | ✅ | Helper — jedna definicja (L18), używana L53 i L378 |

---

## 5. `backend/routers/orders.py` (633 linii, 9 endpointów)

| Endpoint | Status | Uwagi |
|---------|--------|-------|
| `GET /orders` | ✅ | Historia z filtrowaniem |
| `GET /orders/pending` | ✅ | |
| `POST /orders/pending` | ✅ | |
| `POST /orders/pending/{id}/confirm` | ✅ | |
| `POST /orders/pending/{id}/reject` | ✅ | |
| `POST /orders/pending/{id}/cancel` | ✅ | |
| `POST /orders` (create_order) | ✅ | DEMO: DB; LIVE: `binance.place_order()` |
| `GET /orders/export` | ✅ | StreamingResponse CSV |
| `GET /orders/stats` | ✅ | |

---

## 6. `backend/routers/positions.py` (1 910 linii, 14 endpointów)

| Endpoint | Status | Uwagi |
|---------|--------|-------|
| `GET /positions` | ✅ | Z enriched live price |
| `POST /positions/{id}/close` | ✅ | Ręczne zamknięcie |
| `POST /positions/close-all` | ✅ | |
| `GET /positions/analysis` | ✅ | Per-symbol: RSI, EMA, decyzja, HOLD mode |
| `GET /positions/{sym}/goal` | ✅ | Cel pozycji |
| `POST /positions/{sym}/goal` | ✅ | Ustaw cel |
| `DELETE /positions/{sym}/goal` | ✅ | |
| `GET /positions/{sym}/goal-analysis` | ✅ | Pełna analiza celu |
| `GET /positions/goals-summary` | ✅ | Zbiorczy widok celów |
| `GET /positions/{sym}/decision-history` | ✅ | Historia decyzji |
| `POST /positions/{sym}/evaluate-goal` | ✅ | Ocena realizacji celu |
| `POST /positions/sync-from-binance` | ✅ | *nowy* — import pozycji z portfela Binance |

---

## 7. `backend/routers/account.py` (2 058 linii, ~90 endpointów)

Kompletny plik agregujący governance, analytics, system management.

| Obszar | Status | Najważniejsze endpointy |
|--------|--------|------------------------|
| Konto (summary/kpi/history) | ✅ | `/summary`, `/kpi`, `/history`, `/risk` |
| System status | ✅ | `/system-status`, `/bot-activity` |
| Demo reset | ✅ | `/demo/reset-balance` |
| Governance — Experimenty | ✅ | CRUD + results |
| Governance — Rekomendacje | ✅ | CRUD + review + approve/reject |
| Governance — Promocje | ✅ | CRUD + monitoring |
| Governance — Rollback | ✅ | CRUD + decision + monitoring |
| Policy actions | ✅ | CRUD + resolve |
| Incydenty | ✅ | CRUD + escalation |
| Operator console | ✅ | Bundle + sekcje |
| Correlation chains | ✅ | timeline, correlations, chains |
| Trading effectiveness | ✅ | per-symbol, per-reason, per-strategy |
| Tuning insights | ✅ | candidates, summary |
| Experiment feed | ✅ | feed, summary |
| `require_admin` | ✅ | Używane na ~15 WRITE endpointach |

---

## 8. `backend/routers/portfolio.py` (569 linii, 5 endpointów)

| Endpoint | Status | Uwagi |
|---------|--------|-------|
| `GET /portfolio` | ✅ | Demo: DB; Live: Binance |
| `GET /portfolio/summary` | ✅ | |
| `GET /portfolio/wealth` | ✅ | KPI: equity, pnl, margins — używane przez CommandCenter |
| `GET /portfolio/live-sync` | ✅ | Synchronizacja z Binance |
| `GET /portfolio/forecast` | ✅ | Forecast dla portfela |

---

## 9. `backend/routers/debug.py` (224 linii, 2 endpointy)

| Endpoint | Status | Uwagi |
|---------|--------|-------|
| `GET /debug/state-consistency` | ✅ | Diagnoza spójności pozycji/zleceń |
| `GET /debug/last-exits` | ✅ | Historia wyjść z MFE/MAE/premature_exit |

---

## 10. `backend/routers/blog.py` / `control.py` / `telegram_intel.py`

| Router | Endpointy | Status |
|--------|-----------|--------|
| `blog` | `GET /latest`, `GET /list` | ✅ |
| `control` | `GET /state`, `POST /state`, `GET /hold-status` | ✅ |
| `telegram_intel` | `GET /state`, `GET /messages`, `POST /evaluate-goal`, `POST /log-event` | ✅ |

---

## 11. `backend/analysis.py` (~1 577 linii, 20 funkcji) — ✅ KOMPLETNY

Wskaźniki: 24 (RSI, EMA20/50, ATR, MACD, Bollinger, ADX, Stoch, volume_ratio, doji, inside_bar, VWAP24, Donchian, MFI, OBV, Fibonacci 23.6/38.2/61.8, engulfing, Supertrend, Squeeze Momentum, RSI Divergence). Trżysygnałowy scoring (15 sygnałów), ADX-aware zakresy, multi-TF 4h bias, online sentiment (Fear&Greed Index, CoinGecko global). Trzy ścieżki ranges: OpenAI / heurystyka / auto. Fallback bez OpenAI działa.

---

## 12. `backend/risk.py` (235 linii, 4 funkcje) — ✅ KOMPLETNY

10 bram ryzyka; `_find_summary` zwraca `{}` gdy element nie znaleziony — to zamierzone zachowanie (nie błąd).

---

## 13. `backend/runtime_settings.py` (1 063 linii, ~45 SettingSpec)

✅ Kompletny. Nowe ustawienia (z sesji naprawy blokerów):
- `demo_require_manual_confirm` (default: `False`) — auto-execute bez /confirm
- `demo_allow_soft_buy_entries` (default: `True`) — wejście gdy trend+RSI OK
- `demo_use_heuristic_ranges_fallback` (default: `True`) — ATR fallback
- `demo_min_entry_score` (default: `5.5`) — minimalna ocena kandydata

✅ `enabled_strategies` — sprawdzane w `_demo_trading()` jako kill switch (od 01.04)

---

## 14. `backend/binance_client.py` (601 linii, 21 funkcji)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `get_ticker_price` | ✅ | Z time sync |
| `get_klines` | ✅ | Historyczne świece |
| `get_account_info` | ✅ | Spot salda |
| `get_24hr_ticker` | ✅ | |
| `_signed_request` | ✅ | HMAC-SHA256 |
| `get_simple_earn_*` | 💤 | 1-linijkowe REST, nieprzetestowane |
| `get_futures_*` | 💤 | 1-linijkowe REST, nieprzetestowane |
| `get_balances` | ✅ | Spot, filtr zero-balance |
| `get_my_trades` | ✅ | Historia transakcji per symbol |
| `get_avg_buy_price` | ✅ | Średnia cena kupna |
| `place_order` | ✅ | Market/Limit BUY/SELL z pełnym error handling |
| `get_order_fills` | ✅ | Fills po egzekucji |
| `get_allowed_symbols` | ✅ | Symbole z exchange info |
| `resolve_symbol` | ✅ | Mapowanie formatów |

✅ Retry logic: `@_binance_retry` — exp. backoff 1→2→4s, max 3 próby; obsługuje -1003/-1015/429/503 + `requests.ConnectionError`/`Timeout`.

---

## 15. `backend/database.py` (1 119 linii, 30 modeli ORM)

✅ Kompletny. 30 tabel, bezpieczna migracja przez `_ensure_schema`.

⚠️ **GoalAssessment** — nowa tabela, ale column `created_at` BRAKUJE w starych wierszach (kolumna `timestamp` zamiast `created_at` w `DecisionTrace`). Efekt: `decision_traces.created_at` powoduje OperationalError — kolumna nazywa się `timestamp`.

---

## 16. `backend/accounting.py` (561 linii, 18 funkcji) — ✅ KOMPLETNY

Gross/Net PnL, cost breakdown, CostLedger, compute_demo_account_state.

---

## 17. `backend/telegram_intelligence.py` (833 linii) / `notification_hooks.py` (388 linii)

✅ Oba moduły kompletne.

⚠️ Dwie ścieżki Telegram — różne formaty wiadomości, możliwe duplikaty przy incydentach.

---

## 18. `backend/reporting.py` (189 linii) — ✅ KOMPLETNY

`config_snapshot_payload_report` — wywoływana `get_config_snapshot()` (nie pusta).

---

## 19. `backend/auth.py` (24 linii) — ✅ W UŻYCIU

`require_admin` jest używane na ~15 WRITE endpointach account.py.

---

## 20. `telegram_bot/bot.py` (576 linii, 18 komend)

✅ Wszystkie komendy działają.  
`API_BASE_URL` z ENV (default: `http://localhost:8000`) — poprawne.

---

## 21. `tests/test_smoke.py` (4 138 linii, 181 testów)

✅ 181/181 przechodzi (175 smoke + 6 akceptacyjnych).  
✅ 0 deprecation warnings — `datetime.utcnow()` zastąpione przez `utc_now_naive()`.

---

## 22. FRONTEND — `web_portal/`

### Widoki (18 zdefiniowanych w Sidebar, wszystkie mają routing)

| ID widoku | Komponent | Status |
|-----------|-----------|--------|
| `dashboard` | `CommandCenterView` | ✅ Pełny widok |
| `position-analysis` | `PositionAnalysisView` | ✅ |
| `execution-trace` | `ExecutionTraceView` | ✅ |
| `telegram-intel` | `TelegramIntelView` | ✅ |
| `trade-desk` | `TradeDeskView` | ✅ |
| `exit-diagnostics` | `ExitDiagnosticsView` | ✅ entry-readiness + spójność + exits |
| `portfolio` | `PortfolioView` | ✅ |
| `strategies` | `StrategiesView` | ✅ |
| `ai-signals` | `AiSignalsView` | ✅ |
| `risk` | `RiskView` | ✅ |
| `backtest` | `BacktestView` | ✅ |
| `economics`/`alerts`/`news` | `EmptyState` | ⚠️ Placeholdery |
| `settings`/`logs` | `SettingsView` | ✅ |
| `macro-reports` | `MacroReportsView` | ✅ |
| `reports` | `ReportsView` | ✅ |

### API calls frontend → backend (poprawność)

| Widget/View | Endpoint | Status |
|-------------|----------|--------|
| CommandCenterView | `/api/portfolio/wealth` | ✅ |
| CommandCenterView | `/api/signals/best-opportunity` | ✅ |
| CommandCenterView | `/api/signals/final-decisions` | ✅ |
| CommandCenterView | `/api/market/scanner` | ✅ |
| ExitDiagnosticsView | `/api/signals/entry-readiness` | ✅ nowy |
| ExitDiagnosticsView | `/api/debug/state-consistency` | ✅ |
| ExitDiagnosticsView | `/api/debug/last-exits` | ✅ |
| TelegramIntelView | `/api/telegram-intel/state` | ✅ |
| DecisionsRiskPanel | `/api/orders/pending` | ✅ |
| Orderbook.tsx | `/api/market/orderbook/BTCUSDT` | ⚠️ hardcoded BTCUSDT! |
| AccountSummary.tsx | `/api/account/summary` | ⚠️ widget nieużywany w MainContent |
| OpenOrders.tsx | `/api/positions` | ✅ (mylące nazewnictwo) |

---

## PODSUMOWANIE — LISTA AKTUALNYCH PROBLEMÓW

### 🔴 KRYTYCZNE

*Brak otwartych problemów krytycznych.*

### ⚠️ WAŻNE (napraw wkrótce)

*Brak otwartych problemów ważnych.*

### 💡 NISKI PRIORYTET

7. CORS `allow_origins=["*"]` — przed produkcją ograniczyć
8. Dwie ścieżki Telegram (`notification_hooks` + `telegram_bot/bot.py`) — ujednolicić formatter
9. `AccountSummary.tsx` widget — nieużywany, przestarzały (używa `/account/summary` zamiast `/portfolio/wealth`)
10. `get_simple_earn_*` / `get_futures_*`
11. `candidate_validation.py` — odłączony od collectora; pętla tuning→eksperyment→wdrożenie będzie autonomiczna w v0.8+ — 1-linijkowe stuby, nieprzetestowane

---

## METRYKI JAKOŚCI KODU (aktualizacja 2026-04-01 iter5)

| Metryka | Wartość |
|---------|---------|
| Pliki .py (backend) | 37 |
| Łączna liczba funkcji | ~295 |
| Puste/stub funkcje | 0 |
| Testy | 181/181 ✅ |
| TypeScript errors | 0 ✅ |
| Deprecation warnings (backend) | 0 ✅ |
| Deprecation warnings (testy) | 0 ✅ |
| Import nieużywany | 0 ✅ |
| Podwójna definicja funkcji | 0 ✅ |
| Stub katalogi | 0 ✅ (wszystkie usunięte) |
| DB rozmiar | ~275 MB (retencja decision_traces 30 dni dodana) |
| Endpointy API | 32 |

---

## MAPA ZALEŻNOŚCI (aktualizacja)

```
collector.py
├── analysis.py (maybe_generate_insights_and_blog, _heuristic_ranges)
├── risk.py (build_risk_context, evaluate_risk)
├── accounting.py (compute_demo_account_state)
├── runtime_settings.py (build_runtime_state)
├── governance.py (check_pipeline_permission)
├── candidate_validation.py ⚠️ NIE importowane przez collectora
└── database.py (wszystkie modele ORM)

routers/account.py
├── candidate_validation.py (generate_experiment_feed) ✅
├── tuning_insights.py ✅
├── trading_effectiveness.py ✅
├── correlation.py ✅
└── (governance, experiments, promotion, rollback ...) ✅

telegram_bot/bot.py → API_BASE_URL (ENV, default localhost:8000) ✅
notification_hooks.py → Telegram REST bezpośrednio ✅
```

---

## STATUS WERSJI v0.7 BETA (aktualizacja 2026-03-31)

**Co działa (kompletne):**
- Collector zbiera dane, handluje w trybie DEMO, auto-otwiera pozycje (5 blokerów naprawione)
- Real RSI/EMA analiza sygnałów; heurystyczny fallback ATR gdy brak OpenAI ranges
- Market Scanner, Forecast, Entry Readiness endpoints
- CommandCenterView z BestOpportunity, FinalDecisions, SystemStatusBar
- ExitDiagnosticsView z bannerem gotowości + kandydatami + diagnostyką spójności
- Telegram bot (18 komend, autoryzacja, write-endpointy z ADMIN_TOKEN)
- Pełny governance pipeline (experiments → rekomendacje → promocja → monitoring → rollback)
- Dokładna kalkulacja kosztów (fee, slippage, spread)
- Globalny przełącznik DEMO/LIVE — jedno źródło prawdy
- SymbolDetailPanel, Forecast overlay, WLFI status
- LIVE order execution przez Binance API (`place_order` zaimplementowane)
- Sync pozycji z Binance (`POST /positions/sync-from-binance`)

**Co jest niekompletne / do naprawy:**
- `enabled_strategies` — setting istnieje, collector ignoruje
- CORS dla produkcji — przed live

---

> Poniżej szczegółowy raport z każdego pliku i każdej funkcji — co kompletne, co niekompletne, co poprawić.

---

## LEGENDA STATUSÓW

| Symbol | Znaczenie |
|--------|-----------|
| ✅ KOMPLETNA | Funkcja zaimplementowana, działa poprawnie |
| ⚠️ NIEKOMPLETNA | Zaczęta, ale ma luki lub ograniczenia |
| 🔴 PROBLEM | Poważny błąd lub brakująca integracja |
| 💤 STUB | Szkielet bez prawdziwej implementacji |
| 🗂️ NIEUŻYWANA | Zaimplementowana, ale nie podpięta |

---

## 1. KATALOGI PUSTE / STUBOWE

### 🔴 `hft_engine/` — TYLKO .gitkeep — BRAK KODU
- **Status: ZUPEŁNIE PUSTY** — zarezerwowane miejsce, zero implementacji
- Rekomendacja: Usuń lub wypełnij.

### 🔴 `infrastructure/` — TYLKO .gitkeep — BRAK KODU
- **Status: ZUPEŁNIE PUSTY**

### 🔴 `quantum_optimization/` — TYLKO .gitkeep — BRAK KODU
- **Status: ZUPEŁNIE PUSTY** — chwytliwa nazwa, zero kodu.

### 💤 `blockchain_analysis/` — STUB `__init__.py` (~200 bajtów)
- Zero klas/funkcji
- Rekomendacja: Usuń lub dodaj najprostszy on-chain fetch

### 💤 `portfolio_management/` — STUB `__init__.py` (~174 bajty)
- Faktyczna logika portfolio jest w `backend/accounting.py` i `backend/routers/portfolio.py`
- **Problem: kod portfolio jest w `backend/`, a stub istnieje oddzielnie**

### 💤 `recommendation_engine/` — STUB `__init__.py` (~205 bajtów)
- Logika istnieje w `backend/recommendations.py`

### 💤 `ai_trading/` — STUB `__init__.py` (~218 bajtów)
- Kluczowy koncepcyjnie, ale pusty

### ✅ `telegram_bot/bot.py` — ISTNIEJE i DZIAŁA (535 linii, 18 komend)
- **Problemy opisane w sekcji 35 poniżej**

---

## 2. `backend/collector.py` (2272 linii, 39 funkcji) — RDZEŃ SYSTEMU

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `__init__` | ✅ | Inicjalizacja watchlist, WS, flags |
| `_runtime_context` | ✅ | Kontekst z runtime_settings |
| `_trace_decision` | ✅ | Persists ślad decyzji do DB |
| `_load_watchlist` | ✅ | ENV lub MarketData z DB |
| `_has_openai_key` | ✅ | Jednolinijkowy helper |
| `_refresh_watchlist_if_due` | ✅ | Co 5 min z CandidatePortfolio |
| `reset_demo_state` | ✅ | Pełny reset: demo_state + 5 timestamps (iter7) |
| `_create_pending_order` | ✅ | Pełna obsługa PendingOrder |
| `_send_telegram_alert` | ✅ | REST alert Telegram z error handling |
| `_execute_confirmed_pending_orders` | ✅ | Realizuje BUY/SELL, liczy koszty; walidacja cash w pętli kandydatów |
| `_save_exit_quality` | ✅ | MFE/MAE/efektywność TP/SL |
| `_mark_to_market_positions` | ✅ | Aktualizuje current_price, unrealized_pnl |
| `_persist_demo_snapshot_if_due` | ✅ | Co 15 min AccountSnapshot |
| `_demo_trading` | ✅ | Orkiestruje: exits → hold targets → entries → brake |
| `_load_trading_config` | ✅ | 195L — wszystkie parametry z runtime_settings |
| `_check_exits` | ✅ | ATR TP/SL + forecast_bullish integracja (iter7) |
| `_check_hold_targets` | ✅ | Tryb HOLD z docelową wartością EUR |
| `_screen_entry_candidates` | ✅ | Sygnały generowane przez `persist_insights_as_signals` przed wywołaniem; 7 bramek gating |
| `_apply_daily_loss_brake` | ✅ | Blokuje trading po przekroczeniu progu drawdown |
| `_detect_crash` | ✅ | Wykrywa crash w oknie czasowym |
| `collect_market_data` | ✅ | Binance REST → MarketData |
| `collect_klines` | ✅ | Binance REST → Kline tabel |
| `run_once` | ✅ | Poprawna sekwencja cyklu |
| `_purge_stale_data` | ✅ | Zapobiega przepełnieniu dysku |
| `_learn_from_history` | ✅ | Wynik uczenia persists przez RuntimeSetting (`learning_symbol_params`) — fałszywy alarm z audytu |
| `_ws_streams` / `_handle_ws_message` / `_ws_loop` | ✅ | WebSocket Binance |
| `start_ws` / `stop_ws` / `start` / `stop` | ✅ | Lifecycle management |
| `_candidates` (L161) | ⚠️ | Artefakt — metoda z `(self, db)` poza klasą? |

---

## 3. `backend/analysis.py` (672 linii, 20 funkcji)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `_klines_to_df` | ✅ | Kline ORM → DataFrame pandas |
| `_compute_indicators` | ✅ | RSI, EMA20/50, ATR, MACD, Bollinger |
| `_insight_from_indicators` | ✅ | RSI+EMA → signal + confidence + reason |
| `get_live_context` | ✅ | Używane przez signals.py, positions.py, market.py |
| `_compute_quantum_weights` | ✅ | Risk-parity weights (1/vol); **nazwa "quantum" myląca** |
| `generate_market_insights` | ✅ | Insights dla całej watchlisty |
| `_heuristic_ranges` | ✅ | Fallback EMA+ATR gdy brak OpenAI |
| `_openai_ranges` | ✅ | OpenAI prompt z backoff; **parsowanie JSON może zawieść** |
| `persist_insights_as_signals` | ✅ | Insights → Signal tabela |
| `generate_blog_post` | ✅ | Generuje BlogPost |
| `maybe_generate_insights_and_blog` | ✅ | Orchestrator: max 1x na godzinę |

---

## 4. `backend/risk.py` (227 linii, 4 funkcje)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `build_risk_context` | ✅ | Zbiera dane do oceny ryzyka |
| `evaluate_risk` | ✅ | 10 bram ryzyka — kompletne; daily_drawdown w trybie live naprawione (Sesja C) |

---

## 5. `backend/runtime_settings.py` (1028 linii, 43 funkcje)

Solidny moduł konfiguracyjny. Wszystkie funkcje implementowane.

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| Parsery ENV (`_parse_*`) | ✅ | Walidacja z zakresami |
| `build_symbol_tier_map` | ✅ | |
| `_cross_validate` | ✅ | Wzajemna walidacja parametrów |
| `ensure_runtime_snapshot` | ✅ | Persists config przy starcie |
| `upsert_overrides` | ✅ | Zmiana settings przez API |
| `apply_runtime_updates` | ✅ | HTTP payload → settings |
| `build_runtime_state` | ✅ | Główna funckja stanu runtime |

**✅ NAPRAWIONE:** `datetime.utcnow()` zastąpione przez `utc_now_naive()` z `backend.database` (203 zastąpienia w 26 plikach)

---

## 6. `backend/routers/market.py` (672 linii, 13 funkcji)

| Endpoint / Funkcja | Status | Uwagi |
|---------|--------|-------|
| `get_market_summary` | ✅ | Agregacja danych z DB |
| `get_kline_data` | ✅ | |
| `get_ticker` | ✅ | Binance + fallback DB |
| `get_orderbook` | ✅ | |
| `get_price_ranges` | ✅ | |
| `get_quantum_analysis` | ✅ | |
| `analyze_now` | ✅ | Live analiza symbolu |
| `_score_symbol` | ✅ | *dodane* — composite RSI+EMA+ATR score |
| `market_scanner` | ✅ | *dodane* — GET /api/market/scanner |
| `get_forecast` | ✅ | *dodane* — GET /api/market/forecast/{symbol} |
| `_candidates` | 🔴 | **PODWÓJNA DEFINICJA** — L40 i L374 w tym samym module! Python użyje L374, L40 jest martwym kodem |

---

## 7. `backend/routers/signals.py` (~380 linii, 7 funkcji) — *przepisane + rozszerzone*

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `_build_live_signals` | ✅ | Real RSI+EMA analiza |
| `_get_symbols_from_db_or_env` | ✅ | |
| `get_latest_signals` | ✅ | DB → fallback live |
| `get_top10_signals` | ✅ | Live, sort wg confidence |
| `get_top5_signals` | ✅ | BUY/SELL filter |
| `_score_opportunity` | ✅ | *dodane sesja F* — scoring: confidence×10, trend±1.5, RSI±1.5, R/R+1.0, HOLD-3.0 |
| `get_best_opportunity` | ✅ | *dodane sesja F* — `GET /api/signals/best-opportunity`, zwraca BUY/SELL/CZEKAJ |

---

## 8. `backend/routers/positions.py` (483 linii, 6 funkcji)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `get_positions` | ✅ | Z enriched live price |
| `close_position` | ✅ | Ręczne zamknięcie |
| `close_all_positions` | ✅ | |
| `_analyze_position` | ✅ | 175L — bogata analiza: RSI, EMA, trend, decyzja, HOLD mode |
| `position_analysis` | ✅ | Używane przez CommandCenterView |

---

## 9. `backend/routers/orders.py` (530 linii, 10 funkcji)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `get_orders` | ✅ | Historia z filtrowaniem |
| `get_pending_orders` | ✅ | |
| `create_pending_order` | ✅ | |
| `confirm_pending_order` | ✅ | |
| `reject_pending_order` | ✅ | |
| `cancel_pending_order` | ✅ | |
| `create_order` | ⚠️ | **Tryb live NIE wywołuje Binance API** — komentarz `# Jeśli LIVE, call Binance` ale niezaimplementowane |
| `export_orders_csv` | ✅ | StreamingResponse CSV |
| `get_order_stats` | ✅ | |
| `generate_demo_orders` | ✅ | Usunięte (Sesja E) — blok generowania losowych zleceń w `export_orders_csv` |

---

## 10. `backend/routers/account.py` (1788 linii, 84 funkcje)

Ogromny plik — agreguje wiele obszarów. Wszystkie funkcje zaimplementowane.

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `get_account_summary` | ✅ | Demo: accounting.py; Live: Binance |
| `get_openai_status` | ✅ | Test-call z latency |
| `get_account_kpi` | ✅ | KPI dla dashboardu |
| `get_system_status` | ✅ | *dodane* — collector/WS/data age |
| `reset_demo_balance` | ✅ | *dodane* — reset salda demo |
| `get_risk_summary` | ✅ | |
| Governance endpoints | ✅ | Incydenty, policy actions, chain queries |
| `worker_status` | ✅ | |
| `trading_effectiveness_*` | ✅ | Thin wrappers |
| `tuning_insights_*` | ✅ | Thin wrappers |
| `experiment_feed*` | ✅ | |

---

## 11. `backend/routers/portfolio.py` (120 linii, 2 funkcje)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `get_portfolio` | ⚠️ | Demo: brak live price update; Live: calls Binance earn/futures; **`import random` nieużywane** |
| `get_portfolio_summary` | ✅ | |

---

## 12. `backend/binance_client.py` (426 linii, 20 funkcji)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `get_ticker_price` | ✅ | Z time sync |
| `get_klines` | ✅ | Historyczne świece |
| `get_account_info` | ✅ | Spot salda |
| `get_24hr_ticker` | ✅ | |
| `_signed_request` | ✅ | HMAC-SHA256 |
| `get_simple_earn_*` | 💤 | 1-linijkowe REST calls, nieprzetestowane |
| `get_futures_*` | 💤 | 1-linijkowe REST calls, nieprzetestowane |
| `get_balances` | ✅ | Spot, filtr zero-balance |
| `resolve_symbol` | ✅ | Mapowanie formatów |

**⚠️ Problem:** Brak retry logic — API fail → exception → brak danych. Dodaj tenacity retry.

---

## 13. `backend/accounting.py` (547 linii, 19 funkcji) — KOMPLETNY ✅

Wszystkie funkcje: cost summaries, risk snapshot, `compute_demo_account_state` (126L).

---

## 14. `backend/trading_effectiveness.py` (788 linii, 14 funkcji) — WZOROWY ✅

Kompletna analiza efektywności: symbol/reason/strategy, cost leakage, overtrading, edge, improvement suggestions.

---

## 15. `backend/tuning_insights.py` (566 linii, 10 funkcji) — KOMPLETNY ✅

**⚠️ Problem:** Wyniki tuning_insights **nie są widoczne w CommandCenterView** (endpoint istnieje, brak UI).

---

## 16. `backend/candidate_validation.py` (514 linii, 14 funkcji)

**Kompletny moduł** — klasyfikuje kandydatów, wykrywa konflikty, grupuje bundles, generuje experiment_feed.

**🔴 Krytyczny gap:** `collector.py` go NIE importuje. Experiment feed generowany przez `account.py` nie wpływa na autonomiczne decyzje collectora. Pętla tuning→eksperyment→wdrożenie nie domknięta.

---

## 17. `backend/recommendations.py` (217L) / `experiments.py` (457L) / `governance.py` (464L) / `policy_layer.py` (498L) — KOMPLETNE ✅

Pełna pipeline governance: eksperyment → rekomendacja → promocja → monitoring → rollback.

---

## 18. `backend/notification_hooks.py` (373 linii, 19 funkcji)

**⚠️ Problem:** Dwie ścieżki Telegram:
1. `notification_hooks.send_telegram_message` — bezpośredni REST
2. `telegram_bot/bot.py` — python-telegram-bot

Nie zsynchronizowane — różne formaty, możliwe duplikaty.

---

## 19. `backend/reporting.py` (188 linii, 9 funkcji)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `config_snapshot_payload_report` | 🔴 | `return {}` — dosłownie pusta implementacja |
| Pozostałe | ✅ | |

---

## 20. `backend/auth.py` (24 linii, 1 funkcja)

| Funkcja | Status | Uwagi |
|---------|--------|-------|
| `require_admin` | ⚠️ | Działa, ale **nie używane na żadnym endpoincie**; hasło w plaintext w ENV |

---

## 21. `backend/database.py` (937 linii, 16 funkcji) — KOMPLETNY ✅

Modele ORM: 25+ tabel.  
`_ensure_schema` — bezpieczne migracje ADD COLUMN.

---

## 22. `backend/system_logger.py` / `backend/app.py` / `backend/reevaluation_worker.py` / `backend/operator_console.py` / `backend/correlation.py` — KOMPLETNE ✅

---

## 23. `telegram_bot/bot.py` (535 linii, 18 komend)

| Komenda | Status | Uwagi |
|---------|--------|-------|
| `/start` | ✅ | Lista komend |
| `/status` | ✅ | Ostatni sygnał, czas |
| `/stop` | ✅ | Naprawione (Sesja E): wywołuje `POST /api/control/state` z `ADMIN_TOKEN` |
| `/risk` | ✅ | Metryki ryzyka |
| `/top10` | ✅ | REST call do API |
| `/top5` | ✅ | |
| `/portfolio` | ✅ | |
| `/orders` | ✅ | |
| `/positions` | ✅ | |
| `/lastsignal` | ✅ | |
| `/blog` | ✅ | |
| `/logs` | ✅ | |
| `/report` | ✅ | |
| `/confirm <ID>` | ✅ | WRITE — potwierdza pending order |
| `/reject <ID>` | ✅ | WRITE — błąd wcięcia naprawiony (Sesja E) |
| `/governance` | ✅ | WRITE — autoryzacja dodana (Sesja E) |
| `/freeze` | ✅ | WRITE — używa ENV `API_BASE_URL`; autoryzacja obecna |
| `/incidents` | ✅ | Autoryzacja dodana (Sesja E) |

**✅ Naprawione (Sesja E):**
- `/stop` — teraz wywołuje `POST /api/control/state` z poprawnym payloadem i `ADMIN_TOKEN`
- `TELEGRAM_CHAT_ID` — brak konfiguracji blokuje wszystkich (było: przepuszczało wszystkich)
- `/governance` i `/incidents` — dodano `_check_auth` (wcześniej read-only bez weryfikacji)
- `reject_command` — naprawiono brakujący `if not context.args:` (błąd wcięcia)

---

## PODSUMOWANIE — LISTA PROBLEMÓW DO NAPRAWY

### ✅ NAPRAWIONE
1. `telegram_bot/bot.py:stop_command` — teraz wywołuje `POST /api/control/state` z `ADMIN_TOKEN` (Sesja E)
2. `telegram_bot/bot.py` — brak `TELEGRAM_CHAT_ID` teraz blokuje wszystkich (Sesja E)
3. `telegram_bot/bot.py` — `/governance` i `/incidents` mają teraz `_check_auth` (Sesja E)
4. `telegram_bot/bot.py:reject_command` — naprawiono błąd wcięcia (Sesja E)
5. `routers/orders.py:generate_demo_orders` — blok usunięty (Sesja E)
6. `risk.py:evaluate_risk` — daily_drawdown w trybie live naprawiony (Sesja C)
7. `collector.py:_learn_from_history` — fałszywy alarm; już persists przez RuntimeSetting (potwierdzone Sesja E)
8. `signals.py:persist_insights_as_signals` — wywoływane po każdym cyklu `maybe_generate_insights_and_blog`; heurystyka → DB działa bez OpenAI (potwierdzone Sesja E)
9. **ETAP 2** — `Economics/Alerty/Wiadomości` wyświetlają EmptyState (nie fałszywe dane proxy); wskaźniki techniczne EMA20/EMA50 + mini RSI na wykresach; usunięto hardcoded `mode=demo` z OpenOrders, DecisionsRiskPanel (GAP-15/16/09/06)
10. **ETAP 3** — Globalny przełącznik DEMO/LIVE: `Dashboard.tsx` jako jedyne źródło prawdy dla `tradingMode`, propagacja przez props do wszystkich widgetów i widoków; `Topbar.tsx`/`Sidebar.tsx` z przełącznikiem UI (zielony=DEMO, amber=LIVE)
11. **ETAP 4** — `routers/account.py:get_account_summary` LIVE: graceful HTTP 200 z `_info`; `DecisionRisk.tsx`/`MarketInsights.tsx`: czytelne stany błędów
12. **ETAP 6** — `routers/account.py:get_account_kpi` LIVE: `HTTPException(404)` → graceful HTTP 200 z `_info`; `Topbar.tsx` przełącznik DEMO/LIVE; `CommandCenterView`: banner `_info` fallback LIVE; `DecisionsView`: banner `_info`
13. **ETAP 7** — `routers/portfolio.py:get_portfolio_wealth` rozszerzone o pola KPI: `equity_change`, `equity_change_pct`, `margin_level`, `used_margin`, `balance`, `unrealized_pnl`; `CommandCenterView`/`KpiStrip`/`DecisionsView` zmigrowane z `/account/kpi` → `/portfolio/wealth`
14. **ETAP 8** — `DashboardV2View`/`SettingsView` zmigrowane z `/account/summary` → `/portfolio/wealth`; **zero odwołań do `/account/summary` lub `/account/kpi` w frontendzie**; pełna weryfikacja 30 endpointów (30/30 OK); `CHECKLIST_OPERACYJNA.md` utworzona

### 🔴 KRYTYCZNE (następna naprawa)
1. `backend/routers/market.py` — **podwójna definicja `_candidates`** (L40 martwy kod)
2. `backend/routers/orders.py:create_order` — **tryb live nie wywołuje Binance**
3. `backend/auth.py:require_admin` — **nie używane na żadnym endpoincie**

### ⚠️ WAŻNE (napraw wkrótce)
4. `portfolio.py` — `import random` (nieużywane)
5. `reporting.py:config_snapshot_payload_report` — zwraca `{}`
6. ✅ `datetime.utcnow()` — NAPRAWIONE: 203 zastąpienia `utc_now_naive()` w 26 plikach

### 💡 NIZKI PRIORYTET
14. Empty dirs (`hft_engine/`, `infrastructure/`, `quantum_optimization/`) — usuń
15. `collector.py:_check_exits` — brak integracji z forecast
16. `tuning_insights` — brak widoku wyników w CommandCenterView
17. CORS `allow_origins=["*"]` — przed produkcją ograniczyć do origen
18. `binance_client.py` — brak retry logic (tenacity)

---

## MAPA ZALEŻNOŚCI

```
collector.py
├── analysis.py (maybe_generate_insights_and_blog)
├── risk.py (evaluate_risk)
├── accounting.py (compute_demo_account_state)
├── runtime_settings.py (build_runtime_state)
├── governance.py (check_pipeline_permission)
├── candidate_validation.py ← ⚠️ NIEUŻYWANE przez collectora!
└── database.py

telegram_bot/bot.py ← ⚠️ używa localhost:8000 zamiast ENV API_URL
routers/account.py ← agreguje 12+ modułów
```

### 🔴 `candidate_validation.py` — ODŁĄCZONY
Kompletny, ale nie wpływa na decyzje collectora. Pętla tuning→eksperyment→wdrożenie NIE JEST domknięta.

---

## METRYKI JAKOŚCI KODU

| Metryka | Wartość |
|---------|---------|
| Pliki .py (backend) | 37 |
| Łączna liczba funkcji | ~265 |
| Puste/stub funkcje | 0 |
| Testy | 175/175 ✅ |
| TypeScript errors | 0 ✅ |
| Deprecation warnings | 0 (`utc_now_naive()` — helper w database.py) |
| Import nieużywany | `import random` w portfolio.py |
| Podwójna definicja | 1 (`_candidates` w market.py) |

---

## STATUS WERSJI v0.7 BETA

**Co działa (kompletne):**
- Collector zbiera dane, handluje w trybie demo, zarządza ryzykiem
- Real RSI/EMA analiza sygnałów (bez random)
- Market Scanner, Forecast endpoints
- CommandCenterView z SystemStatusBar
- Telegram bot (18 komend, z lukami bezpieczeństwa)
- Pełny governance pipeline
- Dokładna kalkulacja kosztów (fee, slippage, spread)
- **Globalny przełącznik DEMO/LIVE** — jedno źródło prawdy w `Dashboard.tsx`, wszystkie widgety reagują
- **SymbolDetailPanel** — slide-in overlay z wykresem, prognozą, KUP/ZAMKNIJ
- **Forecast overlay** — przerywana linia + EMA20/50 + mini RSI na wykresach
- **LIVE fallback** — brak kluczy Binance nie crashuje UI; graceful 200 + info komunikat
- **WLFI status** — pasek postępu celu 300 EUR w DashboardV2

**Co jest niekompletne / do naprawy:**
- Tryb live: brak Binance order execution (`create_order` w `orders.py`)
- `backend/auth.py:require_admin` — nie używane na żadnym endpoincie
- `market.py` — podwójna definicja `_candidates` (martwy kod na L40)
- `reporting.py:config_snapshot_payload_report` — zwraca `{}`
- ~7 pustych katalogów stub (`hft_engine/`, `infrastructure/`, itp.)
- LIVE pokazuje puste dane gdy brak kluczy — wymaga uzupełnienia `.env`
- **Economics / Alerty / Wiadomości** — widoki pokazują EmptyState, brak własnych danych

---

*Poprzednia wersja dokumentu (2025-07):*

---

## Cel dokumentu

Ocena dojrzałości **rdzenia tradingowego** (kolektor → sygnał → wejście → egzekucja → wyjście)
w stosunku do **warstwy kontrolnej** (governance, risk gates, experiments, tuning, rollback).

Pytania do odpowiedzi:
- A) Czy entry logic jest wystarczająco rozbudowana?
- B) Czy execution path pokrywa scenariusze live?
- C) Czy warstwa strategii jest wydzielona?
- D) Czy symbol selection ma jakościowy ranking?
- E) Czy runtime_settings obejmuje krytyczne parametry?
- F) Czy decision trace daje wystarczającą obserwabilność?

---

## SEKCJA 1 — Co jest świetnie domknięte ✅

### 1.1 Warstwa kontrolna i governance (ETAP 1-8)

System posiada **jeden z najbardziej rozbudowanych frameworków kontroli zmian** jaki można spotkać w botach tradingowych tej skali:

| Moduł | Linie | Co robi |
|---|---|---|
| `runtime_settings.py` | ~870 | ~45 tunowalnych parametrów z walidacją, snapshotami, API |
| `risk.py` | 227 | 10 bram ryzyka (drawdown, exposure, loss streak, kill switch, leakage, expectancy) |
| `experiments.py` | 457 | A/B framework z metrykami, promocją, wycofywaniem |
| `candidate_validation.py` | 514 | Walidacja kandydatów zmian, detekcja konfliktów, pakowanie bundli |
| `tuning_insights.py` | 566 | Automatyczne kandydaty zmian z diagnostyki |
| `promotion_flow.py` | 209 | Promocja kandydatów z monitoring post-promotion |
| `rollback_flow.py` | 158 | Bezpieczne wycofanie zmian |
| `rollback_decision.py` | 246 | Heurystyka decyzji rollback |
| `post_promotion_monitoring.py` | 278 | Monitoring po promocji |
| `post_rollback_monitoring.py` | 278 | Monitoring po rollbacku |
| `review_flow.py` | 143 | Ścieżka recenzji zmian |
| `trading_effectiveness.py` | 716 | Diagnostyka: edge, overtrading, cost leakage, per-symbol/strategy |

**Łącznie ~4600 linii kodu kontrolnego.** To jest ~2.5x więcej niż sam rdzeń tradingowy.

### 1.2 Risk gates — dojrzałe i dobrze zintegrowane

`evaluate_risk()` sprawdza **10 bram** przed każdym wejściem:
1. Kill switch
2. Dzienny drawdown (max_daily_drawdown)
3. Seria strat (loss_streak_limit)
4. Max otwartych pozycji
5. Max transakcji / dzień
6. Max transakcji / godzinę / symbol
7. Całkowita ekspozycja
8. Ekspozycja na symbol
9. Cost leakage ratio
10. Net expectancy (symbol + strategia)

Każda brama generuje `reason_code`, zapisywany w DecisionTrace — można odtworzyć *dlaczego* transakcja została zablokowana.

### 1.3 Cost-aware accounting

`accounting.py` (547 linii) poprawnie modeluje:
- Gross PnL vs Net PnL (po fee, slippage, spread)
- Cost breakdown per order/position
- CostLedger z `expected_value` i `actual_value`
- Risk snapshot i activity snapshot do bram ryzyka

### 1.4 Decision Trace — struktura OK

Model `DecisionTrace` posiada:
- `signal_summary` — parametry sygnału w momencie decyzji
- `risk_gate_result` — wynik bram ryzyka
- `cost_gate_result` — wynik bramy kosztowej
- `execution_gate_result` — wynik bramy egzekucji
- `config_snapshot_id` — powiązanie z dokładną konfiguracją
- `strategy_name`, `reason_code`, `action_type`

Collector faktycznie zapisuje trace dla **zarówno odrzuconych jak i zaakceptowanych** decyzji (`_trace_decision()`).

### 1.5 Provider fallback (AI_PROVIDER=auto)

`analysis.py` posiada **trzy ścieżki** generowania price ranges:
1. `openai` — GPT via API (domyślne)
2. `heuristic` — ATR + Bollinger bands (darmowe, bez API)
3. `auto` — OpenAI z fallbackiem na heurystykę

Heurystyka (`_heuristic_ranges`) jest solidna: ATR-based widths, alignment z Bollinger bands, korekty RSI, korekta trendu. System **nie jest 100% zależny od OpenAI** — ma darmowy fallback.

### 1.6 Kalibracja na historii

`_learn_from_history()` co 1h kalkuluje per-symbol:
- `min_confidence` — dynamicznie na bazie zmienności
- `risk_scale` — skalowanie pozycji wg vol
- `volatility`, `trend_strength`

To prosty ale działający mechanizm adaptacji.

---

## SEKCJA 2 — Co jest średnie lub niezweryfikowane ⚠️

### 2.1 ~~Monolityczna `_demo_trading()`~~ → ✅ DOMKNIĘTE (P2)

**Było:** ~700 linii w jednej metodzie.  
**Zrobione:** Wydzielono 4 metody:
- `_load_trading_config()` — konfiguracja + stan konta + zakresy AI
- `_check_exits()` — TP/SL/trailing + alerty drawdown
- `_screen_entry_candidates()` — screening + gating (7 bramek)
- `_apply_daily_loss_brake()` — globalny hamulec strat

`_demo_trading()` jest teraz ~35-liniowym orkiestratorem. Testy 167/167 zielone.

### 2.2 Jedna strategia: "demo_collector"

**Problem:** `strategy_name` istnieje w DecisionTrace i PendingOrder, ale **zawsze** ma wartość `"demo_collector"`. Nie ma mechanizmu:
- definiowania innych strategii
- porównania strategii (poza retrospektywnym `trading_effectiveness`)
- wyłączenia jednej strategii bez wyłączenia całego tradingu

**Konsekwencje:**
- `enabled_strategies` w runtime_settings istnieje, ale nigdzie nie jest sprawdzane w `_demo_trading()`
- `compute_strategy_performance()` zwraca zawsze jedną strategię
- Experiments framework jest gotowy na multi-strategy, ale silnik nie

**Rekomendacja:** Minimum viable: choćby dwa warianty entry logic (np. "conservative" vs "aggressive") z różnymi progami extreme_min_conf / rating.

### 2.3 ~~env vars w collector NIE przeniesione do runtime_settings~~ → ✅ DOMKNIĘTE (P1)

**Było:** ~15 krytycznych parametrów tradingowych w `os.getenv()`.  
**Zrobione:** Dodano 15 nowych `SettingSpec` w `runtime_settings.py` (sekcje execution/ai/risk) i zmieniono collector na `config.get()`.  
Migrowane: `atr_stop_mult`, `atr_take_mult`, `atr_trail_mult`, `extreme_range_margin_pct`, `extreme_min_confidence`, `extreme_min_rating`, `demo_min_signal_confidence`, `demo_max_signal_age_seconds`, `demo_order_qty`, `demo_max_position_qty`, `demo_min_position_qty`, `pending_order_cooldown_seconds`, `max_ai_insights_age_seconds`, `crash_window_minutes`, `crash_drop_percent`, `crash_cooldown_seconds`.  
Dodana walidacja krzyżowa: `atr_take_mult > atr_stop_mult`.  
Pozostałe `os.getenv()` to parametry infrastrukturalne (klucze API, interwały kolekcji, watchlist refresh).

### 2.4 Model kosztowy — szacunkowy, nie zmierzony

**Problem:** `cost_gate_result` w DecisionTrace zawiera `expected` koszty:
- `taker_fee` = `notional × taker_fee_rate`
- `slippage` = `notional × slippage_bps / 10000`
- `spread` = `notional × spread_buffer_bps / 10000`

Ale **nigdy nie mierzy faktycznych kosztów** — bo w trybie DEMO nie ma realnych egzekucji. `CostLedger` ma pola `expected_value` i `actual_value`, ale `actual_value` jest zawsze NULL w trybie demo.

**Konsekwencje:**
- `cost_leakage_ratio` w diagnostyce trading_effectiveness bazuje na szacunkach
- Nie wiadomo, czy `slippage_bps=5` jest realistyczne
- Przejście na live ujawni rozbieżności

**Rekomendacja:** Przy wejściu live — natychmiast dodać pomiar `actual_value` z Binance fills i porównanie expected vs actual.

### 2.5 Symbol selection — brak rankingu/scoringu

**Obecna logika:**
1. Pobierz balanse z Binance → wyciągnij aktywa z `free > 0`
2. Dołącz `USDT` do każdego → powstaje watchlist
3. Możliwość override z runtime_settings

**Brakuje:**
- Rankingu symboli wg siły trendu / momentum / volatility
- Filtrowania symboli o niskim wolumenie / spreadzie
- Dynamicznego dodawania/usuwania symboli na bazie screenerów
- Priorytetyzacji (symbol z lepszym edge powinien mieć wyższy priorytet)

**Rekomendacja:** Minimum viable: filtruj po wolumenie 24h i przesortuj watchlist wg ATR/price (normalized volatility).

### 2.6 Brak live execution path

**Problem:** `binance_client.py` (426 linii) nie posiada:
- `place_order(symbol, side, qty, price)` — nawet jako stub
- `cancel_order()`
- `get_order_status()`
- Logiki market/limit order

Cały flow jest DEMO:
```
Signal → PendingOrder → Telegram /confirm → collector writes Order/Position to DB
```

Nie ma żadnego kodu, który **wysyła zlecenie na Binance**. Przejście na live wymaga napisania execution layer od zera.

**Rekomendacja:** Dodać minimalny execution module:
- `execute_market_order(symbol, side, qty)` z Binance API
- `get_order_fills(order_id)` dla pomiaru actual costs
- Circuit breaker (max N orders per minute)

---

## SEKCJA 3 — Co ma największy wpływ na wynik bota 💰

Poniżej posortowane od **największego** do **najmniejszego** wpływu na PnL:

### 🏆 3.1 Entry timing i quality (KRYTYCZNY)

**Obecny flow:**
```
Signal (confidence ≥ 0.75)
→ EMA20 > EMA50 (trend filter)
→ RSI ≤ rsi_buy (oversold filter)
→ Cena w buy_low–buy_high range (AI/heuristic)
→ Extreme entry filter (cena na krawędzi zakresu, margin 2%)
→ Rating ≥ 4/5 AND confidence ≥ 0.85
→ Cost gate (expected_move > required_move)
→ Risk gate (10 bram)
→ PendingOrder → Telegram → confirm
```

**Ocena:** Entry logic jest **rygorystyczna** — 7 warstw filtrowania. To chroni przed złymi wejściami, ale może też powodować **zbyt mało transakcji**. Brak danych o hit rate, frequency, missed opportunities.

**Klucz do poprawy PnL:**
- Zmierzyć jak często bot **pomija** dobre okazje (false negatives)
- A/B test: strict vs relaxed extreme_margin_pct
- Dodać alternatywny entry mode (np. momentum-based bez wymogu AI ranges)

### 🥈 3.2 Exit logic — TP/SL/trailing (WAŻNY)

**Obecny flow:**
- **Stop Loss:** `entry_price - ATR × 1.3` (long), `entry_price + ATR × 1.3` (short)
- **Take Profit:** `entry_price + ATR × 2.2` (long), `entry_price - ATR × 2.2` (short)
- **Trailing stop:** Gdy EMA20 > EMA50, SL podąża za ceną (`price - ATR × trail_mult`)
- Sprawdzenie: co cykl (`COLLECTION_INTERVAL_SECONDS=60s`)

**Problemy:**
- TP/SL nie są dynamiczne po wejściu — ATR z momentu entry, nie aktualizowany
- Brak partial exits (np. sprzedaj 50% na TP1, 50% na TP2)
- Trailing stop aktywuje się tylko przy trend confirmation (EMA20 > EMA50) — w ranging market TP/SL są statyczne
- Sprawdzanie co 60s = w szybkim rynku mogą być duże slippage na exit

**Klucz do poprawy PnL:**
- Partial exits mogą znacząco poprawić Sharpe ratio
- Dynamiczny trailing (time-based + ATR decay)
- WS tick-by-tick exit checking zamiast polling co 60s

### 🥉 3.3 Position sizing (WAŻNY)

**Obecny flow:**
```python
risk_amount = equity × risk_per_trade           # np. 10000 × 0.015 = 150
stop_distance = ATR × atr_stop_mult             # np. 500 × 1.3 = 650
qty = risk_amount / (stop_distance × price)     # 150 / (650 × 60000) = 0.0000038
```

Plus skalowanie:
- Loss streak: `qty × max(0.3, 1 - streak × 0.15)`
- Win streak: `qty × min(2.0, 1 + streak × 0.1)`
- Risk gate: `qty × position_size_multiplier` (redukowany przy exposure blisko limitu)
- Symbol-level risk_scale z `_learn_from_history`
- Max/min qty clamp

**Ocena:** Solidna logika — ATR-based sizing z wieloma modyfikatorami. **Lepsze niż 90% botów** na tym etapie rozwoju.

**Potencjał poprawy:**
- Kelly criterion zamiast fixed fractional
- Volatility-normalized position sizing (w _learn_from_history jest podstawa, ale nie jest w pełni wykorzystana)

### 3.4 AI ranges quality (ŚREDNI wpływ)

**Problem:** Jakość ranges zależy od:
- openai: GPT-generated ranges — brak walidacji dokładności
- heuristic: ATR + Bollinger — rozsądne, ale nie uwzględnia fundamentów

**Brak backtestingu ranges:** System nie sprawdza, czy ranges z 6h temu były trafne. Nie kalkuluje hit rate zakresów.

**Rekomendacja:** Dodać tabelę `range_accuracy` — po X godzinach sprawdź, czy cena trafiła w buy/sell range. To da metrykę jakości AI vs heuristic.

### 3.5 Overtrading protection (NIŻSZY, ale ważny)

**Status:** Risk gates pokrywają to dobrze (max_trades_per_day, per_hour_per_symbol, exposure limits). Plus daily loss hamulec i crash detection.

---

## PODSUMOWANIE DOJRZAŁOŚCI

| Warstwa | Dojrzałość | Komentarz |
|---|---|---|
| **Governance / control plane** | ⭐⭐⭐⭐⭐ | Kompletna — experiments, rollback, monitoring, tuning insights |
| **Risk management** | ⭐⭐⭐⭐ | 10 bram, cost-aware, kill switch. Brakuje: risk-of-ruin, portfolio-level VaR |
| **Entry logic** | ⭐⭐⭐ | Rygorystyczna, ale monolityczna. Jedna strategia. Brak alternatywnych entry modes |
| **Exit logic** | ⭐⭐⭐ | ATR-based TP/SL + trailing. Brak partial exits, brak dynamicznego ATR update |
| **Position sizing** | ⭐⭐⭐⭐ | ATR-based + multi-modifier. Solidna |
| **Execution layer** | ⭐ | DEMO only. Zero kodu live execution. Brak order management |
| **Symbol selection** | ⭐⭐ | Portfolio-based watchlist. Brak rankingu / scoringu |
| **Observability** | ⭐⭐⭐⭐ | DecisionTrace + CostLedger + ConfigSnapshot. Brak dashboardu trace |
| **Cost model** | ⭐⭐ | Szacunkowy (expected only). Brak actual measurement |
| **Multi-strategy** | ⭐ | Pole istnieje. Logika nie. Jedna strategia "demo_collector" |
| **Wskaźniki techniczne** | ⭐⭐⭐⭐ | EMA, RSI, MACD, Bollinger, ATR — pandas_ta. Poprawne |
| **Data pipeline** | ⭐⭐⭐⭐ | REST + WebSocket, multi-timeframe klines, market data. Solid |

---

## TOP 5 AKCJI — posortowane wg wpływu na PnL

| # | Akcja | Wpływ PnL | Status |
|---|---|---|---|
| 1 | ~~Migracja env vars → runtime_settings~~ | 🔴 Wysoki | ✅ P1 |
| 2 | ~~Wydzielenie _demo_trading() na metody~~ | 🟡 Średni | ✅ P2 |
| 3 | **Exit quality / MFE-MAE / partial exits** | 🔴 Wysoki | ⬜ NASTĘPNY |
| 4 | **Symbol selection / ranking netto** | 🟡 Średni | ⬜ |
| 5 | **Activity control (max trades/h, anty-overtrading)** | 🟡 Średni | ⬜ |

---

## ODPOWIEDZI NA PYTANIA A–F

### A) Czy entry logic jest wystarczająco rozbudowana?

**TAK, ale monolitycznie.** 7 warstw filtrów to dużo. Problem nie w brakach, tylko w architekturze — wszystko w jednej metodzie, jedna strategia. Rozbudowa wymaga refaktoru.

### B) Czy execution path pokrywa scenariusze live?

**NIE.** Execution layer nie istnieje. `binance_client.py` ma READ-ONLY API (tickers, balances, klines). Brak place_order, cancel_order, get_fills. Przejście na live wymaga nowego modułu.

### C) Czy warstwa strategii jest wydzielona?

**NIE.** Pole `strategy_name` istnieje, ale logika nie. Zawsze "demo_collector". Runtime setting `enabled_strategies` nie jest sprawdzana w `_demo_trading()`. Experiments framework jest gotowy na multi-strategy, ale sam silnik nie.

### D) Czy symbol selection ma jakościowy ranking?

**NIE.** Watchlist = aktywa z portfela Binance + USDT. Brak filtrowania po wolumenie, spreadzie, sile trendu. Brak priorytetyzacji.

### E) Czy runtime_settings obejmuje krytyczne parametry?

**✅ TAK (po P1).** runtime_settings pokrywa ~45 parametrów. Krytyczne parametry tradingowe (ATR mults, extreme filters, cooldowns, demo sizing) przeniesione z `os.getenv()` do `config.get()`. Widoczne dla tuning insights i experiments pipeline.

### F) Czy decision trace daje wystarczającą obserwabilność?

**TAK, na poziomie danych.** DecisionTrace zapisuje signal_summary, risk_gate_result, cost_gate_result, config_snapshot_id. Brakuje: dashboardu do przeglądania trace'ów (obecnie tylko surowy JSON w DB) i alertów na anomalie w trace patterns.

---

## WNIOSEK KOŃCOWY

> **Warstwa kontrolna (governance, risk, experiments) jest ~2x bardziej dojrzała niż rdzeń tradingowy.**
>
> Rdzeń tradingowy *działa* i ma solidne filtry wejściowe + position sizing, ale jest architektonicznie monolityczny (jedna metoda, jedna strategia, brak live execution).
>
> **Najważniejsza kolejność działań (aktualizacja 2026-03):**
> 1. ~~Migracja env vars → runtime_settings~~ ✅
> 2. ~~Refaktor _demo_trading() na osobne metody~~ ✅
> 3. Exit quality: MFE/MAE, range accuracy, partial exit analysis ← NASTĘPNY
> 4. Symbol selection: ranking netto po kosztach, blacklista
> 5. Activity control: max trades/h, cooldown per setup, anty-overtrading gate

---

*Dokument wygenerowany jako checkpoint v0.7-beta. Nie zawiera nowego kodu — tylko diagnostykę i rekomendacje.*
