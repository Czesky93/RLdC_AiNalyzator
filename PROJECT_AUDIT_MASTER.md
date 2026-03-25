# PROJECT AUDIT MASTER

## Audit State
- Current stage: `ETAP 2 - PIPELINE DOMKNIĘTY`
- Current file: `backend/policy_layer.py`
- Last completed file: `backend/post_rollback_monitoring.py`
- Next stage: `governance / operator workflow`
- Audit timestamp: `policy layer completed, 71 tests green`
- Pipeline status: **FULL LOOP OPERATIONAL**

## Scope
This document is the single audit state file for the repository. It tracks:
- file map and module roles,
- critical, medium, and minor issues,
- implementation order,
- per-file audit status,
- baseline test status.

## Executive Summary
Repository status is closer to a trading dashboard prototype than a controlled net-PnL trading system.

Main risk factors found in the first audit pass:
- Trading logic, execution, data collection, AI insight generation, and operational workflows are coupled inside `backend/collector.py`.
- There is no unified trade cost model for fee, slippage, spread, or execution quality.
- Demo accounting ignores transaction costs, which can materially overstate performance.
- Signal endpoints auto-generate demo data, which contaminates operational truth and weakens reporting integrity.
- Persistence uses ad hoc schema mutation in application code instead of migrations.
- Project structure declared in `README.md` does not match actual repository contents.
- Test coverage is only smoke-level and does not validate trading invariants, cost controls, or risk limits.
- Runtime configuration was previously fragmented across ENV fallbacks and router-local parsing; hardened in this pass, but not yet consumed by the trading core.

## Architecture Snapshot
Current effective layers:
- `backend/`: FastAPI app, DB models, Binance client, collector, analysis, accounting, routers.
- `web_portal/`: Next.js dashboard UI.
- `telegram_bot/`: Telegram command layer.
- `docs/`: product and UI documentation.
- domain packages: `ai_trading/`, `blockchain_analysis/`, `portfolio_management/`, `recommendation_engine/` are effectively placeholders.

Missing or weak layers versus target trading architecture:
- `filters/`
- `risk/`
- `execution/`
- `portfolio/`
- `analytics/`
- `reporting/`
- `config/`
- `ai/`

## File Map

### Root
- `README.md`: high-level project description; partially inconsistent with actual repo layout.
- `requirements.txt`: Python dependencies.
- `instrukcje.txt`: auxiliary local instruction file; not yet audited.
- `log.txt`: runtime artifact, not source of truth.
- `webportalinfo`: local artifact or note; not yet audited.

### Backend
- `backend/app.py`: FastAPI bootstrap, router registration, collector startup, optional multi-process launcher.
- `backend/database.py`: SQLAlchemy engine, models, DB init, reset helpers, in-app schema patching.
- `backend/runtime_settings.py`: DB-backed runtime overrides and watchlist parsing.
- `backend/binance_client.py`: Binance REST client wrapper and helpers.
- `backend/collector.py`: market data collection, watchlist building, pending execution, AI triggers, risk alerts, learning hooks.
- `backend/analysis.py`: technical indicator calculations, signal/insight generation, blog-related AI logic.
- `backend/accounting.py`: deterministic demo account state calculation.
- `backend/auth.py`: optional admin token gate.
- `backend/system_logger.py`: DB logging helper; not yet audited deeply.
- `backend/experiments.py`: controlled comparison layer for baseline vs candidate config snapshots.
- `backend/recommendations.py`: evidence-based recommendation engine from experiment results.
- `backend/review_flow.py`: human review / approval lifecycle for recommendations.
- `backend/promotion_flow.py`: controlled promotion execution with audit trail and rollback anchor.
- `backend/post_promotion_monitoring.py`: post-deployment verdict loop for promoted configs.
- `backend/rollback_decision.py`: rollback intent layer consuming monitoring verdicts.
- `backend/rollback_flow.py`: rollback execution using same apply path as promotion.
- `backend/post_rollback_monitoring.py`: post-rollback stabilization monitoring.
- `backend/policy_layer.py`: verdict → operational action mapping with audit trail.
- `backend/reporting.py`: central reporting/analytics layer for dashboards and audit.
- `backend/__init__.py`: package marker.

### Backend Routers
- `backend/routers/market.py`: market summary, klines, ticker, orderbook APIs.
- `backend/routers/orders.py`: order history, pending order workflows, CSV export endpoints.
- `backend/routers/signals.py`: latest/top signal APIs with demo signal generation.
- `backend/routers/account.py`: demo/live account summary, DB reset, OpenAI status.
- `backend/routers/positions.py`: open positions and pending close-order creation.
- `backend/routers/control.py`: runtime control plane overrides.
- `backend/routers/blog.py`: blog API; not yet audited.
- `backend/routers/portfolio.py`: portfolio API; not yet audited.
- `backend/routers/__init__.py`: router package marker.

### Frontend
- `web_portal/`: Next.js application and dashboard widgets.
- `web_portal/src/components/` and `web_portal/src/components/widgets/`: dashboard presentation layer.
- `web_portal/src/app/`: app shell and main page.
- `web_portal/src/styles/globals.css`: global styles.
- `web_portal/package.json`, `package-lock.json`, `next.config.js`, `tailwind.config.js`, `postcss.config.js`, `tsconfig.json`: frontend build config.
- `web_portal/*.PNG`: design assets.
- `web_portal/README.md`: frontend startup notes.

### Telegram
- `telegram_bot/bot.py`: Telegram interaction layer; not yet audited.
- `telegram_bot/__init__.py`: package marker.

### Placeholder Packages
- `ai_trading/__init__.py`: placeholder.
- `blockchain_analysis/__init__.py`: placeholder.
- `portfolio_management/__init__.py`: placeholder.
- `recommendation_engine/__init__.py`: placeholder.

### Tests
- `tests/test_smoke.py`: API smoke tests for health, market, signals, orders, control state, demo close flow.

### Documentation
- `docs/PROJECT_PLAN.md`: existing high-level product plan.
- `docs/DESIGN_SYSTEM.md`: design guidelines.
- `docs/COMPONENT_LIBRARY.md`: UI component notes.
- `docs/QUICK_START.md`: setup guide.
- `docs/IMPLEMENTATION_SUMMARY.md`: implementation summary.

## Critical Problems
1. `backend/collector.py` is a god-object mixing data ingestion, signal generation, execution workflow, risk alerts, Telegram, reporting, and adaptive learning.
Impact:
- hard to reason about trade decisions,
- nearly impossible to validate edge versus costs,
- high regression risk when changing one behavior.

2. No canonical execution-cost ledger exists.
Affected areas:
- `backend/database.py`
- `backend/accounting.py`
- `backend/routers/orders.py`
- likely execution logic inside `backend/collector.py`
Impact:
- no `gross_pnl`, `net_pnl`, `fee_cost`, `slippage_cost`, `spread_cost`, `expectancy_score`,
- strategy can overtrade without detection,
- reporting can overstate performance.

3. Demo accounting excludes fees and slippage.
Affected file:
- `backend/accounting.py`
Impact:
- false-positive profitability,
- invalid comparison against live results,
- no guardrail for minimum expected edge.

4. Signal and market endpoints can synthesize demo data directly in API paths.
Affected files:
- `backend/routers/signals.py`
- possibly other endpoints via fallbacks
Impact:
- operational data pollution,
- reporting ambiguity,
- no clear separation between test fixtures and real state.

5. No explicit risk module or hard trade throttles exist in the audited core.
Missing controls from trading perspective:
- max trades per pair per hour,
- max trades per day,
- loss streak cooldown,
- daily and weekly kill switch,
- asset blacklist/whitelist,
- minimum expected move threshold.

6. Schema management is unsafe for production evolution.
Affected file:
- `backend/database.py`
Impact:
- app startup mutates schema ad hoc,
- no migration history,
- high risk of silent DB drift.

7. No config snapshot is attached to trading decisions or executions.
Impact:
- impossible to reconstruct which config produced a trade,
- weak post-mortem analysis for fee leakage and overtrading,
- no reliable walk-forward provenance.

8. Control plane and domain logic were previously mixed and had no audit trail.
Impact:
- unsafe runtime changes,
- no trace of old/new values or actor,
- high risk of destabilizing live behavior.

