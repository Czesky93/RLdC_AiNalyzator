# CURRENT_STATE

Data: 2026-05-18 — T-154 COMPLETED
Status dokumentu: T-154 Phase 2 Step 1 — Grid Plan Building Integration DONE

---

## 🔄 LATEST: T-154 Phase 2 Step 1 — Integrate dynamic grid into collector main loop

### Objective
Connects dynamic grid plan builder to collector.py main cycle. Each `run_once()` cycle now:
1. Collects klines (1m, 15m, 1h, 4h)
2. Generates market insights/blog
3. **[NEW]** Builds/refreshes grid plans for all watchlist symbols
4. Executes demo/live trading with fresh grid plans available

### Changes Applied

**backend/collector.py** (NEW method ~1060-1150):
- `_build_dynamic_grid_plans(db: Session) -> int`:
  - Loops through `self.watchlist[:10]` (limit to 10 to avoid API overload)
  - For each symbol: fetch `get_grid_context(db, symbol)` (multi-timeframe: 15m, 1h, 4h)
  - Build plan via `build_grid_plan(db, symbol, grid_ctx, equity, config)`
  - Persist plan to RuntimeSetting via `persist_grid_plan(db, symbol, plan)`
  - Returns count of successfully built plans
  - Logs: symbol, range [lower, upper], grid_count, invest_quote
  - Graceful fallback if dynamic_grid disabled or context insufficient

**backend/collector.py** (Integration into run_once() ~7300+):
- Added call to `_build_dynamic_grid_plans(db)` after `collect_klines()`, before trading
- **Sequence**: collect_klines → insights/blog → **build_grid_plans** → demo_trading → live_trading
- Grid plans always fresh before each trading cycle

**tests/test_grid_integration.py** (NEW, 4 integration tests):
- `test_build_and_persist_grid_plan`: Build with mock context, verify DB persistence
- `test_recentering_detection`: Test recentering logic (shift_down/shift_up/none)
- `test_grid_plan_persistence_lifecycle`: Create → persist → load → update cycle
- `test_multiple_grids_per_watchlist`: Manage 3+ plans for different symbols
- **Status**: ✅ **4/4 PASSED**

### Validation
- ✅ Code compiles without errors (syntax check passed)
- ✅ Integration tests: 4/4 passing
- ✅ Full test suite: 657 passed, 25 failed (no regressions)
- ✅ Grid plans now refresh each cycle (before trading)

### Architecture Impact
- Grid plans are NOW DYNAMIC: built each cycle, always fresh
- Multiple watchlist symbols supported simultaneously (top-10)
- Plans persist across cycles for recentering checks
- Ready for **T-155**: Grid entry/exit orchestration

### Operational Status
| Component | Status | Notes |
|-----------|--------|-------|
| Grid selector (select_top_usdc_pairs) | ✅ READY | Implemented in T-152 |
| Grid builder (build_grid_plan) | ✅ READY | Implemented in T-152 |
| Grid recentering (check_recentering_needed) | ✅ READY | Implemented in T-152 |
| Grid persistence (persist/load_grid_plan) | ✅ **TESTED** | 4/4 integration tests PASS |
| Grid plan building in collector | ✅ **INTEGRATED** | Calls _build_dynamic_grid_plans() each cycle |
| Grid entry/exit orchestration | ⏳ **PENDING** | T-155 (next step) |

---

## Phase 2 Roadmap

| Task | Status | Impact |
|------|--------|--------|
| **T-154**: Integrate grid builder into main loop | ✅ DONE | Grid plans refresh each cycle |
| **T-155**: Grid entry/exit orchestration | ⏳ NEXT | Place BUY on buy_levels, manage TP/SL on sell_levels |
| **T-156**: Smoke test on testnet (N=3 pairs) | ⏳ PHASE 2+1 | Validate end-to-end before live production |

---

## Architecture: Grid.md Implementation Progress

**PHASE 1: Infrastructure (COMPLETE ✅)**
- ✅ T-150: Fix critical risk.py bug + add market data helpers
- ✅ T-151: Expand kline collection to 15m, 1h, 4h
- ✅ T-152: Create dynamic_grid.py module (selector, builder, recentering, persistence)
- ✅ T-153: Test dynamic_grid with 18 unit tests (all passing)

**PHASE 2: Integration (IN PROGRESS 🔄)**
- ✅ T-154: Integrate grid plan building into collector main loop
- ⏳ T-155: Grid entry/exit orchestration (place orders on levels, manage exits)
- ⏳ T-156: Smoke test on testnet (validate full pipeline)

**PHASE 3+: Deployment (PENDING)**
- Production grid trading with full monitoring and control

---

## Previous Sessions (Condensed)

