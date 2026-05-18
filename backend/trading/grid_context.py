"""Market context loader for the dynamic grid engine."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional

import pandas as pd
import pandas_ta as ta
from sqlalchemy.orm import Session

from backend.database import Kline, MarketData

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GridTimeframeContext:
    timeframe: str
    close: float
    atr: float
    atr_pct: float
    ema_20: Optional[float]
    ema_50: Optional[float]
    rsi: Optional[float]
    adx: Optional[float]
    trend_bias: float
    realized_range_pct: float
    volume_ratio: Optional[float]
    vwap_24: Optional[float] = None


def _frame_from_klines(rows: list[Kline]) -> pd.DataFrame:
    ordered = list(reversed(rows))
    return pd.DataFrame(
        {
            "open": [float(k.open) for k in ordered],
            "high": [float(k.high) for k in ordered],
            "low": [float(k.low) for k in ordered],
            "close": [float(k.close) for k in ordered],
            "volume": [float(k.volume) for k in ordered],
        }
    )


def _load_timeframe_context(
    db: Session,
    symbol: str,
    timeframe: str,
    limit: int,
) -> Optional[GridTimeframeContext]:
    klines = (
        db.query(Kline)
        .filter(Kline.symbol == symbol, Kline.timeframe == timeframe)
        .order_by(Kline.open_time.desc())
        .limit(limit)
        .all()
    )
    if len(klines) < 60:
        return None

    df = _frame_from_klines(klines)
    df["ema_20"] = ta.ema(df["close"], length=20)
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["rsi_14"] = ta.rsi(df["close"], length=14)
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    try:
        adx_result = ta.adx(df["high"], df["low"], df["close"], length=14)
        if adx_result is not None and not adx_result.empty:
            adx_col = next(
                (col for col in adx_result.columns if str(col).startswith("ADX_")),
                None,
            )
            if adx_col:
                df["adx_14"] = adx_result[adx_col]
    except Exception:
        df["adx_14"] = None

    last = df.iloc[-1]
    close = float(last["close"])
    atr = float(last["atr_14"]) if pd.notna(last["atr_14"]) else 0.0
    atr_pct = atr / close if close > 0 and atr > 0 else 0.0
    ema_20 = float(last["ema_20"]) if pd.notna(last["ema_20"]) else None
    ema_50 = float(last["ema_50"]) if pd.notna(last["ema_50"]) else None
    rsi = float(last["rsi_14"]) if pd.notna(last["rsi_14"]) else None
    adx = (
        float(last["adx_14"])
        if "adx_14" in df.columns and pd.notna(last.get("adx_14"))
        else None
    )

    trend_bias = 0.0
    if ema_20 is not None and ema_50 is not None:
        trend_bias = 1.0 if ema_20 > ema_50 else -1.0

    recent = df.iloc[-50:]
    realized_range_pct = (
        (float(recent["high"].max()) - float(recent["low"].min())) / close
        if close > 0
        else 0.0
    )

    volume_ratio = None
    vol_sma = df["volume"].rolling(20).mean()
    last_sma = vol_sma.iloc[-1]
    if pd.notna(last_sma) and float(last_sma) > 0:
        volume_ratio = float(df["volume"].iloc[-1] / last_sma)

    vwap_24 = None
    if len(df) >= 24:
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        quote_volume = (typical * df["volume"]).rolling(24).sum()
        base_volume = df["volume"].rolling(24).sum()
        vwap_series = quote_volume / base_volume.replace(0, pd.NA)
        vwap_last = vwap_series.iloc[-1]
        if pd.notna(vwap_last):
            vwap_24 = float(vwap_last)

    return GridTimeframeContext(
        timeframe=timeframe,
        close=close,
        atr=atr,
        atr_pct=atr_pct,
        ema_20=ema_20,
        ema_50=ema_50,
        rsi=rsi,
        adx=adx,
        trend_bias=trend_bias,
        realized_range_pct=realized_range_pct,
        volume_ratio=volume_ratio,
        vwap_24=vwap_24,
    )


def get_grid_context(
    db: Session,
    symbol: str,
    *,
    fast_tf: str = "15m",
    anchor_tf: str = "1h",
    trend_tf: str = "4h",
    limit: int = 200,
) -> Optional[dict[str, Any]]:
    """Return the multi-timeframe dict consumed by backend.trading.dynamic_grid."""
    symbol_norm = str(symbol or "").strip().upper().replace("/", "").replace("-", "")
    if not symbol_norm:
        return None

    contexts: dict[str, GridTimeframeContext] = {}
    for timeframe in (fast_tf, anchor_tf, trend_tf):
        tf_context = _load_timeframe_context(db, symbol_norm, timeframe, limit)
        if tf_context is None:
            logger.debug(
                "get_grid_context %s: insufficient %s bars for dynamic grid",
                symbol_norm,
                timeframe,
            )
            return None
        contexts[timeframe] = tf_context

    last_price = contexts[anchor_tf].close or contexts[fast_tf].close
    latest_market = (
        db.query(MarketData)
        .filter(MarketData.symbol == symbol_norm)
        .order_by(MarketData.timestamp.desc())
        .first()
    )

    spread_bps = 10.0
    if latest_market and latest_market.bid and latest_market.ask and latest_market.price:
        bid = float(latest_market.bid)
        ask = float(latest_market.ask)
        price = float(latest_market.price)
        if ask > bid and price > 0:
            spread_bps = ((ask - bid) / price) * 10000.0
            last_price = price

    payload: dict[str, Any] = {
        "symbol": symbol_norm,
        "last_price": float(last_price),
        "spread_bps": float(spread_bps),
    }
    for timeframe, tf_context in contexts.items():
        data = asdict(tf_context)
        data["atr"] = data.pop("atr")
        payload[timeframe] = data

    return payload
