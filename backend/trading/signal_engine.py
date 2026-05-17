"""
signal_engine.py — Multi-timeframe scoring sygnałów wejścia Binance Spot.

Architektura:
  1. Zbiera wskaźniki z 3 timeframe'ów: fast (15m), entry (1h), htf (4h)
  2. Sprawdza spread rynkowy (bid/ask) — blokuje entry przy zbyt szerokim spread
  3. Liczy liquidity score (wolumen, liczba transakcji)
  4. Liczy złożony EntryScore (0.0–1.0) z 6 komponentów
  5. Weryfikuje expected value po kosztach — NIE wchodzimy bez pozytywnego edge

Każda decyzja opisana jest reason_code + details (dla DecisionTrace).

Użycie:
    from backend.trading.signal_engine import evaluate_entry_signal
    result = evaluate_entry_signal(db, symbol, cfg, meta)
    if result.is_valid:
        # użyj result.score, result.confidence, result.entry_price ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class EntrySignalResult:
    """Wynik oceny sygnału wejścia."""

    symbol: str
    is_valid: bool                       # True = wchodzić (wszystkie filtry ok)
    reason_code: str = ""                # jeśli is_valid=False: powód odrzucenia
    reason_pl: str = ""                  # opis po polsku (dla Telegram/WWW)

    # Złożone score'y
    score: float = 0.0                   # złożony entry score (0.0–1.0)
    confidence: float = 0.0             # pewność sygnału (0.0–1.0)

    # Komponenty score (dla transparency / debug)
    trend_score: float = 0.0
    momentum_score: float = 0.0
    volume_score: float = 0.0
    liquidity_score: float = 0.0
    regime_score: float = 0.0
    htf_agreement_score: float = 0.0

    # Ceny i koszty
    entry_price: float = 0.0
    atr: float = 0.0
    spread_pct: float = 0.0
    expected_move_pct: float = 0.0       # ATR/price * 100
    expected_net_edge_pct: float = 0.0  # expected_move - round_trip_cost
    total_cost_pct: float = 0.0

    # Diagnoza
    details: Dict[str, Any] = field(default_factory=dict)
    skip_reasons: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.is_valid:
            return (
                f"VALID {self.symbol} score={self.score:.3f} "
                f"conf={self.confidence:.3f} edge={self.expected_net_edge_pct:.3f}%"
            )
        return f"SKIP {self.symbol} reason={self.reason_code}"


_REASON_PL = {
    "no_klines_data": "Brak danych klines dla symbolu",
    "insufficient_klines": "Za mało klines — niewystarczające dane historyczne",
    "no_atr": "Brak ATR — nie można wyliczyć poziomów TP/SL",
    "no_price": "Brak aktualnej ceny — pobieranie danych nieudane",
    "spread_too_wide": "Spread bid/ask zbyt szeroki — wejście nieopłacalne",
    "volume_below_trade_threshold": "Quote volume poniżej progu handlowego — tylko obserwacja",
    "volume_too_low": "Wolumen zbyt niski — ryzyko braku płynności",
    "orderbook_depth_too_low": "Głębokość order booka zbyt mała — ryzyko poślizgu",
    "liquidity_too_low": "Niski wskaźnik płynności — zbyt mały market",
    "no_buy_signal": "Brak sygnału BUY — warunki techniczne niespełnione",
    "confidence_too_low": "Pewność sygnału poniżej progu",
    "score_too_low": "Złożony score wejścia poniżej progu",
    "negative_edge_after_costs": "Ujemny edge po kosztach — wejście nieopłacalne",
    "htf_trend_disagrees": "Trend wyższego interwału (4h) nie potwierdza wejścia",
    "rsi_overbought": "RSI wskazuje wykupienie — zbyt późne wejście",
    "signal_too_old": "Sygnał wygasł — za stary",
    "hold_mode": "Symbol w trybie HOLD — nowe wejścia zablokowane",
}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v or 0.0)))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _compute_trend_score(
    ema_20: Optional[float],
    ema_50: Optional[float],
    ema_200: Optional[float],
    price: float,
) -> float:
    """
    Trend score (0.0–1.0):
      - EMA20 > EMA50 > EMA200 = silny uptrend (1.0)
      - EMA20 > EMA50 = umiarkowany uptrend (0.7)
      - EMA20 < EMA50 = downtrend (0.2)
      - Brak danych = neutralny (0.45)
    """
    e20 = _safe_float(ema_20)
    e50 = _safe_float(ema_50)
    e200 = _safe_float(ema_200)

    if e20 <= 0 or e50 <= 0:
        return 0.45

    if e200 > 0 and e20 > e50 and e50 > e200 and price > e200:
        return 1.0
    if e20 > e50:
        if e200 > 0 and e50 > e200:
            return 0.85
        return 0.65
    if e20 < e50 * 0.99:  # wyraźny downtrend
        return 0.15
    return 0.35  # EMA20 ≈ EMA50 — chop


def _compute_momentum_score(
    rsi: Optional[float],
    macd_hist: Optional[float],
    macd_signal: Optional[float],
) -> float:
    """
    Momentum score (0.0–1.0):
      - Łączy RSI i MACD histogram
      - Optymalny zakres RSI dla BUY: 45–65 (wchodzenie w trwa trend, nie na szczycie)
      - RSI < 30: oversold (potencjalny reversal, ale ryzykowne)
      - RSI > 70: overbought → kara (-0.3)
      - MACD hist > 0: bonus +0.2
    """
    rsi_v = _safe_float(rsi, 50.0)
    hist = _safe_float(macd_hist, 0.0)
    sig = _safe_float(macd_signal, 0.0)

    # RSI component (0.0–1.0)
    if 45.0 <= rsi_v <= 65.0:
        rsi_score = 1.0
    elif 35.0 <= rsi_v < 45.0 or 65.0 < rsi_v <= 70.0:
        rsi_score = 0.65
    elif rsi_v < 35.0:
        rsi_score = 0.4  # oversold — może być szansa, ale ryzykowne
    elif rsi_v > 70.0:
        rsi_score = max(0.0, 1.0 - (rsi_v - 70.0) / 30.0 * 2.0)  # kara za overbought
    else:
        rsi_score = 0.5

    # MACD histogram component
    if hist > 0 and hist > sig * 0.1:
        macd_score = 1.0  # momentum rosnący
    elif hist > 0:
        macd_score = 0.65
    elif hist < 0:
        macd_score = 0.2  # momentum spadający
    else:
        macd_score = 0.45

    # Połącz 60% RSI + 40% MACD
    return _clamp01(rsi_score * 0.6 + macd_score * 0.4)


def _compute_volume_score(
    volume_ratio: Optional[float],
    volume_spike_ratio: Optional[float],
) -> float:
    """
    Volume score (0.0–1.0):
      - volume_ratio = bieżący wolumen / średni 20-período
      - volume_spike_ratio = max wolumen 20-período / avg
      - Wolumen > 1.5× średniej = potwierdzone zainteresowanie rynku (1.0)
      - Wolumen < 0.8× = słabo aktywny (0.3)
    """
    ratio = _safe_float(volume_ratio, 1.0)
    spike = _safe_float(volume_spike_ratio, ratio)

    base = min(1.0, ratio / 1.5)  # normalizacja do 1.5x

    # Bonus za spike (nagłe pojawienie się wolumenu)
    spike_bonus = 0.0
    if spike > 2.5:
        spike_bonus = 0.15
    elif spike > 2.0:
        spike_bonus = 0.08

    raw = base + spike_bonus
    return _clamp01(raw)


def _compute_liquidity_score(
    volume_24h_quote: Optional[float],
    trade_count_1h: Optional[float],
    spread_pct: float,
    min_volume_24h: float = 100_000.0,
    min_trades_1h: float = 100.0,
) -> float:
    """
    Liquidity score (0.0–1.0):
      - volume_24h_quote: dzienny obrót w quote currency (USDC/EUR)
      - trade_count_1h: liczba transakcji w ostatniej 1h
      - spread_pct: bieżący spread bid/ask
    """
    vol_score = 0.0
    if volume_24h_quote and volume_24h_quote > 0:
        vol_score = _clamp01(volume_24h_quote / (min_volume_24h * 2))

    trades_score = 0.0
    if trade_count_1h and trade_count_1h > 0:
        trades_score = _clamp01(trade_count_1h / (min_trades_1h * 2))

    # Spread kara: im szerszy spread, tym niższy liquidity score
    spread_penalty = 0.0
    if spread_pct > 0:
        if spread_pct >= 0.5:
            spread_penalty = 0.5
        elif spread_pct >= 0.2:
            spread_penalty = spread_pct / 0.5 * 0.3
        elif spread_pct >= 0.1:
            spread_penalty = 0.1

    raw = vol_score * 0.5 + trades_score * 0.5 - spread_penalty
    return _clamp01(raw)


def _compute_regime_score(
    bb_position: Optional[float],
    rsi: Optional[float],
    bb_width: Optional[float],
) -> float:
    """
    Regime score (0.0–1.0):
      - bb_position: (price - lower_band) / (upper_band - lower_band), 0–1
      - bb_width: (upper_band - lower_band) / middle_band — szerokość pasma
      - Wchodzimy najlepiej gdy bb_position jest w dolnej połowie (nie na szczycie)
      - Szerokie pasma = wysoka zmienność (dobre dla momentum)
      - Wąskie pasma = kompresja (czekamy na breakout)
    """
    pos = _safe_float(bb_position, 0.5)
    bb_w = _safe_float(bb_width, 0.04)
    rsi_v = _safe_float(rsi, 50.0)

    # Pozycja w paśmie Bollingera (0.0 = na dolnym pasmie, 1.0 = na górnym)
    # Optymalne wejście BUY: 0.2–0.6 (środek-dolna połowa)
    if 0.15 <= pos <= 0.55:
        pos_score = 1.0
    elif pos < 0.15:
        pos_score = 0.6  # silnie wyprzedany
    elif 0.55 < pos <= 0.75:
        pos_score = 0.55
    else:
        pos_score = 0.2  # przy górnym pasmie — nie wchodzimy

    # Szerokość pasma (czekamy na volę > 3%)
    if bb_w > 0.05:
        width_score = 1.0
    elif bb_w > 0.03:
        width_score = 0.7
    elif bb_w > 0.015:
        width_score = 0.4
    else:
        width_score = 0.2  # squeeze — brak trendu

    return _clamp01(pos_score * 0.6 + width_score * 0.4)


def _compute_htf_agreement(
    htf_ema_20: Optional[float],
    htf_ema_50: Optional[float],
    htf_rsi: Optional[float],
    price: float,
) -> float:
    """
    Potwierdzenie trendu wyższego interwału (4h):
      - 1.0 = mocny uptrend 4h
      - 0.5 = brak danych
      - 0.0 = downtrend 4h (blokuje wejście)
    """
    e20 = _safe_float(htf_ema_20)
    e50 = _safe_float(htf_ema_50)
    rsi_4h = _safe_float(htf_rsi, 50.0)

    if e20 <= 0 or e50 <= 0:
        return 0.5  # brak danych — neutralny

    if e20 > e50 and rsi_4h > 50:
        if rsi_4h > 60:
            return 1.0
        return 0.8
    if e20 > e50:
        return 0.6  # trend up ale RSI osłabiony
    if e20 < e50 * 0.98:  # wyraźny downtrend
        return 0.1
    return 0.35  # chop


def _get_spread_pct(binance_client, symbol: str) -> float:
    """
    Pobierz aktualny spread bid/ask z Binance bookTicker.
    Zwraca 0.0 jeśli danych brak.
    """
    try:
        ticker = binance_client.get_book_ticker(symbol)
        if ticker:
            bid = _safe_float(ticker.get("bidPrice"))
            ask = _safe_float(ticker.get("askPrice"))
            if bid > 0 and ask > 0:
                return (ask - bid) / bid * 100.0
    except Exception:
        pass
    return 0.0


def _effective_quote_volume_trade_threshold(cfg, volume_ratio: float, spread_pct: float) -> float:
    """
    Wyznacza dynamiczny próg quoteVolume dla realnego trade.

    Gdy `use_dynamic_volume_threshold` jest aktywne, próg obniża się
    wraz ze wzrostem potwierdzenia wolumenu i rośnie przy szerszym spreadzie.
    """
    base_threshold = _safe_float(getattr(cfg, "min_quote_volume_trade", 0.0), 0.0)
    if base_threshold <= 0:
        return 0.0

    if not bool(getattr(cfg, "use_dynamic_volume_threshold", True)):
        return base_threshold

    volume_ratio_min = max(_safe_float(getattr(cfg, "volume_ratio_min", 1.0), 1.0), 0.1)
    volume_boost = max(1.0, _safe_float(volume_ratio, 1.0) / volume_ratio_min)
    spread_bps = max(0.0, spread_pct * 100.0)
    spread_penalty = 1.0 + min(spread_bps, 100.0) / 200.0
    return base_threshold * spread_penalty / volume_boost


def _get_orderbook_depth_ratio(
    binance_client,
    symbol: str,
    price: float,
    depth_bps: float,
    min_buy_notional: float,
) -> Tuple[float, float]:
    """
    Zwraca (depth_ratio, quote_depth).

    Liczymy tylko ask-side depth w pobliżu mid, bo dla wejścia BUY to on
    najszybciej przekłada się na koszt poślizgu.
    """
    if not binance_client or price <= 0 or depth_bps <= 0:
        return 0.0, 0.0

    try:
        orderbook = binance_client.get_orderbook(symbol, limit=20)
        asks = (orderbook or {}).get("asks") or []
        if not asks:
            return 0.0, 0.0

        max_ask_price = price * (1.0 + depth_bps / 10000.0)
        quote_depth = 0.0
        for ask_price, ask_qty in asks:
            price_v = _safe_float(ask_price)
            qty_v = _safe_float(ask_qty)
            if price_v <= 0 or qty_v <= 0:
                continue
            if price_v > max_ask_price:
                continue
            quote_depth += price_v * qty_v

        depth_ratio = quote_depth / max(1.0, min_buy_notional)
        return depth_ratio, quote_depth
    except Exception:
        return 0.0, 0.0


def evaluate_entry_signal(
    db: Session,
    symbol: str,
    cfg,                          # TradeConfig
    meta=None,                    # SymbolMeta (opcjonalne — do spread check)
    binance_client=None,          # do bookTicker / avg_price
    external_confidence: Optional[float] = None,  # z AI provider
) -> EntrySignalResult:
    """
    Główna funkcja oceny sygnału wejścia.

    Kroki:
      1. Pobierz wskaźniki z 3 timeframes (fast, entry, htf)
      2. Sprawdź spread
      3. Oblicz 6 komponentów score
      4. Sprawdź hard gates (volume, liquidity, htf, RSI overbought)
      5. Sprawdź expected value po kosztach
      6. Zwróć EntrySignalResult

    Args:
        db:                   Session bazy danych
        symbol:               symbol np. 'BTCUSDC'
        cfg:                  TradeConfig
        meta:                 SymbolMeta z symbol_filter
        binance_client:       do bookTicker
        external_confidence:  confidence z AI/ML (jeśli None → liczymy heurystycznie)
    """
    from backend.analysis import get_live_context

    result = EntrySignalResult(symbol=symbol, is_valid=False)

    # ── 1. Pobierz wskaźniki ──────────────────────────────────────────────
    entry_tf = cfg.entry_timeframe      # 1h
    htf_tf = cfg.htf_timeframe          # 4h
    fast_tf = cfg.fast_timeframe        # 15m

    try:
        ctx_entry = get_live_context(db, symbol, timeframe=entry_tf, limit=200) or {}
    except Exception as exc:
        logger.debug("evaluate_entry_signal: get_live_context(%s,%s) error: %s", symbol, entry_tf, exc)
        ctx_entry = {}

    try:
        ctx_htf = get_live_context(db, symbol, timeframe=htf_tf, limit=100) or {}
    except Exception:
        ctx_htf = {}

    try:
        ctx_fast = get_live_context(db, symbol, timeframe=fast_tf, limit=100) or {}
    except Exception:
        ctx_fast = {}

    if not ctx_entry:
        result.reason_code = "no_klines_data"
        result.reason_pl = _REASON_PL["no_klines_data"]
        return result

    # Sprawdź minimalną liczbę klines
    klines_count = _safe_float(ctx_entry.get("klines_count"), 200 if ctx_entry else 0)
    if klines_count < 50:
        result.reason_code = "insufficient_klines"
        result.reason_pl = _REASON_PL["insufficient_klines"]
        result.details["klines_count"] = klines_count
        return result

    # ATR (obowiązkowe — bez ATR nie możemy obliczyć TP/SL)
    atr = _safe_float(ctx_entry.get("atr"))
    if atr <= 0:
        result.reason_code = "no_atr"
        result.reason_pl = _REASON_PL["no_atr"]
        return result

    # Cena bieżąca
    price = _safe_float(ctx_entry.get("close") or ctx_entry.get("price"))
    if price <= 0:
        result.reason_code = "no_price"
        result.reason_pl = _REASON_PL["no_price"]
        return result

    result.atr = atr
    result.entry_price = price

    # ── 2. Spread bid/ask ────────────────────────────────────────────────
    spread_pct = 0.0
    if binance_client:
        spread_pct = _get_spread_pct(binance_client, symbol)
    result.spread_pct = spread_pct

    max_spread_bps = _safe_float(getattr(cfg, "max_spread_bps", 0.0), 0.0)
    if max_spread_bps <= 0 and _safe_float(getattr(cfg, "max_allowed_spread_pct", 0.0), 0.0) > 0:
        max_spread_bps = _safe_float(getattr(cfg, "max_allowed_spread_pct", 0.0), 0.0) * 100.0
    if max_spread_bps > 0 and spread_pct * 100.0 > max_spread_bps:
        result.reason_code = "spread_too_wide"
        result.reason_pl = _REASON_PL["spread_too_wide"]
        result.details["spread_pct"] = round(spread_pct, 4)
        result.details["spread_bps"] = round(spread_pct * 100.0, 4)
        result.details["max_spread_bps"] = round(max_spread_bps, 4)
        return result

    spread_bps = spread_pct * 100.0
    max_slippage_bps = _safe_float(getattr(cfg, "max_slippage_bps", 0.0), 0.0)
    if max_slippage_bps > 0 and spread_bps > max_slippage_bps:
        result.reason_code = "spread_too_wide"
        result.reason_pl = _REASON_PL["spread_too_wide"]
        result.details["spread_bps"] = round(spread_bps, 4)
        result.details["max_slippage_bps"] = max_slippage_bps
        return result

    # ── 3. Komponenty score ───────────────────────────────────────────────
    ema_20 = ctx_entry.get("ema_20")
    ema_50 = ctx_entry.get("ema_50")
    ema_200 = ctx_entry.get("ema_200")
    rsi = ctx_entry.get("rsi")
    macd_hist = ctx_entry.get("macd_histogram") or ctx_entry.get("macd_hist")
    macd_sig = ctx_entry.get("macd_signal")
    volume_ratio = ctx_entry.get("volume_ratio")
    volume_spike = ctx_entry.get("volume_spike_ratio")
    bb_upper = ctx_entry.get("bb_upper")
    bb_lower = ctx_entry.get("bb_lower")
    bb_mid = ctx_entry.get("bb_middle") or ctx_entry.get("bb_mid")
    quote_volume_24h = _safe_float(ctx_entry.get("volume_24h_quote") or ctx_entry.get("quote_volume"))
    trades_1h = _safe_float(ctx_entry.get("trade_count") or ctx_entry.get("num_trades"))
    volume_ratio_v = _safe_float(volume_ratio, 1.0)

    result.details.update({
        "quote_volume_24h": round(quote_volume_24h, 4),
        "spread_pct": round(spread_pct, 4),
        "spread_bps": round(spread_bps, 4),
        "trade_count_1h": round(trades_1h, 4),
        "volume_ratio": round(volume_ratio_v, 4),
    })

    market_block: Optional[Tuple[int, str, str, Dict[str, Any]]] = None

    def _mark_market_block(priority: int, reason_code: str, details: Dict[str, Any]) -> None:
        nonlocal market_block
        candidate = (priority, reason_code, _REASON_PL[reason_code], details)
        if market_block is None or priority < market_block[0]:
            market_block = candidate

    # Pozycja w pasmie Bollingera
    bb_pos = None
    bb_width = None
    if bb_upper and bb_lower and bb_mid and price > 0:
        band_range = _safe_float(bb_upper) - _safe_float(bb_lower)
        if band_range > 0:
            bb_pos = (price - _safe_float(bb_lower)) / band_range
            bb_width = band_range / _safe_float(bb_mid)

    trend_score = _compute_trend_score(ema_20, ema_50, ema_200, price)
    momentum_score = _compute_momentum_score(rsi, macd_hist, macd_sig)
    volume_score = _compute_volume_score(volume_ratio, volume_spike)

    effective_min_quote_volume_trade = _effective_quote_volume_trade_threshold(
        cfg,
        volume_ratio=volume_ratio_v,
        spread_pct=spread_pct,
    )

    if quote_volume_24h < effective_min_quote_volume_trade:
        _mark_market_block(
            1,
            "volume_below_trade_threshold",
            {
                "quote_volume_24h": round(quote_volume_24h, 4),
                "min_quote_volume_trade": round(_safe_float(getattr(cfg, "min_quote_volume_trade", 0.0), 0.0), 4),
                "effective_min_quote_volume_trade": round(effective_min_quote_volume_trade, 4),
                "volume_ratio": round(volume_ratio_v, 3),
                "spread_bps": round(spread_bps, 4),
                "market_mode": "observe_only",
                "tradable": False,
            },
        )

    if cfg.require_volume_confirmation and volume_ratio_v < cfg.volume_ratio_min:
        _mark_market_block(
            3,
            "volume_too_low",
            {
                "volume_ratio": round(volume_ratio_v, 3),
                "required": cfg.volume_ratio_min,
                "market_mode": "observe_only",
                "tradable": False,
            },
        )

    min_depth_to_order_ratio = _safe_float(getattr(cfg, "min_depth_to_order_ratio", 0.0), 0.0)
    orderbook_depth_bps = _safe_float(getattr(cfg, "orderbook_depth_bps", 20.0), 20.0)
    depth_to_order_ratio = 0.0
    orderbook_quote_depth = 0.0
    if min_depth_to_order_ratio > 0:
        depth_to_order_ratio, orderbook_quote_depth = _get_orderbook_depth_ratio(
            binance_client,
            symbol,
            price,
            orderbook_depth_bps,
            _safe_float(getattr(cfg, "min_buy_notional", 60.0), 60.0),
        )
        if depth_to_order_ratio < min_depth_to_order_ratio:
            _mark_market_block(
                2,
                "orderbook_depth_too_low",
                {
                    "orderbook_depth_bps": orderbook_depth_bps,
                    "orderbook_quote_depth": round(orderbook_quote_depth, 4),
                    "depth_to_order_ratio": round(depth_to_order_ratio, 4),
                    "required_depth_to_order_ratio": min_depth_to_order_ratio,
                    "market_mode": "observe_only",
                    "tradable": False,
                },
            )

    # HTF agreement
    htf_ema_20 = ctx_htf.get("ema_20")
    htf_ema_50 = ctx_htf.get("ema_50")
    htf_rsi = ctx_htf.get("rsi")
    htf_score = _compute_htf_agreement(htf_ema_20, htf_ema_50, htf_rsi, price)

    if cfg.require_htf_trend_agreement and htf_score < 0.35:
        result.reason_code = "htf_trend_disagrees"
        result.reason_pl = _REASON_PL["htf_trend_disagrees"]
        result.details["htf_score"] = round(htf_score, 3)
        result.details["htf_ema_20"] = htf_ema_20
        result.details["htf_ema_50"] = htf_ema_50
        result.details["htf_rsi"] = htf_rsi
        return result

    # RSI overbought — nie wchodzimy przy RSI > 75
    rsi_v = _safe_float(rsi, 50.0)
    if rsi_v > 75.0:
        result.reason_code = "rsi_overbought"
        result.reason_pl = _REASON_PL["rsi_overbought"]
        result.details["rsi"] = round(rsi_v, 2)
        return result

    liquidity_score = _compute_liquidity_score(
        volume_24h_quote=quote_volume_24h,
        trade_count_1h=trades_1h,
        spread_pct=spread_pct,
        min_volume_24h=50_000.0,   # 50k USDC/EUR minimum
        min_trades_1h=50.0,
    )

    if liquidity_score < cfg.min_liquidity_score:
        _mark_market_block(
            4,
            "liquidity_too_low",
            {
                "liquidity_score": round(liquidity_score, 3),
                "required": cfg.min_liquidity_score,
                "quote_volume_24h": round(quote_volume_24h, 4),
                "trade_count_1h": round(trades_1h, 4),
                "spread_bps": round(spread_bps, 4),
                "market_mode": "observe_only",
                "tradable": False,
            },
        )

    regime_score = _compute_regime_score(bb_pos, rsi, bb_width)

    # ── 4. Wykryj sygnał BUY (warunki wejścia) ───────────────────────────
    # Sygnał BUY = kombinacja trend + momentum + potwierdzenie fast timeframe
    fast_ema_20 = ctx_fast.get("ema_20")
    fast_ema_50 = ctx_fast.get("ema_50")
    fast_above_trend = (
        fast_ema_20 and fast_ema_50
        and _safe_float(fast_ema_20) > _safe_float(fast_ema_50)
    )

    has_buy_signal = (
        trend_score >= 0.60           # trend w górę na entry TF
        and momentum_score >= 0.50    # impet pozytywny
        and (htf_score >= 0.50 or not cfg.require_htf_trend_agreement)
        and (fast_above_trend or trend_score >= 0.80)  # 15m potwierdza lub wyraźny 1h trend
    )

    if not has_buy_signal:
        result.reason_code = "no_buy_signal"
        result.reason_pl = _REASON_PL["no_buy_signal"]
        result.details.update({
            "trend_score": round(trend_score, 3),
            "momentum_score": round(momentum_score, 3),
            "htf_score": round(htf_score, 3),
            "fast_above_trend": fast_above_trend,
        })
        return result

    # ── 5. Złożony entry score ────────────────────────────────────────────
    # Wagi komponentów:
    #   trend:      25% (najważniejszy)
    #   htf:        20% (potwierdzenie wyższego TF)
    #   momentum:   20% (RSI + MACD)
    #   volume:     15% (potwierdzenie wolumenem)
    #   liquidity:  10% (płynność)
    #   regime:     10% (Bollinger)
    entry_score = _clamp01(
        trend_score * 0.25
        + htf_score * 0.20
        + momentum_score * 0.20
        + volume_score * 0.15
        + liquidity_score * 0.10
        + regime_score * 0.10
    )

    # Confidence: AI jeśli dostępne, fallback heurystyczny
    if external_confidence is not None:
        confidence = _clamp01(external_confidence)
    else:
        # Heurystyczna confidence z ważonych komponentów (bez minimalnej podłogi!)
        confidence = _clamp01(
            trend_score * 0.30
            + momentum_score * 0.30
            + volume_score * 0.20
            + htf_score * 0.20
        )

    result.score = entry_score
    result.confidence = confidence
    result.trend_score = trend_score
    result.momentum_score = momentum_score
    result.volume_score = volume_score
    result.liquidity_score = liquidity_score
    result.regime_score = regime_score
    result.htf_agreement_score = htf_score

    result.details.update({
        "score": round(entry_score, 4),
        "min_score": _safe_float(getattr(cfg, "min_entry_score", 0.0), 0.0),
        "confidence": round(confidence, 4),
        "min_confidence": _safe_float(getattr(cfg, "min_signal_confidence", 0.0), 0.0),
        "effective_min_quote_volume_trade": round(effective_min_quote_volume_trade, 4),
        "orderbook_quote_depth": round(orderbook_quote_depth, 4),
        "depth_to_order_ratio": round(depth_to_order_ratio, 4),
        "orderbook_depth_bps": round(orderbook_depth_bps, 4),
    })

    if market_block is not None:
        _, reason_code, reason_pl, block_details = market_block
        result.reason_code = reason_code
        result.reason_pl = reason_pl
        result.details.update(block_details)
        result.details.setdefault("final_action", "OBSERVE_ONLY")
        result.details.setdefault("tradable", False)
        return result

    # Score gate
    if entry_score < cfg.min_entry_score:
        result.reason_code = "score_too_low"
        result.reason_pl = _REASON_PL["score_too_low"]
        result.details["score"] = round(entry_score, 4)
        result.details["required"] = cfg.min_entry_score
        return result

    # Confidence gate
    if confidence < cfg.min_signal_confidence:
        result.reason_code = "confidence_too_low"
        result.reason_pl = _REASON_PL["confidence_too_low"]
        result.details["confidence"] = round(confidence, 4)
        result.details["required"] = cfg.min_signal_confidence
        return result

    # ── 6. Expected value gate ────────────────────────────────────────────
    expected_move_pct = (atr / price) * 100.0
    total_cost_pct = (
        cfg.taker_fee_pct / 100.0 * 2       # wejście + wyjście
        + cfg.slippage_bps / 10000.0 * 2    # slippage obustronnie
        + spread_pct / 100.0                # aktualny spread
    ) * 100.0  # -> %

    expected_net_edge_pct = expected_move_pct - total_cost_pct

    result.expected_move_pct = expected_move_pct
    result.total_cost_pct = total_cost_pct
    result.expected_net_edge_pct = expected_net_edge_pct

    # RR check: TP = entry + ATR*take_mult, SL = entry - ATR*stop_mult
    atr_stop = cfg.atr_stop_multiplier
    atr_take = cfg.atr_take_multiplier
    potential_gain_pct = atr / price * atr_take * 100.0
    potential_loss_pct = atr / price * atr_stop * 100.0
    rr_ratio = (
        (potential_gain_pct - total_cost_pct) / (potential_loss_pct + total_cost_pct)
        if potential_loss_pct > 0
        else 0.0
    )

    if expected_net_edge_pct < cfg.min_net_edge_pct:
        result.reason_code = "negative_edge_after_costs"
        result.reason_pl = _REASON_PL["negative_edge_after_costs"]
        result.details.update({
            "expected_move_pct": round(expected_move_pct, 4),
            "total_cost_pct": round(total_cost_pct, 4),
            "expected_net_edge_pct": round(expected_net_edge_pct, 4),
            "required_min_net_edge_pct": cfg.min_net_edge_pct,
        })
        return result

    if rr_ratio < cfg.min_expected_rr:
        result.reason_code = "negative_edge_after_costs"
        result.reason_pl = _REASON_PL["negative_edge_after_costs"]
        result.details.update({
            "rr_ratio": round(rr_ratio, 3),
            "required_rr": cfg.min_expected_rr,
            "potential_gain_pct": round(potential_gain_pct, 4),
            "potential_loss_pct": round(potential_loss_pct, 4),
        })
        return result

    # ── OK — sygnał ważny ─────────────────────────────────────────────────
    result.is_valid = True
    result.reason_code = "signal_accepted"
    result.details.update({
        "ema_20": _safe_float(ema_20),
        "ema_50": _safe_float(ema_50),
        "ema_200": _safe_float(ema_200),
        "rsi": round(rsi_v, 2),
        "macd_hist": _safe_float(macd_hist),
        "volume_ratio": _safe_float(volume_ratio),
        "quote_volume_24h": round(quote_volume_24h, 4),
        "effective_min_quote_volume_trade": round(effective_min_quote_volume_trade, 4),
        "orderbook_quote_depth": round(orderbook_quote_depth, 4),
        "depth_to_order_ratio": round(depth_to_order_ratio, 4),
        "orderbook_depth_bps": round(orderbook_depth_bps, 4),
        "spread_pct": round(spread_pct, 4),
        "spread_bps": round(spread_bps, 4),
        "atr": round(atr, 8),
        "rr_ratio": round(rr_ratio, 3),
        "htf_ema_20": _safe_float(htf_ema_20),
        "htf_ema_50": _safe_float(htf_ema_50),
        "htf_rsi": _safe_float(htf_rsi),
        "fast_above_trend": fast_above_trend,
    })

    logger.debug(
        "evaluate_entry_signal: %s VALID score=%.3f conf=%.3f edge=%.3f%% rr=%.2f",
        symbol, entry_score, confidence, expected_net_edge_pct, rr_ratio,
    )

    return result


def bulk_evaluate(
    db: Session,
    symbols: List[str],
    cfg,
    binance_client=None,
    ai_confidences: Optional[Dict[str, float]] = None,
    max_results: int = 10,
) -> List[EntrySignalResult]:
    """
    Oceń listę symboli i zwróć posortowane (best score) ważne sygnały.

    Args:
        symbols:        lista symboli do oceny
        cfg:            TradeConfig
        binance_client: do bookTicker (opcjonalny)
        ai_confidences: dict symbol → confidence z AI (opcjonalny)
        max_results:    max liczba wyników do zwrotu

    Returns:
        Lista EntrySignalResult posortowanych malejąco po score (tylko is_valid=True).
    """
    results = []
    ai_conf = ai_confidences or {}

    for sym in symbols:
        try:
            conf = ai_conf.get(sym)
            r = evaluate_entry_signal(
                db=db,
                symbol=sym,
                cfg=cfg,
                binance_client=binance_client,
                external_confidence=conf,
            )
            results.append(r)
        except Exception as exc:
            logger.warning("bulk_evaluate: błąd dla %s: %s", sym, exc)

    valid = [r for r in results if r.is_valid]
    valid.sort(key=lambda r: r.score, reverse=True)
    return valid[:max_results]