### T-149 to T-133: Aggressive signal tuning + live trading gates
- T-149: Aggressive bypass for no_buy_signal (signal_engine accepts more candidates)
- T-148: Aggressive runtime thresholds (min_edge=-0.20, min_rr=0.70, min_confidence=0.45)
- T-147: Adaptive RR for short-term breakouts (lower RR for high-quality setups)
- T-146: Binance-style charts + enriched decision-view (indicators, forecast, BUY/SELL zones)
- T-145: Adaptive volume tiers + breakout BUY gate (dynamic volume threshold)
- T-144: BUY/SELL signal quality tuning (fix HTF threshold inconsistency)
- T-143: LIVE execution consistency + Telegram test guards (atomic claim pending, qty netto)
- T-142: LIVE SELL guard + hard exit cooldown split (cap SELL to free balance, SL not blocked by cooldown)
- T-141: Overlay recovery + chart fallback + left panel removal (fix 8099, EUR pair mapping)
- T-139: Observe-only diagnostics + spread/slippage caps + risk sizing clamp
- T-138: QuoteVolume observe-only gate + orderbook depth (dynamic volume threshold)
- T-136-T-133: Safe live-state source, request-storm guard, market health gate, reconciliation

### T-132: Market health gate + telemetry
- Collector evaluates runtime health: NO_TRADE / REDUCE_ONLY / NORMAL
- New LIVE BUY pipeline records reason_code: market_health_no_trade / market_health_reduce_only
- `/api/account/runtime-activity` and `/api/account/trading-status` expose market_health
- Telegram `/status` shows market health mode + issues
- Overlay shows trading_guard in live-state

### T-131-T-129: Runtime WWW/overlay stabilization + reconciliation fixes
- Fixed state_manager.reconcile (cfg.sync_interval_sec → reconcile_interval_sec)
- Confirmed Binance live trader with validated endpoints
- Removed stale test collection lint errors

### T-127-T-123: Watchdog stability + overlay recovery + signal engine contract fix
- Fixed watchdog restart loop with lock + grace period
- Fixed overlay 8099 (resolves chart_symbol for EUR pairs, parallel endpoint fetch)
- Fixed live signal engine: get_live_context() now returns klines_count, quote_volume, trades

### T-121-T-110: Runtime path sync + reconciliation engine
- Unified runtime paths (/home/... instead of /media/...)
- Telegram reads trading_mode from backend (not fixed value)
- Full reconciliation engine (DB ↔ Binance self-heal) with audit trail
- Execution safety gates + manual trade detection

### T-104-T-103: LIVE execution hardening + cash management + control center
- EUR↔USDC auto-conversion before BUY
- Deterministic preflight (min notional, minNotional, reason codes)
- Block test symbols in LIVE execution
- Control center: unified trading-first command parser for Telegram/manual

---

## Current Blockers & Open Tasks

| ID | Blocker | Impact | Status |
|----|---------|--------|--------|
| T-155 | Grid entry/exit not integrated | Can't execute grid trades yet | OPEN (NEXT) |
| T-156 | Testnet smoke test | Can't validate end-to-end | OPEN (PHASE 2+1) |
| T-134 | `/api/positions?mode=live` timeout | 20s+ latency | OPEN (CRITICAL) |
| T-135 | `/api/positions/analysis?mode=live` slow | Heavy per-request analysis | OPEN (CRITICAL) |
| T-136 | Overlay resilience on timeout | Falls back to last good snapshot | OPEN |
| T-122 | Panel trycloudflare rate limit | Cloudflare 1015 / 429 | BLOCKED (EXTERNAL) |

---

## Full Test Suite Status

- ✅ **657 PASSED** (test_grid_integration 4/4, test_trading_dynamic_grid 18/18)
- ⚠️ **25 FAILED** (pre-existing, not related to T-154)
- No regressions from T-154 changes

---

## Operational Runtime Status

| Component | Status | Notes |
|-----------|--------|-------|
| Backend | ✅ UP | Collector running, grid plans building |
| Frontend | ✅ UP | WWW portal stable |
| Telegram | ✅ UP | Commands responsive |
| Overlay | ✅ UP | 8099 serving live-state |
| Binance Live | ✅ CONNECTED | Orders executeable |
| Grid Engine | ✅ READY | Plans building each cycle (T-154) |
| Market Health | ✅ NOMINAL | allow_new_entries=true |

---

## Key Metrics (Post-T-154)

- **Grid Plans Built Per Cycle**: ~10 (top-N from dynamic selector)
- **Plan Persistence**: RuntimeSetting (survives restarts)
- **Recentering Logic**: Activated when position drifts > 85% or < 15% of range
- **API Impact**: +1 call per cycle to get_grid_context() per symbol (acceptable)
- **Test Coverage**: 4/4 integration tests passing