9. Environment bootstrap was not closed operationally.
Impact:
- tests failed before import,
- no guaranteed reproducible dev/test startup path,
- high friction for validation and CI.

## Medium Problems
1. `README.md` documents modules and subsystems that do not exist in the repository.
2. `backend/app.py` mixes API bootstrap with process orchestration for backend, Telegram, and Next.js.
3. `backend/routers/*` hold business logic instead of delegating to service modules.
4. `backend/runtime_settings.py` and `backend/routers/control.py` duplicate watchlist parsing responsibilities.
5. `backend/account.py` caches and persists demo state, but there is no centralized portfolio domain service.
6. Empty domain packages suggest planned architecture that was never wired into the running system.

## Minor Problems
1. Mixed language style across docs and code comments.
2. Runtime artifacts live in repository root.
3. Sparse typing and validation around trading invariants.
4. No explicit configuration schema or validation layer.

## Module Responsibility Map
- Data ingestion: `backend/collector.py`, `backend/binance_client.py`, `backend/routers/market.py`
- Signals and analysis: `backend/analysis.py`, `backend/routers/signals.py`
- Risk management: partially embedded in `backend/collector.py`; no dedicated module
- Execution: pending-order flow in `backend/routers/orders.py` and `backend/routers/positions.py`; live/demo execution logic appears embedded in `backend/collector.py`
- Accounting and portfolio state: `backend/accounting.py`, `backend/routers/account.py`
- Configuration and runtime control: `backend/runtime_settings.py`, `backend/routers/control.py`, environment variables
- Logging: `backend/system_logger.py`, `backend/database.py` `SystemLog`
- Backtesting: not present
- Walk-forward / out-of-sample validation: not present
- AI integration: `backend/analysis.py`, OpenAI checks in `backend/routers/account.py`
- Reporting: fragmented across routers and UI; no dedicated reporting layer

## Repair Plan
1. Audit and stabilize configuration and runtime controls.
Target files:
- `backend/runtime_settings.py`
- `backend/routers/control.py`
- `backend/app.py`

2. Isolate execution workflow from routers and collector.
Target outcome:
- dedicated execution service,
- explicit order lifecycle,
- full cost capture.

3. Introduce risk layer before any further strategy changes.
Required controls:
- trade frequency caps,
- cooldowns,
- asset filters,
- kill switches,
- minimum edge gate.

4. Replace synthetic API demo generation with explicit fixtures or seed utilities.

5. Separate analytics/reporting from signal generation and blog generation.

6. Add schema migration path and richer trade model for net-PnL accounting.

7. Expand tests from smoke to trading invariants and cost/risk validation.

## Per-File Status
Status vocabulary:
- `nieprzeanalizowany`
- `przeanalizowany`
- `wymaga poprawy`
- `poprawiony`
- `przetestowany`
- `zatwierdzony`

| File | Role | Status | Notes |
| --- | --- | --- | --- |
| `README.md` | project overview | `wymaga poprawy` | documents modules not present |
| `requirements.txt` | Python deps | `nieprzeanalizowany` | verify trading/runtime deps later |
| `instrukcje.txt` | local notes | `nieprzeanalizowany` | not part of runtime yet |
| `log.txt` | runtime artifact | `nieprzeanalizowany` | likely exclude from source control |
| `webportalinfo` | local artifact | `nieprzeanalizowany` | unclear role |
| `backend/app.py` | API bootstrap | `wymaga poprawy` | bootstrap mixed with process orchestration |
| `backend/database.py` | DB models/init | `poprawiony` | decision trace, cost ledger, net-pnl fields and DB helpers added |
| `backend/runtime_settings.py` | runtime overrides | `poprawiony` | central registry, validation, sections, guard rails, snapshot id |
| `backend/risk.py` | capital protection layer | `poprawiony` | consumes accounting/runtime, returns unified risk decisions |
| `backend/binance_client.py` | exchange client | `wymaga poprawy` | needs audit for execution-cost and reliability coverage |
| `backend/collector.py` | collector/execution/risk hub | `poprawiony` | runtime-integrated for key gates, still too broad and partially legacy-driven |
| `backend/analysis.py` | indicators/AI/blog | `wymaga poprawy` | mixed concerns, weak signal-quality gating |
| `backend/accounting.py` | demo accounting | `poprawiony` | central cost-aware metrics, rollups, consistency checks, risk/reporting inputs |
| `backend/auth.py` | admin auth | `przeanalizowany` | simple but minimal |
| `backend/system_logger.py` | DB/system logs | `nieprzeanalizowany` | inspect before refactor |
| `backend/__init__.py` | package marker | `zatwierdzony` | no action needed |
| `backend/routers/__init__.py` | package marker | `zatwierdzony` | no action needed |
| `backend/routers/market.py` | market API | `wymaga poprawy` | fallback logic and sourcing need cleanup |
| `backend/routers/orders.py` | order API | `wymaga poprawy` | lacks cost model and service separation |
| `backend/routers/signals.py` | signals API | `wymaga poprawy` | demo-data generation in production path |
| `backend/routers/account.py` | account API | `wymaga poprawy` | mixed live/demo and ops diagnostics |
| `backend/routers/positions.py` | positions API | `wymaga poprawy` | pending close flow only, no risk layer |
| `backend/routers/control.py` | control plane API | `poprawiony` | thin HTTP delegation, audit trail response, live guard enforcement |
| `backend/routers/blog.py` | blog API | `nieprzeanalizowany` | inspect later |
| `backend/routers/portfolio.py` | portfolio API | `nieprzeanalizowany` | inspect later |
| `backend/policy_layer.py` | policy verdict→action | `poprawiony` | deterministic mappings, audit trail, supersede semantics |
| `tests/test_smoke.py` | smoke tests | `przetestowany` | 71 tests (54 base + 17 policy layer) |
| `telegram_bot/bot.py` | Telegram bot | `nieprzeanalizowany` | inspect after execution layer |
| `telegram_bot/__init__.py` | package marker | `zatwierdzony` | no action needed |
| `ai_trading/__init__.py` | placeholder package | `wymaga poprawy` | architecture placeholder only |
| `blockchain_analysis/__init__.py` | placeholder package | `wymaga poprawy` | architecture placeholder only |
| `portfolio_management/__init__.py` | placeholder package | `wymaga poprawy` | architecture placeholder only |
| `recommendation_engine/__init__.py` | placeholder package | `wymaga poprawy` | architecture placeholder only |
| `docs/PROJECT_PLAN.md` | project plan | `nieprzeanalizowany` | compare against actual code later |
| `docs/DESIGN_SYSTEM.md` | design system | `nieprzeanalizowany` | not trading-critical |
| `docs/COMPONENT_LIBRARY.md` | UI docs | `nieprzeanalizowany` | not trading-critical |
| `docs/QUICK_START.md` | setup docs | `nieprzeanalizowany` | validate after backend audit |
| `docs/IMPLEMENTATION_SUMMARY.md` | implementation notes | `nieprzeanalizowany` | validate against repo state |
| `web_portal/package.json` | frontend deps | `nieprzeanalizowany` | frontend dependency audit pending |
| `web_portal/next.config.js` | Next config | `nieprzeanalizowany` | |
| `web_portal/postcss.config.js` | PostCSS config | `nieprzeanalizowany` | |
| `web_portal/tailwind.config.js` | Tailwind config | `nieprzeanalizowany` | user has local modifications |
| `web_portal/tsconfig.json` | TS config | `nieprzeanalizowany` | |
| `web_portal/src/app/layout.tsx` | app shell | `nieprzeanalizowany` | |
| `web_portal/src/app/page.tsx` | main page | `nieprzeanalizowany` | |
| `web_portal/src/components/*.tsx` | dashboard components | `nieprzeanalizowany` | inspect after backend stabilization |
| `web_portal/src/components/widgets/*.tsx` | widget components | `nieprzeanalizowany` | inspect after backend stabilization |
| `web_portal/src/styles/globals.css` | global styles | `nieprzeanalizowany` | user has local modifications |
| `web_portal/README.md` | frontend docs | `nieprzeanalizowany` | |

