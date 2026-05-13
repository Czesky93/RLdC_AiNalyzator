# FRONTEND_VIEW_MAP

## Active view -> komponent
- dashboard -> DashboardV2View
- dashboard-classic -> ClassicDashboardView
- execution-trace -> ExecutionTraceView
- operator-console -> DiagnosticHubView
- markets -> MarketsView
- telegram-intel -> TelegramIntelligenceView
- trade-desk -> TradeDeskView
- exit-diagnostics -> ExitDiagnosticsView
- portfolio -> PortfolioView
- strategies -> StrategiesView
- ai-signals -> SignalsView
- risk -> RiskView
- decisions -> DecisionsView
- position-analysis -> PositionAnalysisView
- backtest -> BacktestView
- economics -> EconomicsSubView (w EconomicsView)
- alerts -> AlertsSubView (w EconomicsView)
- news -> NewsSubView (w EconomicsView)
- blog -> BlogView
- settings -> SettingsView
- logs -> SettingsView (wariant logs)
- macro-reports -> PlaceholderView
- reports -> PlaceholderView

## Nawigacja
- Sidebar (główna): 12 pozycji produkcyjnych
- Topbar (skrót): markets, trade-desk, portfolio, strategies, ai-signals, risk, operator-console

## Źródła danych UI (najważniejsze)
- Centrum dowodzenia:
  - /api/account/system-status
  - /api/account/trading-status
  - /api/account/runtime-activity
  - /api/account/capital-snapshot
  - /api/portfolio/wealth
- Trade desk / pozycje / zlecenia:
  - /api/positions
  - /api/orders
  - /api/orders/pending
  - /api/positions/analysis
- Diagnostyka:
  - /api/signals/execution-trace
  - /api/account/bot-activity
  - /api/debug/state-consistency

## Status LIVE-only
- Badge w UI: LIVE — Binance
- Usunięte/wycięte guardy akcji typu mode===demo w kluczowych panelach
- Pending actions i close actions dostępne dla LIVE
