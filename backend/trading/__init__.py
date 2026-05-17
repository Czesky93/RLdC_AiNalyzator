"""
backend.trading — modułowy silnik handlu Binance Spot

Warstwy logiczne:
  symbol_filter   — exchangeInfo, filtry LOT_SIZE/PRICE_FILTER/NOTIONAL/permissionSets
  signal_engine   — multi-timeframe scoring, spread, liquidity, expected-value gate
  risk_engine     — position sizing ATR, max exposure, cooldown, drawdown gate
  execution_engine — state machine per symbol, order rounding, OCO/TP/SL
  state_manager   — reconcile, orphan detection, recovery po restarcie
  trade_config    — centralny config z DB + .env
"""