## Baseline Test Status
- Test suite selected: `tests/test_smoke.py`
- Current expectation: should pass if demo mode boots cleanly with collector disabled
- Initial blocker: system environment missing `fastapi`, and `python` alias is absent
- Resolution:
  - created isolated virtual environment: `.venv`
  - installed dependencies from `requirements.txt`
  - executed tests via `.venv/bin/pytest`
- Final result: `passed`
- Command executed: `.venv/bin/pytest tests/test_smoke.py`
- Outcome: `12 passed`
- Residual warning debt:
  - widespread `datetime.utcnow()` deprecations
  - SQLAlchemy `declarative_base()` deprecation path
  - pytest-asyncio loop-scope warning

## Bootstrap Notes
- Recommended developer bootstrap:
  - `python3 -m venv .venv`
  - `.venv/bin/python -m pip install --upgrade pip`
  - `.venv/bin/python -m pip install -r requirements.txt`
  - `.venv/bin/pytest tests/test_smoke.py`
- Current dependency observation:
  - `requirements.txt` already includes runtime and test packages
  - missing split between runtime and dev/test dependencies remains a medium-priority cleanup item
- Minimal future improvement:
  - keep `requirements.txt` for runtime
  - add `requirements-dev.txt` layering test/lint tooling on top
  - add one environment sanity test for interpreter + dependencies

## File Review: backend/runtime_settings.py
Status: `poprawiony`

### Role
Central runtime configuration registry, ENV/DB resolution, validation, live guard rails, config snapshot generation, and change audit trail generation.

### Current problems
- Prior version only handled a few booleans and watchlist override.
- No typed schema for trading, risk, execution, or cost settings.
- No cross-field validation.
- No live guard rails.
- No config snapshot id.
- No change audit trail.

### Business impact
- Runtime settings now provide a controlled surface for later split of risk/execution/cost services.
- Reduces chance of accidental revenue leakage caused by unsafe runtime edits.

### Trading impact
- Adds explicit knobs for mode, activity limits, cooldowns, drawdown limits, and strategy enablement.
- Adds live-mode blockers when prerequisites are not met.

### Cost impact
- Adds explicit config for maker/taker fees, slippage, spread buffer, min edge multiplier, and minimum notional.
- This does not yet price trades, but it removes ambiguity in where those constraints belong.

### Risk if unchanged
- Without this hardening, later work on `collector.py` would still depend on fragmented and weakly validated settings.

### Dependencies
- `backend/routers/control.py`
- future consumers: `backend/collector.py`, execution/risk services, analytics/reporting

### Test status
- `passed` indirectly via `tests/test_smoke.py`

### Notes
- Next improvement should propagate `config_snapshot_id` into order/trade decision records.

## File Review: backend/routers/control.py
Status: `poprawiony`

### Role
HTTP control plane adapter for reading and updating runtime configuration.

### Current problems
- Prior version duplicated watchlist parsing and built state locally.
- No audit trail in API response.
- No protection against unsafe live changes during open positions.
- Router contained configuration assembly logic instead of delegating.

### Business impact
- Safer runtime operations reduce the probability of destabilizing production behavior during parameter changes.

### Trading impact
- Control updates now respect open-position guard rails for critical live settings.
- Live mode activation is blocked when required safety conditions are not met.

### Cost impact
- Cost-related knobs can now be updated through one validated interface instead of ad hoc changes.

### Risk if unchanged
- Unsafe live toggles and missing audit history would keep operational risk high and make post-incident analysis weak.

### Dependencies
- `backend/runtime_settings.py`
- `backend/database.py`
- `backend/accounting.py`

### Test status
- `passed` via `tests/test_smoke.py`

### Notes
- Control plane is thinner now, but the trading core still does not consume most of the new settings.

## File Review: backend/collector.py
Status: `poprawiony`

### Role
Runtime orchestrator for watchlist refresh, market ingestion, kline ingestion, AI/blog trigger, demo execution flow, mark-to-market, and demo trade decision flow.

### Current problems
- Still mixes data ingestion, decision logic, risk throttling, execution preparation, and adaptive parameter tuning.
- Still relies on multiple legacy ENV fallbacks for ATR multipliers, AI freshness, crash detection, and demo sizing details.
- Demo state remains mutable local memory, not persisted or synchronized across processes.
- Cost model is still heuristic, not backed by executed net-PnL schema.

### Business impact
- Collector now stops inventing its own core activity/risk/cost limits for the main decision gates.
- Decision traces make post-trade analysis materially easier.

### Trading impact
- Entry gating now consumes central settings for mode, max open positions, max trades per day, cooldown, loss streak, risk per trade, daily drawdown, min notional, and cost threshold.
- Pending execution now respects runtime trading mode instead of raw ENV.

### Cost impact
- Collector now applies a cost-aware gate using taker fee, slippage, spread buffer, min edge multiplier, and minimum expected RR before creating pending orders.
- This is still a pre-trade heuristic gate, not a full realized cost ledger.

### Risk if unchanged
- Without the remaining split, collector will continue to be hard to test and reason about under live conditions.
- Local mutable state and legacy fallbacks can still diverge from central configuration.

### Dependencies
- `backend/runtime_settings.py`
- `backend/analysis.py`
- `backend/accounting.py`
- `backend/database.py`
- future extraction targets: risk service, execution service, decision-trace persistence

### Test status
- `passed` via `.venv/bin/pytest tests/test_smoke.py`

### Notes
- This pass preserves behavior where possible and removes dual-source truth for critical guards, but does not yet fully separate strategy from orchestration.

## File Review: backend/database.py
Status: `poprawiony`

### Role
Primary persistence layer for market data, orders, positions, runtime state, and now decision tracing plus cost accounting.

### Current problems
- Still uses application-side schema mutation instead of real migrations.
- Order remains the nearest proxy for a trade lifecycle; there is still no dedicated trade aggregate.
- Realized net-PnL persistence is now possible, but not yet fully populated across all order entry/exit paths outside collector demo execution.

### Business impact
- System can now persist why a trade was blocked or executed, not only that it happened.
- Enables leakage analysis and net-PnL measurement per order.

### Trading impact
- Decisions, costs, and configuration snapshots are linkable.
- Creates a durable substrate for later risk gating and performance analytics by asset/setup.

### Cost impact
- Fee, slippage, and spread are now structurally separable in `cost_ledger`.
- `orders` and `positions` can now hold `gross_pnl`, `net_pnl`, `total_cost`, and cost breakdowns.

### Risk if unchanged
- Without further integration into remaining order paths, analytics would still be skewed toward collector-driven flows only.
- Lack of migrations still keeps production upgrade risk elevated.

### Dependencies
- `backend/collector.py`
- future: `backend/accounting.py`, reporting endpoints, risk layer, analytics layer

### Test status
- `passed` via `.venv/bin/pytest tests/test_smoke.py`

### Notes
- Next step should propagate net-PnL and cost usage into accounting/reporting instead of leaving it only on raw records.

## File Review: backend/accounting.py
Status: `poprawiony`

### Role
Central accounting source of truth for net-PnL definitions, order/position rollups, symbol/strategy/day summaries, blocked-decision summaries, and risk snapshot inputs.

### Current problems
- Still uses current DB schema without a dedicated config snapshot payload table.
- Some metrics remain approximate where source data is not yet normalized, especially strategy linkage outside decision traces.
- Existing routers outside accounting may still expose raw unrealized values directly instead of accounting rollups.

### Business impact
- System now has one place that defines net economics instead of multiple ad hoc implementations.
- Enables consistent leakage, expectancy, and profit-factor calculations.

### Trading impact
- Daily net PnL, loss streak, and exposure can now be derived from a stable accounting layer.
- Risk layer can consume net-aware metrics instead of rebuilding them from raw orders.

### Cost impact
- Fee/slippage/spread are aggregated consistently from `cost_ledger` and order fields.
- `compute_demo_account_state(...)` is now cost-aware rather than gross-only.

### Risk if unchanged
- If downstream layers bypass accounting, the project will drift back to multiple incompatible metric definitions.

### Dependencies
- `backend/database.py`
- `backend/collector.py`
- `backend/routers/account.py`
- future: risk service, reporting endpoints, analytics layer

### Test status
- `passed` via `.venv/bin/pytest tests/test_smoke.py`

### Notes
- Accounting should remain the only place that defines `net_pnl`, `cost_leakage_ratio`, `net_expectancy`, and `profit_factor_net`.

## File Review: backend/risk.py
Status: `poprawiony`

### Role
Central capital-protection layer that consumes accounting rollups and runtime limits, then returns unified risk decisions for trading candidates.

### Current problems
- Some risk-related behavior still remains in collector as legacy local state, especially pending cooldown and crash-mode adjustments.
- Risk persistence still relies on decision trace payloads rather than a dedicated normalized risk-events table.

### Business impact
- Capital protection is no longer encoded as scattered boolean checks inside collector only.
- Global and symbol-level loss controls now have one decision surface.

### Trading impact
- Collector can consume one risk decision with action, reason codes, limit breaches, and size multiplier.
- `/api/account/risk` now reads the accounting risk snapshot instead of recomputing drawdown locally.

### Cost impact
- Leakage and net expectancy are now first-class risk inputs rather than optional diagnostics.

### Risk if unchanged
- If remaining collector-local risk logic is not migrated, two partial risk regimes will continue to coexist.

### Dependencies
- `backend/accounting.py`
- `backend/runtime_settings.py`
- `backend/collector.py`
- `backend/routers/account.py`

### Test status
- `passed` via `.venv/bin/pytest tests/test_smoke.py`

### Notes
- Next step should remove remaining legacy risk branches from collector and route reporting through accounting/risk outputs.

## Database Extensions
- New tables:
  - `decision_traces`
  - `cost_ledger`
- Extended tables:
  - `orders`
  - `positions`
  - `pending_orders`
- New persistence helpers:
  - `save_decision_trace(...)`
  - `save_cost_entry(...)`
  - `attach_costs_to_order(...)`
  - `load_order_cost_summary(...)`

## Data Layer Impact
- Audit:
  - blocked and executed decisions are now persistable outside generic logs
  - config snapshot linkage is stored on traces and economic records
- Risk:
  - decision trace can now store gate outcomes and reason codes for later blocker analysis
- Analytics:
  - order-level fee/slippage/spread rollups are possible
  - leakage per symbol and cost type is now derivable
- Net PnL:
  - orders and positions can now store gross and net economics instead of only raw execution data

## Accounting Metrics
- Implemented definitions:
  - `gross_pnl`
  - `net_pnl`
  - `total_cost`
  - `fee_cost`
  - `slippage_cost`
  - `spread_cost`
  - `expected_edge`
  - `realized_rr`
  - `cost_leakage_ratio`
  - `net_expectancy`
  - `profit_factor_net`
- Implemented rollups:
  - order: `compute_order_cost_summary(...)`
  - position: `position_cost_summary(...)`
  - day: `compute_daily_performance(...)`
  - symbol: `compute_symbol_performance(...)`
  - strategy: `compute_strategy_performance(...)`
- Reporting inputs:
  - `cost_breakdown_by_symbol(...)`
  - `blocked_decisions_summary(...)`
- Risk inputs:
  - `compute_risk_snapshot(...)`
  - cost-aware `compute_demo_account_state(...)`

## Risk Gate Inventory
- `daily_net_drawdown_gate`
  - source metric: `compute_risk_snapshot().daily_net_drawdown`
  - source config field: `max_daily_drawdown`
  - action on breach: `block_temporarily`
  - reason code: `daily_net_drawdown_gate`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `loss_streak_gate`
  - source metric: `compute_risk_snapshot().loss_streak_net`
  - source config field: `loss_streak_limit`
  - action on breach: `block_temporarily`
  - reason code: `loss_streak_gate`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `max_open_positions_gate`
  - source metric: `compute_risk_snapshot().open_positions_count`
  - source config field: `max_open_positions`
  - action on breach: `block_temporarily`
  - reason code: `max_open_positions_gate`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `activity_gate_day`
  - source metric: `compute_activity_snapshot().trades_24h`
  - source config field: `max_trades_per_day`
  - action on breach: `block_temporarily`
  - reason code: `activity_gate_day`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `activity_gate_symbol_hour`
  - source metric: `compute_activity_snapshot().by_symbol_1h`
  - source config field: `max_trades_per_hour_per_symbol`
  - action on breach: `block_symbol`
  - reason code: `activity_gate_symbol_hour`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `exposure_gate_total`
  - source metric: `compute_risk_snapshot().total_exposure`
  - source config field: `max_total_exposure_ratio`
  - action on breach: `block_temporarily`
  - reason code: `exposure_gate_total`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `exposure_gate_symbol`
  - source metric: `compute_risk_snapshot().exposure_per_symbol`
  - source config field: `max_symbol_exposure_ratio`
  - action on breach: `block_symbol`
  - reason code: `exposure_gate_symbol`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `leakage_gate_symbol`
  - source metric: `compute_symbol_performance().cost_leakage_ratio`
  - source config field: `max_cost_leakage_ratio`
  - action on breach: `block_symbol`
  - reason code: `leakage_gate_symbol`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `expectancy_gate_symbol`
  - source metric: `compute_symbol_performance().net_expectancy`
  - source config field: `min_symbol_net_expectancy`
  - action on breach: `block_symbol`
  - reason code: `expectancy_gate_symbol`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `expectancy_gate_strategy`
  - source metric: `compute_strategy_performance().net_expectancy`
  - source config field: `min_symbol_net_expectancy`
  - action on breach: `block_strategy`
  - reason code: `expectancy_gate_strategy`
  - persistence status: decision trace ready
  - integrated with collector: `yes`
- `kill_switch_gate`
  - source metric: `compute_risk_snapshot().kill_switch_triggered`
  - source config field: `kill_switch_enabled`
  - action on breach: `trigger_kill_switch`
  - reason code: `kill_switch_gate`
  - persistence status: decision trace ready
  - integrated with collector: `yes`

## Critical Priority Update
- Critical: without routing risk and reporting through `backend/accounting.py`, the system risks reintroducing multiple incompatible definitions of net PnL, drawdown, leakage, and expectancy.

## Remaining Data Gaps
- No standalone `trade_performance` aggregate yet.
- Non-collector order creation paths still do not fully populate economic fields.
- Reporting is centralized, but account history/KPI endpoints still expose snapshot-style account views rather than config-aware analytics rollups.
- Risk-at-decision metrics are stored in traces only as JSON payloads, not normalized dimensions.
- Some API endpoints still expose raw `unrealized_pnl` or direct DB sums instead of accounting rollups.
- Pending-order cooldown and crash-mode risk branches still live in collector, outside centralized `risk.py`.

## Legacy Logic Inventory: backend/collector.py
- Local thresholds:
  - `DEMO_MIN_SIGNAL_CONFIDENCE`
  - `DEMO_MAX_SIGNAL_AGE_SECONDS`
  - `DEMO_MIN_KLINES`
  - `EXTREME_RANGE_MARGIN_PCT`
  - `EXTREME_MIN_CONFIDENCE`
  - `EXTREME_MIN_RATING`
- Local activity caps:
  - `PENDING_ORDER_COOLDOWN_SECONDS`
- Local cooldowns:
  - `CRASH_COOLDOWN_SECONDS`
  - in-memory per-symbol `demo_state["cooldown"]`
- Local risk gates:
  - ATR stop/take/trail multipliers
  - crash detection thresholds
  - adaptive `symbol_params` calibration
- Local fee assumptions:
  - none as hardcoded fee rates anymore for primary entry gate
  - realized execution costs still not persisted in schema
- Local signal overrides:
  - blog-derived AI range gating
  - extreme-entry filter
  - crash-mode confidence override
- Implicit mode behavior:
  - DEMO-only execution path
  - SELL without shorting
  - local in-memory streak handling

## Collector Migration Status
- Source of truth migrated:
  - `trading_mode`
  - `demo_trading_enabled`
  - `max_certainty_mode`
  - `max_open_positions`
  - `max_trades_per_day`
  - `cooldown_after_loss_streak_minutes`
  - `loss_streak_limit`
  - `risk_per_trade`
  - `max_daily_drawdown`
  - `max_weekly_drawdown`
  - `maker_fee_rate`
  - `taker_fee_rate`
  - `slippage_bps`
  - `spread_buffer_bps`
  - `min_edge_multiplier`
  - `min_expected_rr`
  - `min_order_notional`
- Legacy fallback still present:
  - ATR-based stop/take/trail multipliers
  - crash detection params
  - AI staleness thresholds
  - demo min/max qty
  - min signal confidence fallback
- Needs removal:
  - dual logic around watchlist refresh cadence and collector-local state
  - in-memory `demo_state` for streak/cooldown
  - `symbol_params` adaptive tuning inside collector
- Behavior preserved / behavior changed:
  - preserved: demo trading flow, pending confirmation workflow, AI/blog dependency, no-shorting demo policy
  - changed: entries now require centralized cost gate and min notional gate; critical throttles now come from runtime settings

## Open Risks
- Existing uncommitted frontend changes are present and must not be overwritten during backend audit.
- Current repository mixes prototype/demo behaviors with operational endpoints, so audit findings may reveal hidden assumptions in UI flows.
- Cost and expectancy controls cannot be implemented safely until order and position schemas are extended.
- Trading core still ignores most newly formalized runtime parameters.
- Control-plane audit trail is currently stored in generic `SystemLog`, not a dedicated immutable audit table.
- Collector still owns too much mutable local state and strategy-specific fallback logic.
- Schema evolution is still managed by ad hoc `ALTER TABLE` logic instead of migrations.
- Config snapshot ids exist, but snapshot payloads are not yet persisted in a dedicated table.
- Risk and reporting layers are not yet fully rewired to consume accounting as their only financial source of truth.
- Risk is centralized for primary entry gates, but not yet for every legacy protective branch in collector.

## Next Actions
- Propagate validated settings into `backend/collector.py` and future risk/execution services.
- Inspect `backend/system_logger.py`, `backend/routers/portfolio.py`, and `backend/routers/blog.py` to close file map gaps.
- Start execution/cost-model refactor with config snapshot attached to decisions.
- Extend schema for realized cost fields and decision-trace persistence beyond generic logs.
- Integrate `cost_ledger` and `net_pnl` into `backend/accounting.py` and reporting surfaces.
- Rewire risk layer to consume `compute_risk_snapshot(...)` and accounting rollups only.
- Rewire remaining account snapshot/KPI views to distinguish clearly between operational account state and analytics source-of-truth payloads.
- Remove remaining collector-local risk fallbacks and expose risk decisions in reporting/analytics.

## File: backend/runtime_settings.py
Status: corrected

### Role
- Central source of truth for runtime configuration, validation, guard rails, and now persisted config snapshot generation.

### Current problems
- Snapshot persistence now exists, but `build_runtime_state(...)` still performs persistence on read paths, which may be too eager for high-frequency polling.
- Snapshot payloads do not yet include external environment provenance beyond normalized effective config values.
- Historical account KPI endpoints are still separate from config-aware performance comparisons.

### Impact on trading
- Every decision path can now resolve `config_snapshot_id` to the exact effective config payload used at the time.
- Makes before/after config analysis possible without guessing which limits or cost assumptions were active.

### Impact on costs
- Cost and edge controls are now traceable back to the exact fee/slippage/spread settings that produced them.

### Required fixes
- Consider decoupling snapshot persistence from pure read operations if polling overhead becomes material.
- Add environment/bootstrap provenance if startup source attribution becomes important.

### Dependencies
- `backend/database.py`
- `backend/reporting.py`
- `backend/collector.py`
- `backend/routers/control.py`

### Test status
- passed via smoke tests

### Notes
- Snapshot payload now includes full config sections plus effective watchlist and watchlist source.
- Snapshot chain uses `previous_snapshot_id` and persisted `changed_fields`.

## File: backend/database.py
Status: corrected

### Role
- Database source of truth for persisted facts, now extended with immutable-ish `config_snapshots`.

### Current problems
- Schema migration is still ad hoc and not a replacement for real migrations.
- Referential integrity between `config_snapshot_id` columns and `config_snapshots.id` is logical, not enforced via foreign keys.

### Impact on trading
- Decisions, orders, positions, pending orders, and reporting can now resolve runtime config context exactly.

### Impact on costs
- Makes leakage and net performance comparable across config versions instead of only across symbols/strategies.

### Required fixes
- Add stronger referential guarantees once migrations are introduced.
- Consider indexes/retention policy if snapshot volume grows.

### Dependencies
- `backend/runtime_settings.py`
- `backend/reporting.py`
- `tests/test_smoke.py`

### Test status
- passed via smoke tests

### Notes
- Added `config_snapshots` table, helpers for save/load/list/compare, and schema ensure hooks.

## Config Snapshot Payload Storage
- Table: `config_snapshots`
  - fields: `id`, `created_at`, `config_hash`, `payload_json`, `source`, `changed_fields_json`, `previous_snapshot_id`, `notes`, `is_current`
- Hash generation:
  - `id`: short sha256 over canonical payload
  - `config_hash`: full sha256 over canonical payload
- Payload contents:
  - full `sections` tree from runtime settings
  - effective `watchlist`
  - `watchlist_source`
- Link model:
  - `orders.config_snapshot_id`
  - `positions.config_snapshot_id`
  - `pending_orders.config_snapshot_id`
  - `decision_traces.config_snapshot_id`
  - `cost_ledger.config_snapshot_id`
- Comparison readiness:
  - snapshot payload fetch by id
  - snapshot catalog listing
  - snapshot-to-snapshot diff with changed field paths
  - reporting enrichment with payload metadata and config-based performance grouping

## File: backend/experiments.py
Status: corrected

### Role
- Controlled comparison and experiment layer for baseline vs candidate config snapshots.

### Current problems
- Verdict logic is intentionally conservative and heuristic; it is not yet statistically aware.
- Experiment scope currently supports `mode`, `symbol`, `strategy_name`, and date range, but not portfolio-segment or regime labels.
- Results are stored as JSON payloads; there is no normalized fact table for long-horizon experiment analytics yet.

### Impact on trading
- Enables controlled before/after evaluation of config changes without jumping straight to auto-tuning.
- Prevents “more turnover” from being mistaken for a genuine improvement when net PnL/expectancy do not improve.

### Impact on costs
- Makes leakage and cost-aware tradeoffs explicit at experiment verdict time.
- Supports comparing whether stricter risk/cost settings improved net results or merely reduced activity.

### Required fixes
- Add statistical confidence / sample-size checks before any automated promotion of candidate configs.
- Extend scope vocabulary beyond global/symbol/strategy/date once experiment volume grows.
- Add regime-aware grouping before controlled auto-tuning starts making recommendations.

### Dependencies
- `backend/database.py`
- `backend/accounting.py`
- `backend/reporting.py`
- `backend/routers/account.py`

### Test status
- passed via smoke tests

### Notes
- Added `experiments` and `experiment_results` tables.
- Verdict outputs: `candidate`, `baseline`, `inconclusive`.
- Reason codes include net-PnL, drawdown, leakage, expectancy, and turnover-only warnings.

## Comparison / Experiments Layer
- Models:
  - `experiments`
  - `experiment_results`
- Supported scopes:
  - overall/global
  - per symbol
  - per strategy
  - per date range
  - per trading mode
- Compared metrics:
  - `gross_pnl`
  - `net_pnl`
  - `total_cost`
  - `cost_leakage_ratio`
  - `profit_factor_net`
  - `net_expectancy`
  - `drawdown_net`
  - `win_rate_net`
  - `blocked_decisions`
  - `risk_actions_count`
  - `trade_count`
- Decision policy:
  - `candidate` wins only if it improves `net_pnl`, preserves or improves `net_expectancy`, and does not materially worsen drawdown
  - `baseline` wins when candidate degrades net result, drawdown, and expectancy together
  - otherwise result is `inconclusive`

## File: backend/recommendations.py
Status: corrected

### Role
- Conservative recommendation engine translating experiment evidence into operational suggestions without auto-applying config changes.

### Current problems
- Confidence is heuristic, not statistically calibrated.
- Recommendation history is stored as JSON-rich rows, not normalized for large-scale meta-analysis.
- No review/approval workflow exists yet; recommendations stop at `open`.

### Impact on trading
- Prevents premature promotion of configs that improve turnover or win rate without improving net economics.
- Creates an auditable bridge from experiment evidence to human review.

### Impact on costs
- Explicitly downgrades candidates that worsen leakage or risk actions without compensating net improvement.
- Highlights parameter changes behind recommendations, making cost-sensitive settings easier to review.

### Required fixes
- Add review/approval state transitions before any controlled auto-tuning.
- Add sample-size and statistical significance logic before allowing high-confidence promotion.
- Add cross-experiment parameter ranking once more experiments accumulate.

### Dependencies
- `backend/experiments.py`
- `backend/database.py`
- `backend/routers/account.py`

### Test status
- passed via smoke tests

### Notes
- Recommendation types: `promote`, `reject`, `watch`, `needs_more_data`, `rollback_candidate`.
- Each recommendation stores confidence, reason codes, parameter changes, net-effect summary, and risk-effect summary.

## Recommendation Layer
- Model:
  - `recommendations`
- Recommendation types:
  - `promote`
  - `reject`
  - `watch`
  - `needs_more_data`
  - `rollback_candidate`
- Confidence model:
  - heuristic score based on net delta, expectancy delta, sample size, and experiment verdict
  - intentionally conservative; reduced for `watch` and `needs_more_data`
- Explainability inputs:
  - experiment verdict and reason codes
  - config diff changed fields
  - net effect summary
  - risk/leakage effect summary
- Auto-tuning readiness:
  - recommendation evidence is now persisted, but still requires external review/approval before any config promotion

## File: backend/review_flow.py
Status: corrected

### Role
- Human review / approval lifecycle for recommendations before any config promotion.

### Current problems
- Review stops at approval state; there is still no controlled promotion execution.
- Superseding is conservative and currently limited to open sibling recommendations with the same baseline/candidate pair.
- Reviewer identity is stored as plain text; no richer operator model exists yet.

### Impact on trading
- Adds a hard human gate between recommendation evidence and any future operational action.
- Prevents conflicting review decisions and preserves a durable audit trail of who approved, rejected, or deferred a change.

### Impact on costs
- Keeps cost-sensitive config changes from being promoted implicitly without explicit human sign-off.
- Makes it possible to defer suspicious low-sample improvements instead of overreacting to noise.

### Required fixes
- Add controlled promotion flow as a separate stage after approval.
- Extend supersede logic to broader recommendation families if experiment volume grows.
- Introduce reviewer identity/auth metadata beyond free-form strings when operational governance becomes stricter.

### Dependencies
- `backend/recommendations.py`
- `backend/database.py`
- `backend/routers/account.py`

### Test status
- passed via smoke tests

### Notes
- Lifecycle states now include `open`, `under_review`, `approved`, `rejected`, `deferred`, `superseded`, `expired`.
- Approval does not change runtime config; it only marks recommendation as promotion-ready for a later stage.

## Review / Approval Flow
- Review model:
  - `recommendation_reviews`
- Supported decisions:
  - `start_review`
  - `approve`
  - `reject`
  - `defer`
- Guard rails:
  - no review without existing recommendation
  - no approve/reject/defer from terminal states
  - no review bundle without experiment and snapshot context
  - promotion readiness only after explicit `approved`
- Review bundle contents:
  - recommendation
  - experiment summary
  - verdict
  - snapshot diff
  - changed params
  - net effect summary
  - risk effect summary
  - confidence
  - reason codes

## File: backend/promotion_flow.py
Status: corrected

### Role
- Controlled promotion service applying an approved snapshot to runtime configuration with audit trail and rollback anchor.

### Current problems
- Rollback execution exists, but post-rollback monitoring is still only a hook/state placeholder.
- Promotion currently requires current active snapshot to match approved baseline exactly, which is safe but conservative.
- Post-promotion monitoring exists, but repeated warning/rollback patterns still need explicit policy handling.

### Impact on trading
- Introduces the first controlled path that can change runtime behavior based on approved optimization results.
- Prevents silent or duplicate promotions and preserves `from -> to` lineage.

### Impact on costs
- Ensures cost-sensitive config changes are promoted only after approval and with explicit audit metadata.
- Supports later monitoring of whether promoted settings improved leakage or only changed turnover.

### Required fixes
- Add post-rollback monitoring and rollback policy handling for repeated `warning` or `rollback_candidate` verdicts.
- Consider drift-tolerant promotion policy if active runtime diverges slightly from baseline for benign reasons.

### Dependencies
- `backend/runtime_settings.py`
- `backend/review_flow.py`
- `backend/recommendations.py`
- `backend/routers/account.py`

### Test status
- passed via smoke tests

### Notes
- Promotion statuses: `pending`, `applied`, `failed`, `rolled_back`, `cancelled` planned; currently exercised `pending`, `applied`, `failed`.
- Successful promotion initializes post-promotion monitoring and stores rollback anchor.

## Controlled Promotion Flow
- Model:
  - `config_promotions`
- Guard rails:
  - approved review required
  - `promotion_ready=true` required
  - candidate snapshot must exist
  - duplicate `pending/applied` promotion for same recommendation blocked
  - active runtime snapshot must match approved baseline
  - failures persist audit trail with reason
- Stored audit fields:
  - `from_snapshot_id`
  - `to_snapshot_id`
  - `review_id`
  - `initiated_by`
  - `validation_summary_json`
  - `runtime_apply_result_json`
  - `rollback_snapshot_id`
  - `post_promotion_monitoring_status`

## File: backend/post_promotion_monitoring.py
Status: corrected

### Role
- Post-promotion monitoring service evaluating whether a promoted snapshot remains healthy after deployment, using cost-aware accounting and risk outputs instead of ad hoc runtime heuristics.

### Current problems
- Monitoring is still pull-based; there is no scheduler or periodic evaluation worker yet.
- Rollback can now be decided, executed, and evaluated after rollback, but there is still no higher-level escalation policy spanning both monitoring layers.
- Minimum sample and time gates are controlled by environment variables rather than central runtime settings.

### Impact on trading
- Adds an explicit post-deployment verdict loop so promoted configs are judged by real net results, not only experiment expectations.
- Makes it possible to distinguish between a healthy promotion, an inconclusive rollout, and a rollout that materially worsens capital protection.

### Impact on costs
- Detects post-promotion cost leakage drift and flags cases where a new config increases trading costs without sufficient net benefit.
- Compares observed results against baseline cost-aware summaries before any rollback decision is considered.

### Required fixes
- Move monitoring thresholds into central runtime settings once rollout governance is extended.
- Add escalation / intervention policy consuming promotion and rollback monitoring lineage together.
- Add expiry/escalation rules for promotions that remain stuck in `collecting` or `watch`.

### Dependencies
- `backend/promotion_flow.py`
- `backend/experiments.py`
- `backend/recommendations.py`
- `backend/database.py`
- `backend/routers/account.py`

### Test status
- passed via smoke tests

### Notes
- Monitoring statuses:
  - `pending`
  - `collecting`
  - `healthy`
  - `watch`
  - `warning`
  - `rollback_candidate`
- Current reason codes include:
  - `POST_PROMOTION_SAMPLE_TOO_SMALL`
  - `POST_PROMOTION_TIME_WINDOW_TOO_SHORT`
  - `POST_PROMOTION_NET_PNL_DEGRADATION`
  - `POST_PROMOTION_DRAWDOWN_WORSE`
  - `POST_PROMOTION_COST_LEAKAGE_HIGH`
  - `POST_PROMOTION_RISK_ACTIONS_INCREASED`
  - `POST_PROMOTION_EXPECTANCY_DOWN`

## Post-Promotion Monitoring
- Model:
  - `promotion_monitoring`
- Audit fields:
  - `promotion_id`
  - `from_snapshot_id`
  - `to_snapshot_id`
  - `status`
  - `baseline_reference_summary_json`
  - `observed_summary_json`
  - `deviation_summary_json`
  - `reason_codes_json`
  - `rollback_recommended`
  - `min_trade_count_gate_passed`
  - `min_time_window_gate_passed`
  - `confidence`
  - `evaluation_version`
- Guard rails:
  - no monitoring evaluation before promotion reaches `applied`
  - no strong verdict before minimal sample/time gates pass
  - verdicts compare promoted snapshot against baseline and observed window, not raw runtime noise
  - rollback is only recommended at this stage, never auto-executed

## File: backend/reporting.py
Status: corrected

### Role
- Central reporting and analytics layer for performance overview, symbol/strategy/day breakdowns, blocked decisions, cost leakage, risk effectiveness, and config-snapshot grouping.

### Current problems
- Config payloads are persisted, but reporting still lacks richer before/after views combining snapshot payload diff with promotion and rollback lineage in one place.
- Daily reporting derives blocked counts from traces and cost totals from ledger, but does not yet expose weekly/monthly windows.
- Routers still expose legacy account snapshot endpoints alongside analytics endpoints, which can confuse downstream consumers if not clearly separated.

### Impact on trading
- Makes net performance, blocked decisions, and risk actions visible without duplicating financial logic in routers.
- Enables symbol/strategy pruning based on real cost-aware outputs instead of raw turnover.

### Impact on costs
- Surfaces fee/slippage/spread leakage per symbol and per cost type.
- Exposes whether risk gates are reducing leakage or merely throttling volume.

### Required fixes
- Add promotion/rollback-lineage-aware reporting once rollback execution exists.
- Extend reporting windows beyond daily once risk/report consumers need regime comparisons.
- Migrate remaining summary/KPI endpoints to use reporting vocabulary consistently.

### Dependencies
- `backend/accounting.py`
- `backend/risk.py`
- `backend/database.py`
- `backend/routers/account.py`
- `backend/routers/portfolio.py`

### Test status
- passed via smoke tests

### Notes
- `backend/routers/account.py` now delegates analytics endpoints to `backend/reporting.py`.
- `backend/routers/portfolio.py` now derives cost-aware summary fields from `summarize_positions(...)` while preserving response compatibility.

## File: backend/rollback_decision.py
Status: corrected

### Role
- Rollback decision layer consuming post-promotion monitoring verdicts and translating them into auditable rollback intent without applying runtime configuration changes.

### Current problems
- Decision records now feed execution, but there is still no post-rollback monitoring lifecycle after execution.
- Monitoring thresholds feeding rollback remain partly controlled by ENV rather than central runtime settings.
- Latest decision is promotion-scoped and monitoring-scoped, but there is no execution-aware lifecycle yet.

### Impact on trading
- Adds a formal safety checkpoint between monitoring verdicts and any future rollback action.
- Prevents ad hoc rollback interpretation by forcing explicit statuses: `no_action`, `continue_monitoring`, `rollback_recommended`, `rollback_required`.

### Impact on costs
- Makes rollback pressure visible when promoted configs degrade net PnL, leakage, drawdown, or risk behavior.
- Avoids overreacting to tiny samples by keeping low-sample cases in `continue_monitoring`.

### Required fixes
- Add post-rollback monitoring and execution-aware lifecycle transitions after rollback completes.
- Move monitoring sample/time thresholds into central runtime settings.
- Extend rollback policy with retry/cancel semantics only if operationally required.

### Dependencies
- `backend/post_promotion_monitoring.py`
- `backend/promotion_flow.py`
- `backend/database.py`
- `backend/routers/account.py`

### Test status
- passed via smoke tests

### Notes
- Current decision statuses:
  - `no_action`
  - `continue_monitoring`
  - `rollback_recommended`
  - `rollback_required`
- Current rollback reason codes include:
  - `ROLLBACK_NO_ACTION_HEALTHY`
  - `ROLLBACK_CONTINUE_MONITORING`
  - `ROLLBACK_MONITORING_WARNING_PERSISTENT`
  - `ROLLBACK_NET_PNL_DEGRADATION`
  - `ROLLBACK_DRAWDOWN_BREACH`
  - `ROLLBACK_COST_LEAKAGE_BREACH`
  - `ROLLBACK_RISK_ACTIONS_SURGE`
  - `ROLLBACK_EXPECTANCY_DETERIORATION`
  - `ROLLBACK_SAMPLE_TOO_SMALL`
  - `ROLLBACK_TIME_WINDOW_TOO_SHORT`

## Rollback Decision
- Model:
  - `config_rollbacks`
- Guard rails:
  - no rollback decision without existing promotion and monitoring record
  - no rollback decision when promotion lacks `rollback_snapshot_id`
  - no local economics recalculation; monitoring verdict is the source of truth
  - low-sample cases default to `continue_monitoring` unless monitoring already shows a stronger breach state
- Stored audit fields:
  - `promotion_id`
  - `monitoring_id`
  - `decision_source`
  - `decision_status`
  - `from_snapshot_id`
  - `to_snapshot_id`
  - `rollback_snapshot_id`
  - `validation_summary_json`
  - `rollback_reason_codes_json`
  - `urgency`

## File: backend/rollback_flow.py
Status: corrected

### Role
- Rollback execution flow applying an already-approved rollback decision through the same runtime update path used by promotions, with full audit trail and drift detection.

### Current problems
- Post-rollback monitoring exists, but there is still no escalation policy after a failed stabilization verdict.
- Execution currently blocks on runtime drift instead of offering an operator-mediated override path.
- Rollback execution is single-shot; retry/cancel policy is not yet modeled beyond `pending`, `executed`, `failed`.

### Impact on trading
- Completes the operational safety loop by enabling the system to revert from a degraded promoted config to the previous snapshot.
- Prevents hidden rollback paths by forcing all config reversal through the same guarded runtime apply mechanism.

### Impact on costs
- Limits cost leakage and degraded expectancy persistence by making rollback executable once monitoring and rollback decision align.
- Preserves visibility into whether rollback happened because of net PnL deterioration, drawdown pressure, leakage, or risk-action surge.

### Required fixes
- Add escalation policy over post-rollback monitoring verdicts.
- Decide whether failed rollback executions can be retried safely or must require a new decision record.
- Move drift override policy into an explicit review/approval step if operators need manual exceptions.

### Dependencies
- `backend/rollback_decision.py`
- `backend/promotion_flow.py`
- `backend/runtime_settings.py`
- `backend/database.py`
- `backend/routers/account.py`

### Test status
- passed via smoke tests

### Notes
- Execution statuses:
  - `pending`
  - `executed`
  - `failed`
  - `cancelled` planned
- Rollback execution reuses the same config apply path as promotion via `apply_runtime_updates(...)`.
- Drift is treated as a hard failure with preserved audit trail; no silent overwrite is allowed.

## Rollback Execution
- Shared apply path:
  - `backend/promotion_flow.py`
  - `backend/runtime_settings.py`
  - `apply_runtime_updates(...)`
- Guard rails:
  - no execution without existing rollback decision
  - only `rollback_recommended` or `rollback_required` decisions are executable
  - no execution without `rollback_snapshot_id`
  - duplicate execution attempts are blocked once `execution_status != pending`
  - runtime drift is detected and stored as failure
  - post-rollback monitoring is initialized after successful execution and evaluated separately
- Stored audit fields:
  - `execution_status`
  - `executed_at`
  - `failed_at`
  - `validation_summary_json`
  - `runtime_apply_result_json`
  - `failure_reason`
  - `post_rollback_monitoring_status`

## File: backend/post_rollback_monitoring.py
Status: corrected

### Role
- Post-rollback monitoring service evaluating whether a rollback actually stabilized the system after config reversion, using the same accounting/risk/reporting-derived metrics as the rest of the safety pipeline.

### Current problems
- Monitoring is still pull-based; there is no scheduler or automatic reevaluation loop yet.
- Thresholds for sample/time gates remain in environment variables instead of central runtime settings.
- Verdicts stop at `escalate`; there is still no policy layer telling the operator or system what intervention should follow.

### Impact on trading
- Closes the safety loop by showing whether rollback restored a healthier regime or whether degradation persists after config reversion.
- Distinguishes between successful stabilization, inconclusive recovery, and cases where rollback was insufficient.

### Impact on costs
- Confirms whether rollback actually reduces leakage and risk pressure instead of only reverting parameters.
- Makes persistent post-rollback cost/risk degradation visible for later escalation policy.

### Required fixes
- Move post-rollback monitoring thresholds into central runtime settings.
- Add escalation policy / operator workflow for `warning` and `escalate`.
- Consider a shared monitoring orchestration layer if promotion and rollback monitoring start to need scheduled reevaluation.

### Dependencies
- `backend/rollback_flow.py`
- `backend/experiments.py`
- `backend/database.py`
- `backend/routers/account.py`

### Test status
- passed via smoke tests

### Notes
- Post-rollback monitoring statuses:
  - `pending`
  - `collecting`
  - `stabilized`
  - `watch`
  - `warning`
  - `escalate`
- Current reason codes include:
  - `POST_ROLLBACK_SAMPLE_TOO_SMALL`
  - `POST_ROLLBACK_TIME_WINDOW_TOO_SHORT`
  - `POST_ROLLBACK_NET_PNL_RECOVERED`
  - `POST_ROLLBACK_NET_PNL_STILL_WEAK`
  - `POST_ROLLBACK_DRAWDOWN_IMPROVED`
  - `POST_ROLLBACK_DRAWDOWN_STILL_HIGH`
  - `POST_ROLLBACK_LEAKAGE_IMPROVED`
  - `POST_ROLLBACK_LEAKAGE_STILL_HIGH`
  - `POST_ROLLBACK_RISK_PRESSURE_REDUCED`
  - `POST_ROLLBACK_RISK_PRESSURE_PERSISTENT`

## Post-Rollback Monitoring
- Model:
  - `rollback_monitoring`
- Guard rails:
  - no evaluation before rollback reaches `executed`
  - no strong verdict before minimal sample/time gates pass
  - observed period is compared against pre-rollback summary and rollback target snapshot
  - no automatic action is taken from `warning` or `escalate`
- Stored audit fields:
  - `rollback_id`
  - `promotion_id`
  - `from_snapshot_id`
  - `to_snapshot_id`
  - `pre_rollback_summary_json`
  - `observed_summary_json`
  - `deviation_summary_json`
  - `reason_codes_json`
  - `min_trade_count_gate_passed`
  - `min_time_window_gate_passed`
  - `confidence`

## Checklist
- [x] Repository scan completed
- [x] Critical backend modules identified
- [x] Initial project map created
- [x] Problem severity list created
- [x] Repair order proposed
- [x] Baseline tests executed
- [x] First file-level refactor completed
- [x] Policy layer implemented and tested

## File: backend/policy_layer.py
Status: corrected

### Role
- Operational policy layer mapping existing verdicts from promotion monitoring, rollback decision, and post-rollback monitoring into deterministic operational actions with audit trail.

### Architectural position
- Consumes:
  - `promotion_monitoring` verdicts
  - `rollback_decision` verdicts (via `config_rollbacks`)
  - `rollback_monitoring` verdicts
- Does NOT:
  - calculate PnL, drawdown, leakage, or expectancy
  - execute promotions, rollbacks, or config changes
  - duplicate logic from `review_flow`, `promotion_flow`, `rollback_flow`, or `risk.py`

### Policy actions
- `NO_ACTION` — system healthy, no intervention needed
- `CONTINUE_MONITORING` — keep observing, no immediate action
- `REQUIRE_MANUAL_REVIEW` — human must assess before proceeding
- `PREPARE_ROLLBACK` — rollback should be prepared
- `FREEZE_PROMOTIONS` — block new promotions while incident is active
- `FREEZE_EXPERIMENTS` — block new experiments while incident is active
- `ESCALATE_TO_OPERATOR` — critical situation, operator must intervene
- `CLOSE_INCIDENT` — system has stabilized, incident resolved

### Deterministic verdict → action mappings

#### Promotion monitoring
| Verdict | Action | Priority |
|---|---|---|
| `healthy` | `NO_ACTION` | low |
| `pending` / `collecting` | `CONTINUE_MONITORING` | low |
| `watch` | `CONTINUE_MONITORING` | medium |
| `warning` | `REQUIRE_MANUAL_REVIEW` | high |
| `rollback_candidate` | `PREPARE_ROLLBACK` | critical |

#### Rollback decision
| Verdict | Action | Priority |
|---|---|---|
| `no_action` | `NO_ACTION` | low |
| `continue_monitoring` | `CONTINUE_MONITORING` | from urgency |
| `rollback_recommended` | `PREPARE_ROLLBACK` | high |
| `rollback_required` | `ESCALATE_TO_OPERATOR` | critical |

#### Post-rollback monitoring
| Verdict | Action | Priority |
|---|---|---|
| `stabilized` | `CLOSE_INCIDENT` | low |
| `pending` / `collecting` | `CONTINUE_MONITORING` | low |
| `watch` | `CONTINUE_MONITORING` | medium |
| `warning` | `REQUIRE_MANUAL_REVIEW` | high |
| `escalate` | `ESCALATE_TO_OPERATOR` | critical |

### Freeze and permission flags per action
- Each policy action carries operational flags:
  - `requires_human_review`
  - `promotion_allowed`
  - `rollback_allowed`
  - `experiments_allowed`
  - `freeze_recommendations`
- Higher-severity actions progressively freeze promotions, experiments, and recommendations.

### Supersede semantics
- New policy action for the same `source_type + source_id` automatically supersedes any previous `open` action.
- Superseded actions get `status=superseded` and a link to the replacing action.
- Manual close via `resolve_policy_action(...)` sets `status=resolved`.

### Impact on trading
- Gives the system a structured operational response vocabulary instead of ad hoc human interpretation of monitoring verdicts.
- Creates the substrate for later governance / operator workflow decisions.

### Impact on costs
- Does not calculate costs; relies entirely on upstream verdicts that already account for leakage and net economics.

### Required fixes
- Add governance / operator workflow layer above policy actions.
- Move monitoring thresholds from ENV into central runtime settings.
- Add scheduled reevaluation of stale open policy actions.

### Dependencies
- `backend/database.py` (model `PolicyAction`)
- `backend/routers/account.py` (thin endpoints)

### Test status
- passed via smoke tests: **71 tests total (54 original + 17 policy layer)**

### Notes
- Public API:
  - `evaluate_policy(...)` — pure function, no DB
  - `create_policy_action(...)` — evaluate + persist + supersede
  - `resolve_policy_action(...)` — manual close
  - `get_policy_action(...)` — single record read
  - `list_policy_actions(...)` — filtered list
  - `list_active_policy_actions(...)` — open actions sorted by priority
  - `policy_actions_summary(...)` — dashboard aggregate

### Endpoints
- `GET /api/account/analytics/policy-actions` — lista z filtrami `status`, `source_type`
- `GET /api/account/analytics/policy-actions/active` — otwarte akcje (critical first)
- `GET /api/account/analytics/policy-actions/summary` — podsumowanie do dashboardu
- `GET /api/account/analytics/policy-actions/{id}` — pojedynczy rekord
- `POST /api/account/analytics/policy-actions` — tworzenie (admin)
- `POST /api/account/analytics/policy-actions/{id}/resolve` — zamknięcie (admin)

## Policy Layer
- Model:
  - `policy_actions`
- Guard rails:
  - deterministic mapping only, no ad hoc economics
  - supersede on new verdict for same source
  - resolve only from `open` state
  - unknown source_type → ValueError
- Stored audit fields:
  - `source_type`
  - `source_id`
  - `policy_action`
  - `priority`
  - `requires_human_review`
  - `promotion_allowed`
  - `rollback_allowed`
  - `experiments_allowed`
  - `freeze_recommendations`
  - `summary`
  - `reason_codes_json`
  - `status`
  - `resolved_at`
  - `superseded_by`

## Complete Pipeline Status
Full safety loop is now operational end-to-end:

```
config → experiment → recommendation → review → promotion
  → post-promotion monitoring → rollback decision
  → rollback execution → post-rollback monitoring → policy
```

Each layer consumes the previous layer's verdicts. No layer recalculates economics independently.

## Next Recommended Stage: Governance / Operator Workflow
- Who can approve which actions
- Incident queue management
- Freeze enforcement across pipeline
- Incident lifecycle (open → acknowledged → in_progress → resolved)
- Operator notification hooks
