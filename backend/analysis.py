"""
Moduł analizy technicznej i generacji bloga.
"""
from __future__ import annotations

from typing import Any, List, Dict, Optional
from datetime import datetime, timedelta, timezone
import json
import os
import requests
import re
import time as _time

import pandas as pd
import pandas_ta as ta

from backend.database import Kline, Signal, BlogPost, utc_now_naive
from backend.system_logger import log_to_db, log_exception
from backend.accounting import build_profitability_guard, estimate_trade_costs

_last_openai_error_ts: Optional[datetime] = None
_last_gemini_error_ts: Optional[datetime] = None
_last_groq_error_ts: Optional[datetime] = None
_last_ollama_error_ts: Optional[datetime] = None

# Cache dla zewnętrznych źródeł danych (bez klucza API)
_fear_greed_cache: dict = {"value": None, "ts": None}
_coingecko_cache: dict = {"data": None, "ts": None}
_FEAR_GREED_TTL = 300   # 5 min
_COINGECKO_TTL = 600    # 10 min

# Cache dla get_live_context — unika powtórnych DB queries + pandas-ta per request
# Kolektor zapisuje nowe klines co 60s, więc TTL 55s jest bezpieczny.
_live_ctx_cache: dict = {}
_LIVE_CTX_TTL = 20  # sekund (kolektor co 60s, frontend co 15-25s → max staleness ~20s)


def _fetch_fear_greed_index() -> Optional[int]:
    """Pobiera Fear & Greed Index z alternative.me (darmowe, bez klucza API).

    Wartość 0-100: 0-24 = Extreme Fear, 25-49 = Fear, 50-74 = Greed, 75-100 = Extreme Greed.
    Cache: 5 minut. Fallback: ostatnia znana wartość lub None.
    """
    global _fear_greed_cache
    now = datetime.now(timezone.utc)
    ts = _fear_greed_cache.get("ts")
    if ts and (now - ts).total_seconds() < _FEAR_GREED_TTL and _fear_greed_cache["value"] is not None:
        return _fear_greed_cache["value"]
    try:
        resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=4)
        if resp.status_code == 200:
            raw = resp.json()
            value = int(raw["data"][0]["value"])
            _fear_greed_cache = {"value": value, "ts": now}
            return value
    except Exception:
        pass
    return _fear_greed_cache.get("value")  # stare dane przy błędzie połączenia


def _fetch_coingecko_global() -> Optional[dict]:
    """Pobiera globalne dane rynku krypto z CoinGecko public API (darmowe, bez klucza).

    Zwraca dict z: btc_dominance, market_cap_change_24h, total_market_cap_usd.
    Cache: 10 minut. Fallback: ostatnie znane dane lub None.
    """
    global _coingecko_cache
    now = datetime.now(timezone.utc)
    ts = _coingecko_cache.get("ts")
    if ts and (now - ts).total_seconds() < _COINGECKO_TTL and _coingecko_cache["data"] is not None:
        return _coingecko_cache["data"]
    try:
        resp = requests.get("https://api.coingecko.com/api/v3/global", timeout=4)
        if resp.status_code == 200:
            raw = resp.json().get("data", {})
            result = {
                "btc_dominance": raw.get("btc_dominance"),
                "market_cap_change_24h": raw.get("market_cap_change_percentage_24h_usd"),
                "total_market_cap_usd": (raw.get("total_market_cap") or {}).get("usd"),
            }
            _coingecko_cache = {"data": result, "ts": now}
            return result
    except Exception:
        pass
    return _coingecko_cache.get("data")


# Cache dla market regime — odnawia się co 30 minut
_market_regime_cache: dict = {"data": None, "ts": None}
_MARKET_REGIME_TTL = 1800  # 30 minut


def get_market_regime() -> dict:
    """Wyznacza aktualny reżim rynkowy na podstawie F&G + CoinGecko.

    Zwraca:
        regime: CRASH / BEAR / BEAR_SOFT / SIDEWAYS / BULL / UNKNOWN
        buy_confidence_adj: korekta min_confidence dla wejść BUY (dodatnia = ostrzejszy filtr)
        buy_blocked: czy wejścia BUY mają być zablokowane
        reason: opis sytuacji rynkowej
    """
    global _market_regime_cache
    now = datetime.now(timezone.utc)
    ts = _market_regime_cache.get("ts")
    if ts and (now - ts).total_seconds() < _MARKET_REGIME_TTL and _market_regime_cache["data"]:
        return _market_regime_cache["data"]

    fg = _fetch_fear_greed_index()
    coingecko = _fetch_coingecko_global()
    mc_chg = float((coingecko or {}).get("market_cap_change_24h", 0) or 0)

    if fg is None:
        result = {
            "regime": "UNKNOWN",
            "buy_confidence_adj": 0.0,
            "buy_blocked": False,
            "reason": "Brak danych F&G — tryb neutralny",
        }
    elif fg <= 15 and mc_chg < -2.5:
        result = {
            "regime": "CRASH",
            "buy_confidence_adj": 0.15,  # P1-FIX: 0.20→0.15 — nadal blokujące ale mniej agresywne
            "buy_blocked": True,
            "reason": f"🔴 CRASH: F&G={fg} Extreme Fear + MCap {mc_chg:+.1f}% — BUY ZABLOKOWANY",
        }
    elif fg <= 20 and mc_chg < -1.0:
        result = {
            "regime": "BEAR",
            "buy_confidence_adj": 0.10,  # P1-FIX: 0.15→0.10 — mniej agresywne blokowanie
            "buy_blocked": True,
            "reason": f"🟠 BEAR: F&G={fg} Extreme Fear + MCap {mc_chg:+.1f}% — BUY ZABLOKOWANY",
        }
    elif fg <= 30 and mc_chg < 0:
        result = {
            "regime": "BEAR_SOFT",
            "buy_confidence_adj": 0.05,  # P1-FIX: 0.10→0.05 — BEAR_SOFT nie może blokować typowych sygnałów
            "buy_blocked": False,
            "reason": f"🟡 BEAR_SOFT: F&G={fg} Fear + MCap {mc_chg:+.1f}% — podwyższone progi BUY",
        }
    elif fg >= 75 and mc_chg > 2.0:
        result = {
            "regime": "BULL",
            "buy_confidence_adj": -0.05,
            "buy_blocked": False,
            "reason": f"🟢 BULL: F&G={fg} Extreme Greed + MCap {mc_chg:+.1f}%",
        }
    else:
        result = {
            "regime": "SIDEWAYS",
            "buy_confidence_adj": 0.0,
            "buy_blocked": False,
            "reason": f"⚪ SIDEWAYS: F&G={fg} + MCap {mc_chg:+.1f}%",
        }

    _market_regime_cache = {"data": result, "ts": now}
    return result


def _get_openai_api_key() -> str:
    key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    # Support keys accidentally wrapped in quotes in `.env`.
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()
    return key


def _klines_to_df(klines: List[Kline]) -> Optional[pd.DataFrame]:
    if not klines:
        return None

    data = {
        "open_time": [k.open_time for k in klines],
        "open": [k.open for k in klines],
        "high": [k.high for k in klines],
        "low": [k.low for k in klines],
        "close": [k.close for k in klines],
        "volume": [k.volume for k in klines],
    }
    df = pd.DataFrame(data).sort_values("open_time")
    return df


def _compute_indicators(df: pd.DataFrame) -> Dict[str, float]:
    """Zwraca ostatnie wartości wskaźników."""
    indicators: Dict[str, float] = {}

    if len(df) < 60:
        return indicators

    df = df.copy()
    df["ema_20"] = ta.ema(df["close"], length=20)
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["rsi_14"] = ta.rsi(df["close"], length=14)
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
    if macd is not None:
        df["macd"] = macd["MACD_12_26_9"]
        df["macd_hist"] = macd["MACDh_12_26_9"]

    bb = ta.bbands(df["close"], length=20, std=2)
    if bb is not None and not bb.empty:
        upper_col = next((c for c in bb.columns if "BBU" in c), None)
        lower_col = next((c for c in bb.columns if "BBL" in c), None)
        if upper_col and lower_col:
            df["bb_upper"] = bb[upper_col]
            df["bb_lower"] = bb[lower_col]

    # ADX — siła trendu (>25 = silny trend, <20 = korekta/rynek boczny)
    try:
        adx = ta.adx(df["high"], df["low"], df["close"], length=14)
        if adx is not None and not adx.empty:
            adx_col = next((c for c in adx.columns if c.startswith("ADX_")), None)
            if adx_col:
                df["adx"] = adx[adx_col]
    except Exception:
        pass

    # Stochastic %K — momentum oscylator
    try:
        stoch = ta.stoch(df["high"], df["low"], df["close"], k=14, d=3)
        if stoch is not None and not stoch.empty:
            k_col = next((c for c in stoch.columns if "STOCHk" in c or c.startswith("K_")), None)
            if k_col:
                df["stoch_k"] = stoch[k_col]
    except Exception:
        pass

    # Volume ratio: ostatni wolumen vs SMA(20) wolumenu
    if "volume" in df.columns:
        try:
            df["vol_sma20"] = df["volume"].rolling(20).mean()
            last_vol = df["volume"].iloc[-1]
            last_vsma = df["vol_sma20"].iloc[-1]
            if pd.notna(last_vol) and pd.notna(last_vsma) and last_vsma > 0:
                df["volume_ratio"] = df["volume"] / df["vol_sma20"]
        except Exception:
            pass

    # Zmiana procentowa ceny (1h = 1 świeca, 24h = 24 świece)
    try:
        if len(df) >= 2:
            df["price_change_1h"] = df["close"].pct_change(1) * 100
        if len(df) >= 24:
            df["price_change_24h"] = df["close"].pct_change(24) * 100
    except Exception:
        pass

    # Doji — świeca niezdecydowania (body < 10% zakresu)
    try:
        doji = ta.cdl_doji(df["open"], df["high"], df["low"], df["close"])
        if doji is not None and len(doji) > 0:
            df["doji_signal"] = doji
    except Exception:
        pass

    # Inside bar — konsolidacja, potencjalny breakout (H<prevH i L>prevL)
    try:
        inside = ta.cdl_inside(df["open"], df["high"], df["low"], df["close"])
        if inside is not None and len(inside) > 0:
            df["inside_bar"] = inside
    except Exception:
        pass

    # Rolling VWAP (24 świece) — cena vs VWAP jako bias kierunkowy
    if "volume" in df.columns and len(df) >= 24:
        try:
            typical = (df["high"] + df["low"] + df["close"]) / 3
            df["vwap_24"] = (
                (typical * df["volume"]).rolling(24).sum()
                / df["volume"].rolling(24).sum()
            )
        except Exception:
            pass

    # Kanały Donchiana (20 świec) — poziomy wsparcia/oporu
    try:
        dc = ta.donchian(df["high"], df["low"], lower_length=20, upper_length=20)
        if dc is not None and not dc.empty:
            dcl_col = next((c for c in dc.columns if "DCL" in c), None)
            dcu_col = next((c for c in dc.columns if "DCU" in c), None)
            if dcl_col:
                df["donchian_lower"] = dc[dcl_col]
            if dcu_col:
                df["donchian_upper"] = dc[dcu_col]
    except Exception:
        pass

    # MFI (Money Flow Index 14) — RSI ważone wolumenem
    if "volume" in df.columns:
        try:
            mfi = ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=14)
            if mfi is not None and len(mfi) > 0:
                df["mfi_14"] = mfi
        except Exception:
            pass

    # OBV trend — nachylenie On-Balance Volume (EMA5 vs EMA20 OBV)
    if "volume" in df.columns:
        try:
            obv = ta.obv(df["close"], df["volume"])
            if obv is not None and len(obv) >= 20:
                obv_ema5 = obv.ewm(span=5, adjust=False).mean()
                obv_ema20 = obv.ewm(span=20, adjust=False).mean()
                df["obv_trend"] = (obv_ema5 - obv_ema20).apply(
                    lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)
                )
        except Exception:
            pass

    # Fibonacci retracement ze 50-barowego zakresu high/low
    if len(df) >= 50:
        try:
            window = df["close"].iloc[-50:]
            swing_high = float(df["high"].iloc[-50:].max())
            swing_low = float(df["low"].iloc[-50:].min())
            if swing_high > swing_low:
                fib_range = swing_high - swing_low
                df["fib_382"] = swing_high - 0.382 * fib_range  # wsparcie
                df["fib_618"] = swing_high - 0.618 * fib_range  # głębsze wsparcie
                df["fib_236"] = swing_high - 0.236 * fib_range  # słabszy opór
        except Exception:
            pass

    # Engulfing pattern — ręczne wykrycie (brak TA-Lib)
    # +1 = bycze (bullish engulfing), -1 = niedźwiedzie (bearish engulfing)
    try:
        if len(df) >= 2:
            prev = df.iloc[-2]
            curr = df.iloc[-1]
            prev_body_lo = min(float(prev["open"]), float(prev["close"]))
            prev_body_hi = max(float(prev["open"]), float(prev["close"]))
            curr_body_lo = min(float(curr["open"]), float(curr["close"]))
            curr_body_hi = max(float(curr["open"]), float(curr["close"]))
            prev_bearish = float(prev["close"]) < float(prev["open"])
            curr_bullish = float(curr["close"]) > float(curr["open"])
            prev_bullish = float(prev["close"]) > float(prev["open"])
            curr_bearish = float(curr["close"]) < float(curr["open"])
            if prev_bearish and curr_bullish and curr_body_lo < prev_body_lo and curr_body_hi > prev_body_hi:
                df.loc[df.index[-1], "engulfing"] = 1.0   # bycze
            elif prev_bullish and curr_bearish and curr_body_lo < prev_body_lo and curr_body_hi > prev_body_hi:
                df.loc[df.index[-1], "engulfing"] = -1.0  # niedźwiedzie
            else:
                df.loc[df.index[-1], "engulfing"] = 0.0
    except Exception:
        pass

    # Supertrend (ATR*3, length=7) — najsilniejszy trend filter
    # SUPERTd: +1 = bycze, -1 = niedźwiedzie
    try:
        st = ta.supertrend(df["high"], df["low"], df["close"], length=7, multiplier=3.0)
        if st is not None and not st.empty:
            d_col = next((c for c in st.columns if "SUPERTd" in c), None)
            if d_col:
                df["supertrend_dir"] = st[d_col]
    except Exception:
        pass

    # Squeeze Momentum — wykrywa konsolidację przed wybiciem
    # SQZ_ON=1: niska zmienność (konsolidacja), SQZ_OFF=1: po wyjściu ze squeeze
    try:
        sq = ta.squeeze(
            df["high"], df["low"], df["close"],
            bb_length=20, kc_length=20, asint=True,
        )
        if sq is not None and not sq.empty:
            if "SQZ_ON" in sq.columns:
                df["squeeze_on"] = sq["SQZ_ON"]
            if "SQZ_OFF" in sq.columns:
                df["squeeze_off"] = sq["SQZ_OFF"]
            # Histogram momentum Squeeze (kierunek wybicia)
            hist_col = next((c for c in sq.columns if sq[c].dtype in ['float64','float32']
                             and c not in ('SQZ_ON','SQZ_OFF','SQZ_NO')), None)
            if hist_col:
                df["squeeze_hist"] = sq[hist_col]
    except Exception:
        pass

    # RSI Divergence (ręczne, okno 10 świec)
    # +1 = bycza dywergencja (cena niższy dół, RSI wyższy dół)
    # -1 = niedźwiedzia dywergencja (cena wyższy szczyt, RSI niższy szczyt)
    try:
        if "rsi_14" in df.columns and len(df) >= 10:
            win = 10
            price_w = df["close"].iloc[-win:].values
            rsi_w = df["rsi_14"].iloc[-win:].values
            # Szukaj lokalnego minimum (ostatnie 5 vs poprzednie 5)
            p_min1 = float(price_w[-5:].min())
            p_min2 = float(price_w[:5].min())
            r_min1 = float(rsi_w[-5:].min())
            r_min2 = float(rsi_w[:5].min())
            # Szukaj lokalnego maksimum
            p_max1 = float(price_w[-5:].max())
            p_max2 = float(price_w[:5].max())
            r_max1 = float(rsi_w[-5:].max())
            r_max2 = float(rsi_w[:5].max())
            div = 0.0
            # Bycza: cena robi niższy dół, RSI robi wyższy dół
            if p_min1 < p_min2 * 0.998 and r_min1 > r_min2 * 1.005:
                div = 1.0
            # Niedźwiedzia: cena robi wyższy szczyt, RSI robi niższy szczyt
            elif p_max1 > p_max2 * 1.002 and r_max1 < r_max2 * 0.995:
                div = -1.0
            df.loc[df.index[-1], "rsi_divergence"] = div
    except Exception:
        pass

    last = df.iloc[-1]
    for key in [
        "ema_20", "ema_50", "rsi_14", "atr_14", "macd", "macd_hist",
        "bb_upper", "bb_lower", "adx", "stoch_k", "volume_ratio",
        "price_change_1h", "price_change_24h",
        "doji_signal", "inside_bar", "vwap_24", "donchian_lower", "donchian_upper",
        "mfi_14", "obv_trend", "fib_382", "fib_618", "fib_236", "engulfing",
        "supertrend_dir", "squeeze_on", "squeeze_off", "squeeze_hist", "rsi_divergence",
    ]:
        if key in df.columns and pd.notna(last.get(key)):
            indicators[key] = float(last[key])

    indicators["close"] = float(last["close"])
    return indicators


def _insight_from_indicators(indicators: Dict[str, float]) -> Dict[str, str]:
    """Wielowskaźnikowa analiza sygnałów tradingowych (system punktowy).

    Każdy wskaźnik głosuje BUY (+) lub SELL (-) z określoną wagą.
    Ostateczny sygnał zależy od sumy głosów — przy przewadze 2+ punktów
    sygnał jest potwierdzony.
    """
    rsi = indicators.get("rsi_14")
    ema_20 = indicators.get("ema_20")
    ema_50 = indicators.get("ema_50")
    macd_hist = indicators.get("macd_hist")
    macd = indicators.get("macd")
    close = indicators.get("close")
    bb_upper = indicators.get("bb_upper")
    bb_lower = indicators.get("bb_lower")
    adx = indicators.get("adx")
    stoch_k = indicators.get("stoch_k")
    volume_ratio = indicators.get("volume_ratio")
    pct_1h = indicators.get("price_change_1h")
    doji_signal = indicators.get("doji_signal")    # != 0 → doji pattern
    inside_bar = indicators.get("inside_bar")      # 100 → inside bar (konsolidacja)
    vwap_24 = indicators.get("vwap_24")            # rolling VWAP 24-period
    mfi_14 = indicators.get("mfi_14")              # Money Flow Index (volume-weighted RSI)
    obv_trend = indicators.get("obv_trend")        # +1 akumulacja, -1 dystrybucja
    engulfing = indicators.get("engulfing")        # +1 bycze, -1 niedźwiedzie
    supertrend_dir = indicators.get("supertrend_dir")  # +1 bycze, -1 niedźwiedzie
    squeeze_on = indicators.get("squeeze_on")      # 1 = squeeze aktywny (niska zmienność)
    squeeze_off = indicators.get("squeeze_off")    # 1 = właśnie wyszedł ze squeeze
    squeeze_hist = indicators.get("squeeze_hist")  # momentum kierunek po wyjściu ze squeeze
    rsi_divergence = indicators.get("rsi_divergence")  # +1 bycza, -1 niedźwiedzia dywergencja

    reasons = []
    score = 0  # >0 = BUY, <0 = SELL
    base_confidence = 0.58

    trend_up_confirmed = bool(
        ema_20 is not None and ema_50 is not None and ema_20 > ema_50
        and supertrend_dir is not None and supertrend_dir > 0
    )
    trend_down_confirmed = bool(
        ema_20 is not None and ema_50 is not None and ema_20 < ema_50
        and supertrend_dir is not None and supertrend_dir < 0
    )
    bullish_momentum = bool((macd_hist is not None and macd_hist > 0) or (pct_1h is not None and pct_1h > 0))
    bearish_momentum = bool((macd_hist is not None and macd_hist < 0) or (pct_1h is not None and pct_1h < 0))

    # ---- RSI (waga: 2) ----
    if rsi is not None:
        if rsi < 30:
            if trend_up_confirmed and bullish_momentum:
                score += 2
                reasons.append(f"RSI={rsi:.0f} — skrajne wyprzedanie, ale z potwierdzeniem odbicia")
            else:
                reasons.append(f"RSI={rsi:.0f} — skrajne wyprzedanie bez potwierdzenia odbicia")
        elif rsi < 40:
            if trend_up_confirmed and bullish_momentum:
                score += 1
                reasons.append(f"RSI={rsi:.0f} — strefa kupna z potwierdzeniem trendu")
            else:
                reasons.append(f"RSI={rsi:.0f} — niskie, ale bez potwierdzenia BUY")
        elif rsi > 70:
            if trend_down_confirmed and bearish_momentum:
                score -= 2
                reasons.append(f"RSI={rsi:.0f} — skrajne wykupienie z potwierdzeniem słabości")
            else:
                reasons.append(f"RSI={rsi:.0f} — skrajne wykupienie bez potwierdzenia SELL")
        elif rsi > 60:
            if trend_down_confirmed and bearish_momentum:
                score -= 1
                reasons.append(f"RSI={rsi:.0f} — strefa sprzedaży z potwierdzeniem trendu")
            else:
                reasons.append(f"RSI={rsi:.0f} — wysokie, ale bez potwierdzenia SELL")
        else:
            reasons.append(f"RSI={rsi:.0f} — strefa neutralna")

    # ---- EMA cross (waga: 2) ----
    if ema_20 is not None and ema_50 is not None:
        diff_pct = (ema_20 - ema_50) / ema_50 * 100 if ema_50 else 0
        if ema_20 > ema_50:
            score += 2 if diff_pct > 0.5 else 1
            reasons.append(f"EMA20 > EMA50 (+{diff_pct:.2f}%) — trend wzrostowy")
        else:
            score -= 2 if diff_pct < -0.5 else 1
            reasons.append(f"EMA20 < EMA50 ({diff_pct:.2f}%) — trend spadkowy")

    # ---- MACD histogram (waga: 1) ----
    if macd_hist is not None:
        if macd_hist > 0 and macd is not None and macd > 0:
            score += 1
            reasons.append(f"MACD histogram={macd_hist:.4f} — momentum wzrostowe")
        elif macd_hist < 0 and macd is not None and macd < 0:
            score -= 1
            reasons.append(f"MACD histogram={macd_hist:.4f} — momentum spadkowe")
        elif macd_hist > 0:
            reasons.append(f"MACD hist rosnący ({macd_hist:.4f}), ale MACD ujemny — wczesny sygnał")
        else:
            reasons.append(f"MACD hist malejący ({macd_hist:.4f})")

    # ---- Bollinger Bands (waga: 2) ----
    if close is not None and bb_lower is not None and bb_upper is not None:
        bb_range = bb_upper - bb_lower
        pct_b = (close - bb_lower) / bb_range if bb_range > 0 else 0.5
        if close < bb_lower:
            if trend_up_confirmed and bullish_momentum:
                score += 1
                reasons.append(f"%B={pct_b:.2f} — cena przy dolnym BB, ale rynek już odbija")
            else:
                reasons.append(f"%B={pct_b:.2f} — cena poniżej dolnego BB bez potwierdzenia odbicia")
        elif pct_b < 0.25:
            if trend_up_confirmed and bullish_momentum:
                score += 1
                reasons.append(f"%B={pct_b:.2f} — cena w dolnej ćwiartce BB z potwierdzeniem trendu")
            else:
                reasons.append(f"%B={pct_b:.2f} — dolna ćwiartka BB bez potwierdzenia BUY")
        elif close > bb_upper:
            if trend_down_confirmed and bearish_momentum:
                score -= 1
                reasons.append(f"%B={pct_b:.2f} — cena powyżej górnego BB z potwierdzeniem słabości")
            else:
                reasons.append(f"%B={pct_b:.2f} — cena powyżej górnego BB bez potwierdzenia SELL")
        elif pct_b > 0.75:
            if trend_down_confirmed and bearish_momentum:
                score -= 1
                reasons.append(f"%B={pct_b:.2f} — cena w górnej ćwiartce BB z potwierdzeniem SELL")
            else:
                reasons.append(f"%B={pct_b:.2f} — górna ćwiartka BB bez potwierdzenia SELL")
        else:
            reasons.append(f"%B={pct_b:.2f} — cena w środku BB")

    # ---- Stochastic %K (waga: 1) ----
    if stoch_k is not None:
        if stoch_k < 20:
            if trend_up_confirmed and bullish_momentum:
                score += 1
                reasons.append(f"Stoch%K={stoch_k:.0f} — wyprzedanie z potwierdzeniem odbicia")
            else:
                reasons.append(f"Stoch%K={stoch_k:.0f} — wyprzedanie bez potwierdzenia")
        elif stoch_k > 80:
            if trend_down_confirmed and bearish_momentum:
                score -= 1
                reasons.append(f"Stoch%K={stoch_k:.0f} — wykupienie z potwierdzeniem słabości")
            else:
                reasons.append(f"Stoch%K={stoch_k:.0f} — wykupienie bez potwierdzenia")

    # ---- ADX — siła trendu (modyfikator, nie głos) ----
    trend_strength = "boczny"
    if adx is not None:
        if adx > 25:
            trend_strength = "silny"
            # Silny trend wzmacnia głosy EMA
            base_confidence += 0.05
            reasons.append(f"ADX={adx:.0f} — silny trend (wzmocnienie sygnału EMA)")
        elif adx > 20:
            trend_strength = "umiarkowany"
            reasons.append(f"ADX={adx:.0f} — umiarkowany trend")
        else:
            trend_strength = "boczny"
            reasons.append(f"ADX={adx:.0f} — rynek boczny (słabsze sygnały)")
            # Rynek boczny — redukuj pewność sygnału
            base_confidence -= 0.03

    # ---- Potwierdzenie wolumenem (waga: 1) ----
    if volume_ratio is not None:
        if volume_ratio > 1.5:
            # Wysoki wolumen potwierdza kierunek sygnału
            if score > 0:
                score += 1
                reasons.append(f"Wolumen {volume_ratio:.1f}x SMA20 — potwierdza BUY")
            elif score < 0:
                score -= 1
                reasons.append(f"Wolumen {volume_ratio:.1f}x SMA20 — potwierdza SELL")
        elif volume_ratio < 0.6:
            reasons.append(f"Niski wolumen ({volume_ratio:.1f}x SMA20) — słaby sygnał")
            base_confidence -= 0.04

    # ---- Zmiana % ceny (kontekst) ----
    if pct_1h is not None:
        if pct_1h < -2.0:
            if trend_down_confirmed:
                score -= 1
                reasons.append(f"Spadek {pct_1h:.1f}% w 1h — momentum spadkowe, nie łap spadającego noża")
            else:
                reasons.append(f"Spadek {pct_1h:.1f}% w 1h — obserwacja, bez automatycznego BUY")
        elif pct_1h > 2.0:
            if trend_up_confirmed:
                score += 1
                reasons.append(f"Wzrost {pct_1h:.1f}% w 1h — momentum wzrostowe potwierdza trend")
            else:
                reasons.append(f"Wzrost {pct_1h:.1f}% w 1h — bez pełnego potwierdzenia trendu")

    # ---- VWAP rolling 24h (waga: 1) ----
    if vwap_24 is not None and close is not None and vwap_24 > 0:
        vwap_diff_pct = (close - vwap_24) / vwap_24 * 100
        if close > vwap_24 * 1.005:
            score += 1
            reasons.append(f"Cena +{vwap_diff_pct:.1f}% powyżej VWAP(24) — kupujący dominują")
        elif close < vwap_24 * 0.995:
            score -= 1
            reasons.append(f"Cena {vwap_diff_pct:.1f}% poniżej VWAP(24) — sprzedający dominują")
        else:
            reasons.append(f"Cena ≈VWAP(24) ({vwap_diff_pct:+.1f}%) — równowaga")

    # ---- Wzorce świecowe (modyfikatory pewności) ----
    if inside_bar is not None and inside_bar != 0:
        # Inside bar = rynek się konsoliduje, sygnał może być fałszywy
        base_confidence -= 0.04
        reasons.append("Inside bar — konsolidacja/pauza (redukcja pewności)")
    if doji_signal is not None and doji_signal != 0:
        # Doji przy skrajnym RSI potwierdza odwrócenie
        if rsi is not None and rsi < 35:
            score += 1
            reasons.append(f"Doji przy RSI={rsi:.0f} — możliwe odwrócenie w górę")
        elif rsi is not None and rsi > 65:
            score -= 1
            reasons.append(f"Doji przy RSI={rsi:.0f} — możliwe odwrócenie w dół")
        else:
            reasons.append("Doji — niezdecydowanie rynku")

    # ---- Engulfing — najsilniejszy wzorzec świecowy (waga: 2) ----
    if engulfing is not None and engulfing != 0:
        if engulfing > 0:
            score += 2
            reasons.append("Bycze Engulfing — silny sygnał odwrócenia w górę")
        else:
            score -= 2
            reasons.append("Niedźwiedzie Engulfing — silny sygnał odwrócenia w dół")

    # ---- MFI — Money Flow Index (waga: 1) ----
    if mfi_14 is not None:
        if mfi_14 < 20:
            if trend_up_confirmed and bullish_momentum:
                score += 1
                reasons.append(f"MFI={mfi_14:.0f} — skrajny outflow, ale już z potwierdzeniem odbicia")
            else:
                reasons.append(f"MFI={mfi_14:.0f} — skrajny outflow bez potwierdzenia BUY")
        elif mfi_14 < 35:
            reasons.append(f"MFI={mfi_14:.0f} — strefa kupna")
        elif mfi_14 > 80:
            if trend_down_confirmed and bearish_momentum:
                score -= 1
                reasons.append(f"MFI={mfi_14:.0f} — skrajny inflow z potwierdzeniem SELL")
            else:
                reasons.append(f"MFI={mfi_14:.0f} — skrajny inflow bez potwierdzenia SELL")
        elif mfi_14 > 65:
            reasons.append(f"MFI={mfi_14:.0f} — strefa sprzedaży")
        else:
            reasons.append(f"MFI={mfi_14:.0f} — neutralny")

    # ---- OBV trend — akumulacja/dystrybucja (waga: 1) ----
    if obv_trend is not None and obv_trend != 0:
        if obv_trend > 0:
            score += 1
            reasons.append("OBV ↑ — akumulacja (Volume potwierdza trend wzrostowy)")
        else:
            score -= 1
            reasons.append("OBV ↓ — dystrybucja (Volume potwierdza trend spadkowy)")

    # ---- Supertrend (waga: 2) — najsilniejszy trend filter ----
    if supertrend_dir is not None:
        if supertrend_dir > 0:
            score += 2
            reasons.append("Supertrend ↑ — trend wzrostowy (silny ATR-based sygnał BUY)")
        else:
            score -= 2
            reasons.append("Supertrend ↓ — trend spadkowy (silny ATR-based sygnał SELL)")

    # ---- Squeeze Momentum — wybicie ze squeeze (waga: 1) ----
    if squeeze_off is not None and squeeze_off == 1 and squeeze_hist is not None:
        # Właśnie wyszedł ze squeeze — możliwy silny ruch
        if squeeze_hist > 0:
            score += 1
            reasons.append("Squeeze → wybicie w górę (Bollinger+Keltner release)")
        elif squeeze_hist < 0:
            score -= 1
            reasons.append("Squeeze → wybicie w dół (Bollinger+Keltner release)")
    elif squeeze_on is not None and squeeze_on == 1:
        # Wciąż w squeeze — zmniejsz pewność
        base_confidence -= 0.03
        reasons.append("Squeeze aktywny — niska zmienność, czekaj na wybicie")

    # ---- RSI Divergence (waga: 2) — najsilniejszy sygnał odwrócenia ----
    if rsi_divergence is not None and rsi_divergence != 0:
        if rsi_divergence > 0:
            score += 2
            reasons.append("Bycza dywergencja RSI — cena niższy dół, RSI wyższy dół")
        else:
            score -= 2
            reasons.append("Niedźwiedzia dywergencja RSI — cena wyższy szczyt, RSI niższy szczyt")

    # ---- Wyznacz sygnał i pewność ----
    if score >= 3:
        signal = "BUY"
        confidence = base_confidence + min(0.30, score * 0.06)
    elif score >= 1:
        signal = "BUY"
        confidence = base_confidence + min(0.15, score * 0.04)
    elif score <= -3:
        signal = "SELL"
        confidence = base_confidence + min(0.30, abs(score) * 0.06)
    elif score <= -1:
        signal = "SELL"
        confidence = base_confidence + min(0.15, abs(score) * 0.04)
    else:
        signal = "HOLD"
        confidence = base_confidence

    # Rynek boczny + neutralny score = wyraźny HOLD
    if trend_strength == "boczny" and signal == "HOLD":
        confidence = max(0.50, confidence - 0.05)

    confidence = max(0.50, min(confidence, 0.95))
    reason_text = "; ".join(reasons) if reasons else "Brak wystarczających danych"
    score_text = f"Wynik punktowy: {score:+d}"
    reason_text = score_text + " | " + reason_text

    return {
        "signal": signal,
        "confidence": round(confidence, 2),
        "reason": reason_text,
        "close": close,
    }


def get_live_context(db, symbol: str, timeframe: str = "1h", limit: int = 200) -> Optional[Dict[str, float]]:
    """
    Dynamiczny kontekst rynkowy na podstawie live danych:
    EMA20/EMA50, RSI, ATR, progi RSI (percentyle).
    Wyniki są cache'owane na 55s — kolektor zapisuje nowe dane co 60s.
    """
    # Cache lookup
    cache_key = (symbol, timeframe, limit)
    cached = _live_ctx_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _LIVE_CTX_TTL:
        return cached["result"]

    klines = (
        db.query(Kline)
        .filter(Kline.symbol == symbol, Kline.timeframe == timeframe)
        .order_by(Kline.open_time.desc())
        .limit(limit)
        .all()
    )
    df = _klines_to_df(list(reversed(klines)))
    if df is None or len(df) < 60:
        return None

    df = df.copy()
    df["ema_20"] = ta.ema(df["close"], length=20)
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["rsi_14"] = ta.rsi(df["close"], length=14)
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    try:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is not None:
            macd_col = next((c for c in macd_df.columns if c.startswith("MACD_")), None)
            hist_col = next((c for c in macd_df.columns if c.startswith("MACDh_")), None)
            df["macd"] = macd_df[macd_col] if macd_col else None
            df["macd_hist"] = macd_df[hist_col] if hist_col else None
        else:
            df["macd"] = None
            df["macd_hist"] = None
    except Exception:
        df["macd"] = None
        df["macd_hist"] = None
    # P1-FIX: ADX(14) — siła trendu. Potrzebny przez exit engine do oceny trend_strong.
    try:
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=14)
        if adx_df is not None and "ADX_14" in adx_df.columns:
            df["adx_14"] = adx_df["ADX_14"]
        else:
            df["adx_14"] = None
    except Exception:
        df["adx_14"] = None
    # Supertrend(7,3) — kierunek trendu ATR-based
    try:
        st_df = ta.supertrend(df["high"], df["low"], df["close"], length=7, multiplier=3.0)
        if st_df is not None:
            _st_dir_col = next((c for c in st_df.columns if "SUPERTd" in c), None)
            if _st_dir_col:
                df["supertrend_dir"] = st_df[_st_dir_col]
            else:
                df["supertrend_dir"] = None
        else:
            df["supertrend_dir"] = None
    except Exception:
        df["supertrend_dir"] = None
    # Volume ratio (close/SMA20 wolumenu)
    try:
        df["vol_sma20"] = ta.sma(df["volume"], length=20)
        df["volume_ratio"] = df["volume"] / df["vol_sma20"].replace(0, float("nan"))
    except Exception:
        df["volume_ratio"] = None

    rsi_series = df["rsi_14"].dropna()
    if rsi_series.empty:
        return None

    rsi_buy = float(rsi_series.quantile(0.2))
    rsi_sell = float(rsi_series.quantile(0.8))

    last = df.iloc[-1]
    _adx = float(last["adx_14"]) if "adx_14" in df.columns and pd.notna(last["adx_14"]) else None
    _st_dir = float(last["supertrend_dir"]) if "supertrend_dir" in df.columns and pd.notna(last["supertrend_dir"]) else None
    _vol_ratio = float(last["volume_ratio"]) if "volume_ratio" in df.columns and pd.notna(last["volume_ratio"]) else None
    _macd = float(last["macd"]) if "macd" in df.columns and pd.notna(last["macd"]) else None
    _macd_hist = float(last["macd_hist"]) if "macd_hist" in df.columns and pd.notna(last["macd_hist"]) else None
    _price_change_1h = None
    try:
        if len(df) >= 2 and float(df.iloc[-2]["close"]) > 0:
            _price_change_1h = ((float(last["close"]) - float(df.iloc[-2]["close"])) / float(df.iloc[-2]["close"])) * 100.0
    except Exception:
        _price_change_1h = None
    result = {
        "ema_20": float(last["ema_20"]) if pd.notna(last["ema_20"]) else None,
        "ema_50": float(last["ema_50"]) if pd.notna(last["ema_50"]) else None,
        "rsi": float(last["rsi_14"]) if pd.notna(last["rsi_14"]) else None,
        "atr": float(last["atr_14"]) if pd.notna(last["atr_14"]) else None,
        "rsi_buy": rsi_buy,
        "rsi_sell": rsi_sell,
        "close": float(last["close"]),
        "adx": _adx,                  # P1-FIX: ADX — siła trendu (>25 = silny trend)
        "supertrend_dir": _st_dir,    # P1-FIX: Supertrend (+1 bycze, -1 niedźwiedzie)
        "volume_ratio": _vol_ratio,   # P1-FIX: ratio wolumenu vs SMA20
        "macd": _macd,
        "macd_hist": _macd_hist,
        "price_change_1h": _price_change_1h,
    }
    # Zapisz do cache
    _live_ctx_cache[cache_key] = {"result": result, "ts": _time.time()}
    return result


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _load_timeframe_snapshot(db, symbol: str, timeframe: str, limit: int) -> Optional[Dict[str, Any]]:
    klines = (
        db.query(Kline)
        .filter(Kline.symbol == symbol, Kline.timeframe == timeframe)
        .order_by(Kline.open_time.desc())
        .limit(limit)
        .all()
    )
    df = _klines_to_df(list(reversed(klines)))
    if df is None or len(df) < min(30, limit):
        return None
    indicators = _compute_indicators(df)
    if not indicators:
        return None
    last = df.iloc[-1]
    first = df.iloc[max(0, len(df) - min(len(df), 20))]
    close = _safe_float(indicators.get("close"))
    open_ref = _safe_float(first.get("close"))
    momentum_pct = ((close - open_ref) / open_ref * 100.0) if open_ref > 0 else 0.0
    swing_high = _safe_float(df["high"].tail(20).max(), close)
    swing_low = _safe_float(df["low"].tail(20).min(), close)
    bb_upper = _safe_float(indicators.get("bb_upper"), close)
    bb_lower = _safe_float(indicators.get("bb_lower"), close)
    bb_width_pct = ((bb_upper - bb_lower) / close * 100.0) if close > 0 else 0.0
    support_distance_pct = ((close - swing_low) / close * 100.0) if close > 0 else 0.0
    resistance_distance_pct = ((swing_high - close) / close * 100.0) if close > 0 else 0.0
    trend = "WZROSTOWY"
    if indicators.get("ema_20") is not None and indicators.get("ema_50") is not None:
        trend = "WZROSTOWY" if indicators["ema_20"] >= indicators["ema_50"] else "SPADKOWY"
    return {
        "timeframe": timeframe,
        "close": close,
        "open_time": last["open_time"].isoformat() if "open_time" in last and pd.notna(last["open_time"]) else None,
        "trend": trend,
        "momentum_pct": round(momentum_pct, 4),
        "volatility_pct": round((_safe_float(indicators.get("atr_14")) / close * 100.0) if close > 0 else 0.0, 4),
        "bb_width_pct": round(bb_width_pct, 4),
        "support_distance_pct": round(support_distance_pct, 4),
        "resistance_distance_pct": round(resistance_distance_pct, 4),
        "swing_high": round(swing_high, 8),
        "swing_low": round(swing_low, 8),
        "indicators": indicators,
    }


def build_market_snapshot(
    db,
    symbol: str,
    *,
    mode: str = "demo",
    position: Optional[Any] = None,
    include_orderbook: bool = True,
    lightweight: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Formalny snapshot rynku dla decision engine.
    """
    from backend.database import MarketData, Position
    from backend.binance_client import get_binance_client
    from backend.risk import build_risk_context, evaluate_risk

    sym = (symbol or "").strip().upper().replace("/", "").replace("-", "")
    if not sym:
        return None

    latest = (
        db.query(MarketData)
        .filter(MarketData.symbol == sym)
        .order_by(MarketData.timestamp.desc())
        .first()
    )
    if latest is None:
        return None

    binance = get_binance_client()
    current_price = _safe_float(latest.price)
    bid = _safe_float(latest.bid, current_price)
    ask = _safe_float(latest.ask, current_price)
    spread = max(0.0, ask - bid) if ask > 0 and bid > 0 else 0.0
    spread_pct = (spread / current_price * 100.0) if current_price > 0 else 0.0
    data_age_seconds = max(
        0.0,
        (utc_now_naive() - latest.timestamp).total_seconds() if latest.timestamp else 999999.0,
    )

    tf_limits = (
        {"5m": 120, "1h": 180, "4h": 120}
        if lightweight
        else {"1m": 240, "3m": 180, "5m": 160, "15m": 140, "1h": 220, "4h": 160, "1d": 120}
    )
    timeframe_data: Dict[str, Any] = {}
    for tf, limit in tf_limits.items():
        snap = _load_timeframe_snapshot(db, sym, tf, limit)
        if snap:
            timeframe_data[tf] = snap

    primary_tf = timeframe_data.get("1h") or next(iter(timeframe_data.values()), None)
    low_tf = timeframe_data.get("5m") or timeframe_data.get("3m") or timeframe_data.get("1m")
    high_tf = timeframe_data.get("4h") or timeframe_data.get("1d") or timeframe_data.get("1h")
    if primary_tf is None:
        return None

    indicators_1h = primary_tf.get("indicators") or {}
    signal_hint = _insight_from_indicators(indicators_1h)
    regime = get_market_regime()

    position_row = position
    if position_row is None:
        position_row = (
            db.query(Position)
            .filter(Position.symbol == sym, Position.mode == mode)
            .order_by(Position.opened_at.desc())
            .first()
        )

    qty = _safe_float(getattr(position_row, "quantity", 0.0), 0.0)
    entry_price = _safe_float(getattr(position_row, "entry_price", 0.0), 0.0)
    unrealized_gross = ((current_price - entry_price) * qty) if entry_price > 0 and qty > 0 else 0.0
    stored_total_cost = _safe_float(getattr(position_row, "total_cost", 0.0), 0.0)
    unrealized_net = unrealized_gross - stored_total_cost

    orderbook = None
    orderbook_imbalance = 0.0
    if include_orderbook:
        try:
            orderbook = binance.get_orderbook(sym, limit=10)
            if orderbook:
                bid_depth = sum(_safe_float(level[1]) for level in orderbook.get("bids", []))
                ask_depth = sum(_safe_float(level[1]) for level in orderbook.get("asks", []))
                denom = bid_depth + ask_depth
                orderbook_imbalance = ((bid_depth - ask_depth) / denom) if denom > 0 else 0.0
        except Exception:
            orderbook = None

    exchange_filters = binance.get_allowed_symbols().get(sym, {})
    atr = _safe_float(indicators_1h.get("atr_14"))
    tp_price = _safe_float(getattr(position_row, "planned_tp", 0.0), 0.0)
    sl_price = _safe_float(getattr(position_row, "planned_sl", 0.0), 0.0)
    if tp_price <= 0 and atr > 0:
        tp_price = current_price + atr * 2.2
    if sl_price <= 0 and atr > 0:
        sl_price = current_price - atr * 1.4

    target_for_costs = tp_price if tp_price > 0 else current_price + atr * 2.2 if atr > 0 else current_price
    taker_fee_rate = _safe_float(exchange_filters.get("taker_fee_rate"), 0.001)
    maker_fee_rate = _safe_float(exchange_filters.get("maker_fee_rate"), 0.0)
    economics = estimate_trade_costs(
        price=current_price,
        quantity=max(qty, max(_safe_float(exchange_filters.get("min_qty"), 0.0), 1.0 if current_price < 1 else 0.01)),
        maker_fee_rate=maker_fee_rate,
        taker_fee_rate=taker_fee_rate if taker_fee_rate > 0 else 0.001,
        slippage_bps=5.0,
        spread_bps=max(spread_pct * 100.0, 3.0),
        target_price=target_for_costs,
    )

    if lightweight:
        risk_decision = {
            "allowed": True,
            "risk_score": 0.0,
            "warnings": [],
            "reason_codes": ["LIGHTWEIGHT_SNAPSHOT"],
            "requires_human_review": False,
        }
    else:
        risk_context = build_risk_context(
            db,
            symbol=sym,
            side="SELL" if qty > 0 else "BUY",
            notional=max(current_price * max(qty, 0.0), current_price),
            strategy_name="ai_trader_flow",
            mode=mode,
            signal_summary=signal_hint,
        )
        risk_decision = evaluate_risk(risk_context).to_dict()

    snapshot = {
        "symbol": sym,
        "mode": mode,
        "timestamp": utc_now_naive().isoformat(),
        "source_freshness": {
            "market_data_age_seconds": round(data_age_seconds, 2),
            "is_stale": data_age_seconds > 120.0,
        },
        "market": {
            "price": round(current_price, 8),
            "bid": round(bid, 8),
            "ask": round(ask, 8),
            "spread": round(spread, 8),
            "spread_pct": round(spread_pct, 6),
            "volume": _safe_float(latest.volume),
            "orderbook_imbalance": round(orderbook_imbalance, 6),
            "orderbook": orderbook,
        },
        "timeframes": timeframe_data,
        "trend_low_tf": (low_tf or primary_tf).get("trend") if (low_tf or primary_tf) else "BRAK DANYCH",
        "trend_high_tf": (high_tf or primary_tf).get("trend") if (high_tf or primary_tf) else "BRAK DANYCH",
        "momentum": {
            "low_tf_pct": _safe_float((low_tf or primary_tf).get("momentum_pct")),
            "primary_tf_pct": _safe_float(primary_tf.get("momentum_pct")),
            "high_tf_pct": _safe_float((high_tf or primary_tf).get("momentum_pct")),
        },
        "position": {
            "has_position": bool(position_row and qty > 0),
            "entry_price": round(entry_price, 8) if entry_price > 0 else None,
            "current_qty": round(qty, 8),
            "planned_tp": round(tp_price, 8) if tp_price > 0 else None,
            "planned_sl": round(sl_price, 8) if sl_price > 0 else None,
            "unrealized_gross_pnl": round(unrealized_gross, 8),
            "unrealized_net_pnl": round(unrealized_net, 8),
            "stored_total_cost": round(stored_total_cost, 8),
        },
        "costs": economics,
        "technical_levels": {
            "support_price": (primary_tf or {}).get("swing_low"),
            "resistance_price": (primary_tf or {}).get("swing_high"),
            "distance_to_tp_pct": round(((tp_price - current_price) / current_price * 100.0), 4) if current_price > 0 and tp_price > 0 else None,
            "distance_to_sl_pct": round(((current_price - sl_price) / current_price * 100.0), 4) if current_price > 0 and sl_price > 0 else None,
            "distance_to_break_even_pct": round(((economics["break_even_price"] - current_price) / current_price * 100.0), 4) if current_price > 0 else None,
        },
        "market_regime": regime,
        "risk": risk_decision,
        "signal_hint": signal_hint,
        "exchange_filters": exchange_filters,
        "alerts": {
            "market_stale": data_age_seconds > 120.0,
            "spread_wide": spread_pct > 0.35,
            "trend_conflict": str((low_tf or primary_tf).get("trend") or "").upper() != str((high_tf or primary_tf).get("trend") or "").upper(),
        },
    }
    return snapshot


def _plan_action_label(signal: str, has_position: bool, expected_net_profit: float) -> str:
    signal = (signal or "HOLD").upper()
    if has_position:
        if expected_net_profit <= 0:
            return "HOLD"
        if signal == "SELL":
            return "SELL"
        if signal == "BUY":
            return "HOLD"
        return "HOLD"
    if signal == "BUY" and expected_net_profit > 0:
        return "BUY"
    if signal == "SELL":
        return "WAIT"
    return "WAIT"


def build_trade_plan_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministyczny fallback/hard guard dla planu transakcji.
    """
    market = snapshot.get("market") or {}
    costs = snapshot.get("costs") or {}
    position = snapshot.get("position") or {}
    primary_tf = (snapshot.get("timeframes") or {}).get("1h") or next(iter((snapshot.get("timeframes") or {}).values()), {})
    indicators = primary_tf.get("indicators") or {}
    signal_hint = snapshot.get("signal_hint") or {}
    current_price = _safe_float(market.get("price"))
    atr = _safe_float(indicators.get("atr_14"))
    support_price = _safe_float((snapshot.get("technical_levels") or {}).get("support_price"), current_price)
    resistance_price = _safe_float((snapshot.get("technical_levels") or {}).get("resistance_price"), current_price)
    trend_low = snapshot.get("trend_low_tf") or "BRAK DANYCH"
    trend_high = snapshot.get("trend_high_tf") or "BRAK DANYCH"
    has_position = bool(position.get("has_position"))
    entry_ref = _safe_float(position.get("entry_price"), current_price)
    qty = _safe_float(position.get("current_qty"), 0.0)
    risk = snapshot.get("risk") or {}
    macd_hist = _safe_float(indicators.get("macd_hist"))
    adx = _safe_float(indicators.get("adx"))
    volume_ratio = _safe_float(indicators.get("volume_ratio"), 1.0)
    momentum_primary = _safe_float((snapshot.get("momentum") or {}).get("primary_tf_pct"))
    supertrend_dir = _safe_float(indicators.get("supertrend_dir"))

    if atr <= 0 and current_price > 0:
        atr = current_price * 0.01

    if has_position:
        entry_price = entry_ref
        position_size = qty
    else:
        entry_price = current_price
        min_qty = _safe_float((snapshot.get("exchange_filters") or {}).get("min_qty"), 0.0)
        position_size = max(min_qty, round(50.0 / current_price, 8) if current_price > 0 else min_qty)

    acceptable_entry_range = {
        "low": round(max(0.0, min(entry_price, support_price, current_price - atr * 0.35)), 8),
        "high": round(max(entry_price, min(current_price + atr * 0.15, resistance_price, current_price * 1.0025)), 8),
    }
    take_profit_price = round(max(current_price, resistance_price, entry_price + atr * 2.2), 8)
    stop_loss_price = round(max(0.0, min(entry_price - atr * 1.25, support_price if support_price > 0 else entry_price - atr * 1.25)), 8)
    guard = build_profitability_guard(
        entry_price=entry_price,
        target_price=take_profit_price,
        quantity=max(position_size, 1e-9),
        maker_fee_rate=_safe_float((snapshot.get("exchange_filters") or {}).get("maker_fee_rate"), 0.0),
        taker_fee_rate=0.001,
        slippage_bps=5.0,
        spread_bps=max(_safe_float(market.get("spread_pct")) * 100.0, 3.0),
        min_profit_margin_bps=12.0,
        min_expected_rr=1.2,
        stop_price=stop_loss_price,
    )
    confidence = float(signal_hint.get("confidence") or 0.5)
    if trend_low == trend_high and trend_low in {"WZROSTOWY", "SPADKOWY"}:
        confidence = min(0.95, confidence + 0.06)
    if bool(risk.get("allowed")) is False:
        confidence = max(0.2, confidence - 0.25)

    expected_net_profit = _safe_float(guard.get("expected_net_profit"))
    action = _plan_action_label(str(signal_hint.get("signal") or "HOLD"), has_position, expected_net_profit)
    if not guard.get("eligible"):
        action = "BLOCK" if not has_position else "HOLD"

    if has_position:
        break_even_price = max(_safe_float(costs.get("break_even_price")), entry_price)
        minimal_profit_to_allow_exit = max(_safe_float(costs.get("minimum_profit_price")), break_even_price)
    else:
        break_even_price = _safe_float(guard.get("break_even_price"))
        minimal_profit_to_allow_exit = _safe_float(guard.get("minimum_profit_price"))

    trailing_activation_price = round(max(entry_price, break_even_price) + atr * 0.8, 8)
    trailing_distance = round(max(atr * 0.75, current_price * 0.0025), 8)
    plan_status = "ready"
    invalidation_conditions = []
    reconsult_triggers = []
    if trend_low != trend_high and trend_high != "BRAK DANYCH":
        invalidation_conditions.append("Konflikt trendu między niższym i wyższym interwałem")
    if _safe_float(market.get("spread_pct")) > 0.35:
        invalidation_conditions.append("Spread wzrósł ponad bezpieczny poziom")
    if bool((snapshot.get("market_regime") or {}).get("buy_blocked")) and action == "BUY":
        invalidation_conditions.append("Reżim rynku blokuje wejście BUY")
        action = "BLOCK"
        plan_status = "blocked"
    buy_setup_confirmed = all([
        trend_low == "WZROSTOWY",
        trend_high == "WZROSTOWY",
        momentum_primary > 0,
        macd_hist > 0,
        volume_ratio >= 0.9,
        supertrend_dir >= 0,
        adx >= 18,
    ])
    if not has_position and action == "BUY" and not buy_setup_confirmed:
        invalidation_conditions.append("BUY bez pełnego potwierdzenia trendu, momentum i wolumenu")
        action = "BLOCK"
        plan_status = "blocked"
    reconsult_triggers.extend([
        "Cena wybija poza acceptable_entry_range",
        "Trend 5m/1h odwraca się względem planu",
        "Expected net profit spada poniżej zera",
        "Spread lub slippage rośnie ponad próg ochronny",
        "Pojawia się risk gate lub kill switch",
    ])

    risk_score = round(min(1.0, max(0.0, _safe_float(risk.get("risk_score"), 0.0))), 4)
    trade_quality_score = round(min(1.0, max(0.0, (confidence * 0.55) + (float(guard.get("cost_efficiency_score") or 0.0) * 0.45))), 4)
    plan = {
        "action": action,
        "plan_status": plan_status,
        "justification": signal_hint.get("reason") or "Plan heurystyczny zbudowany na bazie snapshotu rynku.",
        "entry_price": round(entry_price, 8),
        "acceptable_entry_range": acceptable_entry_range,
        "max_entry_slippage": round(max(current_price * 0.0015, atr * 0.15), 8),
        "position_size": round(position_size, 8),
        "take_profit_price": take_profit_price,
        "stop_loss_price": stop_loss_price,
        "break_even_price": round(break_even_price, 8),
        "trailing_activation_price": trailing_activation_price,
        "trailing_distance": trailing_distance,
        "minimal_profit_to_allow_exit": round(minimal_profit_to_allow_exit, 8),
        "expected_gross_profit": round(_safe_float(guard.get("expected_gross_profit")), 8),
        "expected_total_cost": round(_safe_float(guard.get("total_cost")), 8),
        "expected_net_profit": round(expected_net_profit, 8),
        "expected_net_profit_pct": round(_safe_float(guard.get("expected_net_profit_pct")), 8),
        "expected_time_horizon": "1h-4h" if trend_high == "WZROSTOWY" else "15m-1h",
        "confidence_score": round(confidence, 4),
        "risk_score": risk_score,
        "trade_quality_score": trade_quality_score,
        "cost_efficiency_score": round(_safe_float(guard.get("cost_efficiency_score")), 4),
        "rr_ratio": round(_safe_float(guard.get("rr_ratio")), 4),
        "plan_invalidation_conditions": invalidation_conditions,
        "reconsult_triggers": reconsult_triggers,
        "requires_revision": False,
        "invalidation_reason": None,
        "last_consulted_at": utc_now_naive().isoformat(),
    }
    return plan


def _trade_plan_prompt(snapshot: Dict[str, Any]) -> str:
    return (
        "Jesteś AI decision engine dla realnego tradera kryptowalut. "
        "Na podstawie snapshotu rynku zwróć WYŁĄCZNIE JSON z planem transakcji. "
        "Pole action musi być jednym z: BUY, SELL, HOLD, WAIT, REDUCE, BLOCK. "
        "Uwzględnij koszty, break-even, expected_net_profit, invalidation i reconsult_triggers. "
        "Nie wolno zwrócić planu z BUY/SELL, jeśli expected_net_profit <= 0. "
        "Dane:\n"
        + json.dumps(snapshot, ensure_ascii=False)
    )


def _normalize_trade_plan(plan: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(fallback)
    normalized.update({k: v for k, v in plan.items() if v is not None})
    action = str(normalized.get("action") or "WAIT").upper()
    if action not in {"BUY", "SELL", "HOLD", "WAIT", "REDUCE", "BLOCK"}:
        action = "WAIT"
    normalized["action"] = action
    expected_net = _safe_float(normalized.get("expected_net_profit"))
    if action in {"BUY", "SELL"} and expected_net <= 0:
        normalized["action"] = "BLOCK" if action == "BUY" else "HOLD"
        normalized["plan_status"] = "blocked"
        normalized["invalidation_reason"] = "AI zwróciła plan bez dodatniego expected net profit"
    normalized["requires_revision"] = bool(normalized.get("requires_revision"))
    normalized["last_consulted_at"] = normalized.get("last_consulted_at") or utc_now_naive().isoformat()
    return normalized


def _parse_trade_plan_response(text: str, provider: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    extracted = _extract_json_from_text(text)
    if not extracted:
        log_to_db("ERROR", "analysis", f"{provider}: brak JSON planu transakcji")
        return fallback
    try:
        raw = json.loads(extracted)
        if isinstance(raw, list) and raw:
            raw = raw[0]
        if isinstance(raw, dict):
            raw["ai_provider"] = provider.lower()
            return _normalize_trade_plan(raw, fallback)
    except json.JSONDecodeError as exc:
        log_to_db("ERROR", "analysis", f"{provider}: błąd parsowania planu JSON: {exc}")
    return fallback


def _compute_quantum_weights(db, symbols: List[str], timeframe: str = "1h", limit: int = 200) -> Dict[str, Dict[str, float]]:
    """
    Prosta analiza 'kwantowa' (proxy): risk-parity/volatility weights na podstawie zwrotów.
    """
    data = {}
    for symbol in symbols:
        klines = (
            db.query(Kline)
            .filter(Kline.symbol == symbol, Kline.timeframe == timeframe)
            .order_by(Kline.open_time.desc())
            .limit(limit)
            .all()
        )
        df = _klines_to_df(list(reversed(klines)))
        if df is None or len(df) < 30:
            continue
        returns = df["close"].pct_change().dropna()
        vol = float(returns.std()) if not returns.empty else None
        if vol and vol > 0:
            data[symbol] = {"volatility": vol}

    if not data:
        return {}

    # Risk parity weights = 1/vol
    inv_vol = {s: 1.0 / v["volatility"] for s, v in data.items() if v.get("volatility")}
    total = sum(inv_vol.values()) if inv_vol else 0.0
    weights = {}
    for s, inv in inv_vol.items():
        w = inv / total if total > 0 else 0.0
        weights[s] = {
            "weight": round(w, 4),
            "volatility": round(data[s]["volatility"], 6),
        }
    return weights


def _get_htf_bias(db, symbol: str, htf: str = "4h", limit: int = 60) -> float:
    """Zwraca bias wyższego TF: +1 (wzrostowy), -1 (spadkowy), 0 (brak danych).

    Używany jako modyfikator pewności sygnałów 1h.
    Graceful fallback gdy brak danych 4h w DB (np. przed pierwszym uruchomieniem).
    """
    try:
        klines = (
            db.query(Kline)
            .filter(Kline.symbol == symbol, Kline.timeframe == htf)
            .order_by(Kline.open_time.desc())
            .limit(limit)
            .all()
        )
        df = _klines_to_df(list(reversed(klines)))
        if df is None or len(df) < 30:
            return 0.0
        df = df.copy()
        df["ema_20"] = ta.ema(df["close"], length=20)
        df["ema_50"] = ta.ema(df["close"], length=50)
        df["rsi_14"] = ta.rsi(df["close"], length=14)
        last = df.iloc[-1]
        ema_20 = float(last["ema_20"]) if pd.notna(last.get("ema_20")) else None
        ema_50 = float(last["ema_50"]) if pd.notna(last.get("ema_50")) else None
        rsi = float(last["rsi_14"]) if pd.notna(last.get("rsi_14")) else None
        score = 0
        if ema_20 is not None and ema_50 is not None:
            score += 1 if ema_20 > ema_50 else -1
        if rsi is not None:
            if rsi < 40:
                score += 1
            elif rsi > 60:
                score -= 1
        return float(score) / 2.0  # normalizuj do [-1, 1]
    except Exception:
        return 0.0


def generate_market_insights(db, symbols: List[str], timeframe: str = "1h", limit: int = 200) -> List[Dict]:
    """Generuje listę insightów na bazie danych z DB."""
    insights: List[Dict] = []
    quantum = _compute_quantum_weights(db, symbols, timeframe=timeframe, limit=limit)
    # Zbierz bias 4h gdy timeframe=1h (multi-TF konfluencja)
    htf = "4h" if timeframe == "1h" else None

    # Online sentiment (pobierz raz na cały batch — cache 5-10 min)
    fear_greed = _fetch_fear_greed_index()
    coingecko = _fetch_coingecko_global()

    for symbol in symbols:
        klines = (
            db.query(Kline)
            .filter(Kline.symbol == symbol, Kline.timeframe == timeframe)
            .order_by(Kline.open_time.desc())
            .limit(limit)
            .all()
        )

        df = _klines_to_df(list(reversed(klines)))
        if df is None:
            continue

        indicators = _compute_indicators(df)
        if not indicators:
            continue

        insight = _insight_from_indicators(indicators)

        # Multi-TF konfluencja: jeśli 4h potwierdza 1h → większa pewność
        htf_bias = 0.0
        htf_note = ""
        if htf:
            htf_bias = _get_htf_bias(db, symbol, htf=htf)
            if htf_bias > 0 and insight["signal"] == "BUY":
                insight["confidence"] = min(0.95, insight["confidence"] + 0.05)
                htf_note = " | 4h: ⬆ potwierdza BUY"
            elif htf_bias < 0 and insight["signal"] == "SELL":
                insight["confidence"] = min(0.95, insight["confidence"] + 0.05)
                htf_note = " | 4h: ⬇ potwierdza SELL"
            elif htf_bias != 0:
                # Sprzeczne TF — zmniejsz pewność
                insight["confidence"] = max(0.50, insight["confidence"] - 0.04)
                htf_note = f" | 4h: {'\u2b06' if htf_bias > 0 else '\u2b07'} sprzeczny z {insight['signal']}"
        if htf_note:
            insight["reason"] = insight["reason"] + htf_note

        # ---- Online AI Sentiment (Fear & Greed Index + CoinGecko) ----
        online_notes: list[str] = []

        if fear_greed is not None:
            fg = int(fear_greed)
            # Kontekst trendu: htf_bias < 0 = trend spadkowy (4h bearish)
            # F&G serve as CONTRARIAN signal TYLKO gdy rynek nie jest w silnym trendzie
            bearish_trend = htf_bias < 0
            bullish_trend = htf_bias > 0
            # Dodatkowy wskaźnik siły trendu z indicators
            supertrend_down = float(indicators.get("supertrend_dir", 0) or 0) < 0
            obv_down = float(indicators.get("obv_trend", 0) or 0) < 0

            if fg <= 20:
                # Extreme Fear:
                # - jeśli rynek w силным trendzie spadkowym → OSTRZEŻENIE przed BUY, nie zachęcaj
                # - jeśli rynek neutralny lub wzrostowy → kontrariański sygnał BUY
                if bearish_trend and supertrend_down and obv_down:
                    # Rynek spada z siłą - Extreme Fear = panika, nie dno
                    if insight["signal"] == "BUY":
                        insight["confidence"] = max(0.50, insight["confidence"] - 0.05)
                    online_notes.append(f"F&G={fg}🔴EkstrStrah+TrendSpad(UWAGA-BUY)")
                else:
                    # Brak potwierdzenia trendu spadkowego → kontrariański BUY ma sens
                    if insight["signal"] == "BUY":
                        insight["confidence"] = min(0.95, insight["confidence"] + 0.04)
                    online_notes.append(f"F&G={fg}🔴EkstrStrah(kontr.BUY)")
            elif fg <= 40:
                if insight["signal"] == "BUY" and not (bearish_trend and supertrend_down):
                    insight["confidence"] = min(0.95, insight["confidence"] + 0.02)
                elif insight["signal"] == "BUY" and bearish_trend and supertrend_down:
                    insight["confidence"] = max(0.50, insight["confidence"] - 0.02)
                online_notes.append(f"F&G={fg}🟠Strach")
            elif fg >= 80:
                # Extreme Greed — kontrariański sygnał SELL
                if insight["signal"] == "SELL":
                    insight["confidence"] = min(0.95, insight["confidence"] + 0.04)
                elif insight["signal"] == "BUY":
                    insight["confidence"] = max(0.50, insight["confidence"] - 0.04)
                online_notes.append(f"F&G={fg}🟢EkstrChciwość(SELL)")
            elif fg >= 60:
                if insight["signal"] == "SELL":
                    insight["confidence"] = min(0.95, insight["confidence"] + 0.02)
                online_notes.append(f"F&G={fg}🟡Chciwość")
            else:
                online_notes.append(f"F&G={fg}⚪Neutralny")

        if coingecko is not None:
            btc_dom = coingecko.get("btc_dominance")
            mc_chg = coingecko.get("market_cap_change_24h")
            if btc_dom is not None:
                dom = float(btc_dom)
                # Wysoka dominacja BTC → altcoiny pod presją
                sym_norm = (symbol or "").strip().upper().replace("/", "").replace("-", "")
                is_btc = sym_norm.startswith("BTC")
                if dom > 60 and not is_btc:
                    insight["confidence"] = max(0.50, insight["confidence"] - 0.02)
                    online_notes.append(f"BTC.dom={dom:.0f}%↑(alt↓)")
                elif dom < 40:
                    insight["confidence"] = min(0.95, insight["confidence"] + 0.02)
                    online_notes.append(f"BTC.dom={dom:.0f}%↓(altseason)")
                else:
                    online_notes.append(f"BTC.dom={dom:.0f}%")
            if mc_chg is not None:
                chg = float(mc_chg)
                if chg > 3.0 and insight["signal"] == "BUY":
                    insight["confidence"] = min(0.95, insight["confidence"] + 0.02)
                    online_notes.append(f"MCap24h={chg:+.1f}%↑")
                elif chg < -3.0 and insight["signal"] == "SELL":
                    insight["confidence"] = min(0.95, insight["confidence"] + 0.02)
                    online_notes.append(f"MCap24h={chg:+.1f}%↓")
                elif abs(chg) > 1.0:
                    online_notes.append(f"MCap24h={chg:+.1f}%")

        if online_notes:
            insight["reason"] = insight["reason"] + " | " + " ".join(online_notes)

        snapshot = build_market_snapshot(db, symbol, mode="demo")
        plan = consult_trade_plan(snapshot) if snapshot else None

        insights.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal_type": insight["signal"],
                "confidence": insight["confidence"],
                "price": indicators.get("close"),
                "indicators": indicators,
                "reason": insight["reason"],
                "quantum": quantum.get(symbol),
                "htf_bias": htf_bias,
                "fear_greed": fear_greed,
                "coingecko": coingecko,
                "snapshot": snapshot,
                "plan": plan,
                "timestamp": utc_now_naive().isoformat(),
            }
        )

    return insights


def _send_telegram_message(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except Exception as exc:
        log_exception("analysis._send_telegram_message", exc)


def _merge_ranges_with_insights(insights: List[Dict], ranges: List[Dict]) -> List[Dict]:
    range_map = {r.get("symbol"): r for r in ranges}
    for ins in insights:
        r = range_map.get(ins.get("symbol"))
        if r:
            ins["range"] = _apply_action_logic(ins, r)
    return insights


def _apply_action_logic(insight: Dict, r: Dict) -> Dict:
    """
    Wymuś konkretne decyzje KUP/SPRZEDAJ na podstawie live ceny i zakresów.
    Zasady:
    - jeśli cena >= sell_low -> SPRZEDAJ TERAZ
    - jeśli cena w BUY range -> KUP TERAZ
    - w przeciwnym razie CZEKAJ i pokazuj cel (buy_high / sell_low)
    """
    def _to_float(v):
        try:
            return float(v)
        except Exception:
            return None

    price = _to_float(insight.get("price") or insight.get("indicators", {}).get("close") or 0) or 0.0
    buy_low = _to_float(r.get("buy_low"))
    buy_high = _to_float(r.get("buy_high"))
    sell_low = _to_float(r.get("sell_low"))
    sell_high = _to_float(r.get("sell_high"))

    if buy_low is not None and buy_high is not None and buy_low <= price <= buy_high:
        r["buy_action"] = "KUP TERAZ"
        r["buy_target"] = price
    else:
        r["buy_action"] = "CZEKAJ"
        r["buy_target"] = buy_high

    if sell_low is not None and price >= sell_low:
        r["sell_action"] = "SPRZEDAJ TERAZ"
        r["sell_target"] = price
    else:
        r["sell_action"] = "CZEKAJ"
        r["sell_target"] = sell_low

    return r


def _fallback_ranges(insights: List[Dict]) -> List[Dict]:
    ranges = []
    for ins in insights:
        price = ins.get("price") or 0
        # Prosty fallback: +/- 2% od ceny
        buy_low = price * 0.98
        buy_high = price * 0.99
        sell_low = price * 1.01
        sell_high = price * 1.02
        buy_action = "KUP TERAZ" if buy_low <= price <= buy_high else "CZEKAJ"
        sell_action = "SPRZEDAJ TERAZ" if sell_low <= price <= sell_high else "CZEKAJ"
        buy_target = round(buy_high, 6)
        sell_target = round(sell_low, 6)
        ranges.append({
            "symbol": ins.get("symbol"),
            "buy_low": round(buy_low, 6),
            "buy_high": round(buy_high, 6),
            "sell_low": round(sell_low, 6),
            "sell_high": round(sell_high, 6),
            "buy_action": buy_action,
            "buy_target": buy_target,
            "sell_action": sell_action,
            "sell_target": sell_target,
            "comment": "Zakresy wyliczone automatycznie na bazie ceny"
        })
    return ranges


def _heuristic_ranges(insights: List[Dict]) -> List[Dict]:
    """
    Wielowskaźnikowa analiza techniczna: ATR + Bollinger + ADX + Stochastic + wolumen.
    Zastępuje LLM — deterministyczna, kosztem zero, latencja 0ms.
    """

    def _to_float(v):
        try:
            return float(v)
        except Exception:
            return None

    ranges: List[Dict] = []
    for ins in insights:
        ind = ins.get("indicators") or {}
        symbol = ins.get("symbol")
        price = _to_float(ins.get("price") or ind.get("close")) or 0.0
        atr = _to_float(ind.get("atr_14")) or 0.0
        bb_lower = _to_float(ind.get("bb_lower"))
        bb_upper = _to_float(ind.get("bb_upper"))
        ema_20 = _to_float(ind.get("ema_20"))
        ema_50 = _to_float(ind.get("ema_50"))
        rsi = _to_float(ind.get("rsi_14"))
        adx = _to_float(ind.get("adx"))
        stoch_k = _to_float(ind.get("stoch_k"))
        volume_ratio = _to_float(ind.get("volume_ratio"))
        donchian_lower = _to_float(ind.get("donchian_lower"))
        donchian_upper = _to_float(ind.get("donchian_upper"))
        signal = ins.get("signal_type", "HOLD")

        trend_up = (ema_20 is not None and ema_50 is not None and ema_20 > ema_50)
        strong_trend = adx is not None and adx > 25

        # ADX-aware mnożniki ATR:
        # Silny trend (ADX>25) → szersze zakresy (1.5/0.5 * ATR)
        # Rynek boczny (ADX<20) → węższe zakresy (0.9/0.3 * ATR)
        if strong_trend:
            atr_buy_mult_low, atr_buy_mult_high = 1.5, 0.5
            atr_sell_mult_low, atr_sell_mult_high = 0.5, 1.5
        elif adx is not None and adx < 20:
            # Rynek boczny — węższe strefy mean-reversion
            atr_buy_mult_low, atr_buy_mult_high = 0.9, 0.3
            atr_sell_mult_low, atr_sell_mult_high = 0.3, 0.9
        else:
            atr_buy_mult_low, atr_buy_mult_high = 1.2, 0.4
            atr_sell_mult_low, atr_sell_mult_high = 0.6, 1.4

        if atr and atr > 0:
            buy_low = price - (atr_buy_mult_low * atr)
            buy_high = price - (atr_buy_mult_high * atr)
            sell_low = price + (atr_sell_mult_low * atr)
            sell_high = price + (atr_sell_mult_high * atr)
        else:
            buy_low = price * 0.985
            buy_high = price * 0.995
            sell_low = price * 1.005
            sell_high = price * 1.015

        # Zakotwicz do pasm Bollingera
        if bb_lower is not None:
            buy_low = min(buy_low, bb_lower)
            buy_high = min(buy_high, max(bb_lower, (bb_lower + price) / 2))
        if bb_upper is not None:
            sell_high = max(sell_high, bb_upper)
            sell_low = max(sell_low, min(bb_upper, (bb_upper + price) / 2))

        # Zakotwicz do kanałów Donchiana (poziomy kupna/sprzedaży historyczne)
        if donchian_lower is not None and donchian_lower > 0:
            buy_low = min(buy_low, donchian_lower)
        if donchian_upper is not None and donchian_upper > 0:
            sell_high = max(sell_high, donchian_upper)

        # Zakotwicz do poziomów Fibonacciego (38.2% = wsparcie, 61.8% = głębsze wsparcie)
        fib_382 = _to_float(ind.get("fib_382"))
        fib_618 = _to_float(ind.get("fib_618"))
        fib_236 = _to_float(ind.get("fib_236"))
        if fib_618 is not None and fib_618 < price:
            # 61.8% Fib → silne wsparcie → użyj jako buy_low (nie przeładowuj)
            buy_low = min(buy_low, max(fib_618, buy_low * 0.99))
        if fib_382 is not None and fib_382 < price:
            # 38.2% Fib → słabsze wsparcie → buy_high anchor
            buy_high = max(buy_high, min(fib_382, price * 0.999))
        if fib_236 is not None and fib_236 > price:
            # 23.6% Fib powyżej ceny → opor → sell_low anchor
            sell_low = min(sell_low, max(fib_236, price * 1.001))

        # RSI: skrajna wyprzedanie → przesuń strefę kupna bliżej ceny
        if rsi is not None:
            if rsi < 25:
                buy_high = min(buy_high * 1.005, price * 1.001)
            elif rsi > 75:
                sell_low = max(sell_low * 0.995, price * 0.999)

        # Stochastic: wzmocnij strefy przy skrajnych wartościach
        if stoch_k is not None:
            if stoch_k < 15:  # silne wyprzedanie
                buy_high = min(buy_high * 1.003, price)
            elif stoch_k > 85:  # silne wykupienie
                sell_low = max(sell_low * 0.997, price)

        # Korekta kierunkowa (trend EMA)
        if trend_up:
            sell_low *= 1.003
            sell_high *= 1.003
        else:
            buy_low *= 0.997
            buy_high *= 0.997

        # Wolumen: wysoki wolumen przy sygnale BUY → przesuń strefę bliżej ceny
        if volume_ratio is not None and volume_ratio > 1.8:
            if signal == "BUY" and trend_up:
                buy_high = min(buy_high * 1.002, price)
            elif signal == "SELL" and not trend_up:
                sell_low = max(sell_low * 0.998, price)

        # Normalizacja
        buy_low, buy_high = sorted([buy_low, buy_high])
        sell_low, sell_high = sorted([sell_low, sell_high])

        buy_action = "KUP TERAZ" if buy_low <= price <= buy_high else "CZEKAJ"
        sell_action = "SPRZEDAJ TERAZ" if price >= sell_low else "CZEKAJ"
        buy_target = round(price if buy_action == "KUP TERAZ" else buy_high, 8)
        sell_target = round(price if sell_action == "SPRZEDAJ TERAZ" else sell_low, 8)

        # Buduj czytelny komentarz
        vwap_24 = _to_float(ind.get("vwap_24"))
        parts = ["AI Techniczny"]
        if adx is not None:
            parts.append(f"ADX={adx:.0f}({'silny' if strong_trend else 'boczny' if adx < 20 else 'umiar.'})")
        if rsi is not None:
            parts.append(f"RSI={rsi:.0f}")
        if stoch_k is not None:
            parts.append(f"Stoch={stoch_k:.0f}")
        if volume_ratio is not None:
            parts.append(f"Vol={volume_ratio:.1f}x")
        if vwap_24 is not None and price > 0:
            vwap_bias = "↑" if price > vwap_24 * 1.002 else "↓" if price < vwap_24 * 0.998 else "≈"
            parts.append(f"VWAP{vwap_bias}")
        if donchian_lower is not None and donchian_upper is not None:
            dc_range = donchian_upper - donchian_lower
            dc_pos = (price - donchian_lower) / dc_range * 100 if dc_range > 0 else 50
            parts.append(f"DC={dc_pos:.0f}%")
        mfi_val = _to_float(ind.get("mfi_14"))
        if mfi_val is not None:
            parts.append(f"MFI={mfi_val:.0f}")
        obv_val = _to_float(ind.get("obv_trend"))
        if obv_val is not None and obv_val != 0:
            parts.append(f"OBV{'\u2191' if obv_val > 0 else '\u2193'}")
        eng_val = _to_float(ind.get("engulfing"))
        if eng_val is not None and eng_val != 0:
            parts.append(f"Engulf{'\u25b2' if eng_val > 0 else '\u25bc'}")
        st_val = _to_float(ind.get("supertrend_dir"))
        if st_val is not None:
            parts.append(f"ST{'\u2191' if st_val > 0 else '\u2193'}")
        sqz_on = _to_float(ind.get("squeeze_on"))
        sqz_off = _to_float(ind.get("squeeze_off"))
        if sqz_off and sqz_off == 1:
            parts.append("SQZ\u2192")
        elif sqz_on and sqz_on == 1:
            parts.append("SQZ\u23f8")
        div_val = _to_float(ind.get("rsi_divergence"))
        if div_val is not None and div_val != 0:
            parts.append(f"Div{'\u2191' if div_val > 0 else '\u2193'}")
        comment = " | ".join(parts)

        ranges.append(
            {
                "symbol": symbol,
                "buy_low": round(buy_low, 8),
                "buy_high": round(buy_high, 8),
                "sell_low": round(sell_low, 8),
                "sell_high": round(sell_high, 8),
                "buy_action": buy_action,
                "buy_target": buy_target,
                "sell_action": sell_action,
                "sell_target": sell_target,
                "comment": comment,
                "origin": "heuristic",
            }
        )

    return ranges


# ---------------------------------------------------------------------------
# Wspólny prompt i parser JSON dla providerów AI
# ---------------------------------------------------------------------------

_RANGES_SYSTEM_PROMPT = (
    "Jesteś analitykiem rynku kryptowalut. Dla każdej pozycji podaj zakresy "
    "zakupu i sprzedaży na bazie ceny i wskaźników. Zwróć WYŁĄCZNIE JSON "
    "(bez komentarzy, bez markdown fence). Format: "
    '[{"symbol":"BTCUSDT","buy_low":...,"buy_high":...,'
    '"sell_low":...,"sell_high":...,'
    '"buy_action":"KUP TERAZ|CZEKAJ","buy_target":...,'
    '"sell_action":"SPRZEDAJ TERAZ|CZEKAJ","sell_target":...,'
    '"comment":"..."}]'
)


def _extract_json_from_text(text: str) -> Optional[str]:
    """Wyciąga JSON array z odpowiedzi LLM (obsługuje fenced code blocks)."""
    if not text:
        return None
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean = "\n".join(lines).strip()
    start = clean.find("[")
    end = clean.rfind("]")
    if start != -1 and end != -1 and end > start:
        return clean[start : end + 1]
    return clean


def _sanitize_api_keys(msg: str) -> str:
    """Usuwa klucze API z logów."""
    msg = re.sub(r"sk-[^\s]+", "sk-[REDACTED]", msg or "")
    msg = re.sub(r"AIza[^\s]+", "AIza[REDACTED]", msg or "")
    msg = re.sub(r"gsk_[^\s]+", "gsk_[REDACTED]", msg or "")
    return msg


def _parse_ranges_response(text: str, provider: str) -> List[Dict]:
    """Parsuje JSON z odpowiedzi LLM, zwraca listę zakresów z oznaczeniem origin."""
    extracted = _extract_json_from_text(text)
    if not extracted:
        log_to_db("ERROR", "analysis", f"{provider}: brak JSON do parsowania w odpowiedzi")
        return []
    try:
        ranges = json.loads(extracted)
        if isinstance(ranges, list):
            origin_label = f"ai:{provider.lower()}"
            for r in ranges:
                if isinstance(r, dict):
                    r["origin"] = origin_label
            return ranges
    except json.JSONDecodeError as exc:
        log_to_db("ERROR", "analysis", f"{provider}: błąd parsowania JSON: {exc}")
    return []


# ---------------------------------------------------------------------------
# Provider: Google Gemini (darmowy tier)
# ---------------------------------------------------------------------------

def _gemini_ranges(insights: List[Dict], force: bool = False) -> List[Dict]:
    """Generuj zakresy buy/sell za pomocą Google Gemini (darmowy tier)."""
    api_key = (os.getenv("GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return []

    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    backoff_seconds = int(os.getenv("AI_BACKOFF_SECONDS", "600"))
    global _last_gemini_error_ts
    if (not force) and _last_gemini_error_ts and (utc_now_naive() - _last_gemini_error_ts).total_seconds() < backoff_seconds:
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    user_text = _RANGES_SYSTEM_PROMPT + "\n\nDane:\n" + json.dumps(insights, ensure_ascii=False)
    payload = {
        "contents": [{"parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code == 429:
            # P1-FIX: Rate limit — specjalne logowanie + dłuższy backoff
            _last_gemini_error_ts = utc_now_naive()
            log_to_db(
                "WARNING", "analysis",
                f"Gemini HTTP 429 — RATE LIMIT. AI_PROVIDER_RATE_LIMITED. "
                f"FALLBACK_ANALYSIS_ACTIVE. Backoff {backoff_seconds}s → heurystyka ATR/Bollinger."
            )
            return []
        if resp.status_code >= 400:
            _last_gemini_error_ts = utc_now_naive()
            log_to_db("ERROR", "analysis", f"Gemini HTTP {resp.status_code}: {_sanitize_api_keys(resp.text or '')[:220]}")
            return []
        data = resp.json()
        candidates = data.get("candidates", [])
        text = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
        if not text:
            _last_gemini_error_ts = utc_now_naive()
            log_to_db("ERROR", "analysis", "Gemini: pusta odpowiedź")
            return []
        result = _parse_ranges_response(text, "Gemini")
        if result:
            for r in result:
                r["comment"] = r.get("comment", "") + " [Gemini]"
        return result
    except Exception as exc:
        _last_gemini_error_ts = utc_now_naive()
        log_exception("analysis", "Błąd zapytania Gemini", exc)
        return []


# ---------------------------------------------------------------------------
# Provider: Groq (darmowy tier — Llama / Mixtral)
# ---------------------------------------------------------------------------

def _groq_ranges(insights: List[Dict], force: bool = False) -> List[Dict]:
    """Generuj zakresy buy/sell za pomocą Groq (darmowy tier, szybkie LLM)."""
    api_key = (os.getenv("GROQ_API_KEY", "") or "").strip()
    if not api_key:
        return []

    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    backoff_seconds = int(os.getenv("AI_BACKOFF_SECONDS", "600"))
    global _last_groq_error_ts
    if (not force) and _last_groq_error_ts and (utc_now_naive() - _last_groq_error_ts).total_seconds() < backoff_seconds:
        return []

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _RANGES_SYSTEM_PROMPT},
            {"role": "user", "content": "Dane:\n" + json.dumps(insights, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if resp.status_code == 429:
            # P1-FIX: Rate limit — specjalne logowanie + fallback
            _last_groq_error_ts = utc_now_naive()
            log_to_db(
                "WARNING", "analysis",
                f"Groq HTTP 429 — RATE LIMIT. AI_PROVIDER_RATE_LIMITED. "
                f"FALLBACK_ANALYSIS_ACTIVE. Backoff {backoff_seconds}s → heurystyka ATR/Bollinger."
            )
            return []
        if resp.status_code >= 400:
            _last_groq_error_ts = utc_now_naive()
            log_to_db("ERROR", "analysis", f"Groq HTTP {resp.status_code}: {_sanitize_api_keys(resp.text or '')[:220]}")
            return []
        data = resp.json()
        text = ""
        choices = data.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")
        if not text:
            _last_groq_error_ts = utc_now_naive()
            log_to_db("ERROR", "analysis", "Groq: pusta odpowiedź")
            return []
        result = _parse_ranges_response(text, "Groq")
        if result:
            for r in result:
                r["comment"] = r.get("comment", "") + " [Groq]"
        return result
    except Exception as exc:
        _last_groq_error_ts = utc_now_naive()
        log_exception("analysis", "Błąd zapytania Groq", exc)
        return []


# ---------------------------------------------------------------------------
# Provider: Ollama (lokalne LLM — całkowicie darmowe, bez klucza API)
# ---------------------------------------------------------------------------

def _ollama_ranges(insights: List[Dict], force: bool = False) -> List[Dict]:
    """Generuj zakresy buy/sell za pomocą Ollama (lokalne LLM, brak klucza API).

    Przetwarza symbole iteracyjnie (jeden na raz) aby ograniczyć rozmiar
    promptu i czas odpowiedzi na CPU. Czas: ~30-90s / symbol.
    UWAGA: blokuje wątek collectora — zalecane tylko przy AI_PROVIDER=ollama
    na maszynach z GPU lub jako jednorazowa analiza.
    """
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
    base_url = (os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") or "").rstrip("/")
    backoff_seconds = int(os.getenv("AI_BACKOFF_SECONDS", "600"))
    per_symbol_timeout = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
    global _last_ollama_error_ts
    if (not force) and _last_ollama_error_ts and (utc_now_naive() - _last_ollama_error_ts).total_seconds() < backoff_seconds:
        return []

    url = f"{base_url}/v1/chat/completions"
    all_results: List[Dict] = []

    for insight in insights:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _RANGES_SYSTEM_PROMPT},
                {"role": "user", "content": "Dane:\n" + json.dumps([insight], ensure_ascii=False)},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=per_symbol_timeout,
            )
            if resp.status_code >= 400:
                _last_ollama_error_ts = utc_now_naive()
                log_to_db("ERROR", "analysis", f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
                return all_results
            data = resp.json()
            choices = data.get("choices", [])
            text = choices[0].get("message", {}).get("content", "") if choices else ""
            if not text:
                continue
            result = _parse_ranges_response(text, "Ollama")
            for r in result:
                r["comment"] = r.get("comment", "") + f" [Ollama/{model}]"
            all_results.extend(result)
        except requests.exceptions.Timeout:
            log_to_db("WARNING", "analysis", f"Ollama timeout ({per_symbol_timeout}s) dla {insight.get('symbol')} — pomijam symbol")
            continue
        except requests.exceptions.ConnectionError:
            _last_ollama_error_ts = utc_now_naive()
            log_to_db("WARNING", "analysis", f"Ollama niedostępna ({base_url}) — fallback do heurystyki")
            return all_results
        except Exception as exc:
            _last_ollama_error_ts = utc_now_naive()
            log_exception("analysis", "Błąd zapytania Ollama", exc)
            return all_results

    return all_results


# ---------------------------------------------------------------------------
# Provider: OpenAI (płatny)
# ---------------------------------------------------------------------------

def _openai_ranges(insights: List[Dict], force: bool = False) -> List[Dict]:
    api_key = _get_openai_api_key()
    if not api_key:
        return []

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    backoff_seconds = int(os.getenv("OPENAI_BACKOFF_SECONDS", "600"))
    global _last_openai_error_ts
    if (not force) and _last_openai_error_ts and (utc_now_naive() - _last_openai_error_ts).total_seconds() < backoff_seconds:
        return []
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _RANGES_SYSTEM_PROMPT},
            {"role": "user", "content": "Dane: " + json.dumps(insights, ensure_ascii=False)},
        ],
        "max_tokens": 2000,
        "temperature": 0.2,
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=25,
        )
        if resp.status_code >= 400:
            _last_openai_error_ts = utc_now_naive()
            try:
                data = resp.json()
                err = (data or {}).get("error") or {}
                msg = _sanitize_api_keys(str(err.get("message") or resp.text or ""))
                code = err.get("code") or err.get("type") or "openai_error"
                log_to_db("ERROR", "analysis", f"OpenAI HTTP {resp.status_code} ({code}): {msg[:220]}")
            except Exception:
                log_to_db("ERROR", "analysis", f"OpenAI HTTP {resp.status_code}: {_sanitize_api_keys(resp.text or '')[:220]}")
            return []
        data = resp.json()
        # chat/completions zwraca content przez choices[0].message.content
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            text = data.get("output_text") or ""
        if not text:
            return []
        result = _parse_ranges_response(text, "OpenAI")
        if result:
            for r in result:
                r["comment"] = r.get("comment", "") + " [OpenAI]"
        return result
    except Exception as exc:
        _last_openai_error_ts = utc_now_naive()
        log_exception("analysis", "Błąd zapytania/parsing OpenAI ranges", exc)
        return []


def consult_trade_plan(
    snapshot: Dict[str, Any],
    force: bool = False,
    *,
    allow_remote: bool = True,
) -> Dict[str, Any]:
    """
    Hybrydowy bridge: LLM zwraca plan, fallback to plan heurystyczny.
    """
    fallback = build_trade_plan_from_snapshot(snapshot)
    provider = os.getenv("AI_PROVIDER", "auto").strip().lower()
    prompt = _trade_plan_prompt(snapshot)

    def _gemini_plan() -> Dict[str, Any]:
        api_key = (os.getenv("GEMINI_API_KEY", "") or "").strip()
        if not api_key:
            return fallback
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096},
        }
        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code >= 400:
                return fallback
            data = resp.json()
            candidates = data.get("candidates", [])
            text = ""
            if candidates:
                text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []))
            return _parse_trade_plan_response(text, "gemini", fallback) if text else fallback
        except Exception:
            return fallback

    def _groq_plan() -> Dict[str, Any]:
        api_key = (os.getenv("GROQ_API_KEY", "") or "").strip()
        if not api_key:
            return fallback
        payload = {
            "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "messages": [
                {"role": "system", "content": "Zwróć tylko JSON planu transakcji."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=25,
            )
            if resp.status_code >= 400:
                return fallback
            text = (((resp.json() or {}).get("choices") or [{}])[0].get("message") or {}).get("content", "")
            return _parse_trade_plan_response(text, "groq", fallback) if text else fallback
        except Exception:
            return fallback

    def _openai_plan() -> Dict[str, Any]:
        api_key = _get_openai_api_key()
        if not api_key:
            return fallback
        payload = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": "Zwróć tylko JSON planu transakcji."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=25,
            )
            if resp.status_code >= 400:
                return fallback
            text = ((((resp.json() or {}).get("choices") or [{}])[0]).get("message") or {}).get("content", "")
            return _parse_trade_plan_response(text, "openai", fallback) if text else fallback
        except Exception:
            return fallback

    def _ollama_plan() -> Dict[str, Any]:
        base_url = (os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") or "").rstrip("/")
        payload = {
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"),
            "messages": [
                {"role": "system", "content": "Zwróć tylko JSON planu transakcji."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }
        try:
            resp = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=35)
            if resp.status_code >= 400:
                return fallback
            text = ((((resp.json() or {}).get("choices") or [{}])[0]).get("message") or {}).get("content", "")
            return _parse_trade_plan_response(text, "ollama", fallback) if text else fallback
        except Exception:
            return fallback

    if not allow_remote or provider == "heuristic" or provider == "offline":
        plan = fallback
    elif provider == "gemini":
        plan = _gemini_plan()
    elif provider == "groq":
        plan = _groq_plan()
    elif provider == "openai":
        plan = _openai_plan()
    elif provider == "ollama":
        plan = _ollama_plan()
    else:
        plan = _gemini_plan()
        if plan == fallback:
            plan = _groq_plan()
        if plan == fallback:
            plan = _openai_plan()
        if plan == fallback:
            plan = _ollama_plan()
    if plan == fallback:
        plan = dict(fallback)
        plan["ai_provider"] = "heuristic"
    return plan


def evaluate_plan_revision(snapshot: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sprawdza, czy plan wymaga rewizji po zmianie rynku.
    """
    market = snapshot.get("market") or {}
    position = snapshot.get("position") or {}
    current_price = _safe_float(market.get("price"))
    spread_pct = _safe_float(market.get("spread_pct"))
    trend_low = snapshot.get("trend_low_tf")
    trend_high = snapshot.get("trend_high_tf")
    expected_net = _safe_float(plan.get("expected_net_profit"))
    action = str(plan.get("action") or "WAIT").upper()
    entry_price = _safe_float(plan.get("entry_price"), current_price)
    entry_range = plan.get("acceptable_entry_range") or {}
    entry_low = _safe_float(entry_range.get("low"), entry_price)
    entry_high = _safe_float(entry_range.get("high"), entry_price)
    stop_loss_price = _safe_float(plan.get("stop_loss_price"))
    break_even_price = _safe_float(plan.get("break_even_price"))
    has_position = bool(position.get("has_position"))

    triggers: List[str] = []
    if current_price <= 0:
        triggers.append("Brak poprawnej ceny rynkowej")
    if spread_pct > 0.35:
        triggers.append("Spread przekroczył bezpieczny próg")
    if action == "BUY" and (current_price < entry_low or current_price > entry_high):
        triggers.append("Cena wyszła poza akceptowalny zakres wejścia")
    if trend_low and trend_high and trend_low != trend_high and trend_high != "BRAK DANYCH":
        triggers.append("Konflikt trendu między TF")
    if expected_net <= 0:
        triggers.append("Expected net profit przestał być dodatni")
    if has_position and stop_loss_price > 0 and current_price < stop_loss_price:
        triggers.append("Cena spadła poniżej poziomu obrony planu")
    if has_position and break_even_price > 0 and current_price < break_even_price and action not in {"SELL", "REDUCE"}:
        triggers.append("Cena wróciła poniżej break-even planu")

    return {
        "requires_revision": bool(triggers),
        "invalidation_reason": "; ".join(triggers) if triggers else None,
        "triggers": triggers,
    }


def persist_insights_as_signals(db, insights: List[Dict]):
    """Zapisz insighty jako sygnały AI — z oznaczeniem origin zakresu (ai vs heuristic)."""
    for ins in insights:
        # Wzbogać indicators o metadane range (origin, buy_low, sell_low)
        # bez zmiany schematu DB — pola diagnostyczne embedded w JSON
        ind_data = dict(ins.get("indicators") or {})
        rng = ins.get("range")
        if rng:
            ind_data["range_origin"] = rng.get("origin", "unknown")
            ind_data["range_buy_low"] = rng.get("buy_low")
            ind_data["range_sell_low"] = rng.get("sell_low")
        signal = Signal(
            symbol=ins["symbol"],
            signal_type=ins["signal_type"],
            confidence=ins["confidence"],
            price=ins.get("price") or 0.0,
            indicators=json.dumps(ind_data),
            reason=ins.get("reason", ""),
            snapshot_json=json.dumps(ins.get("snapshot")) if ins.get("snapshot") is not None else None,
            plan_json=json.dumps(ins.get("plan")) if ins.get("plan") is not None else None,
            plan_status=((ins.get("plan") or {}).get("plan_status") if isinstance(ins.get("plan"), dict) else "draft") or "draft",
            requires_revision=bool((ins.get("plan") or {}).get("requires_revision")) if isinstance(ins.get("plan"), dict) else False,
            invalidation_reason=((ins.get("plan") or {}).get("invalidation_reason") if isinstance(ins.get("plan"), dict) else None),
            last_consulted_at=utc_now_naive(),
            timestamp=utc_now_naive(),
        )
        db.add(signal)

    db.commit()


def generate_blog_post(db, insights: List[Dict]) -> Optional[BlogPost]:
    """Tworzy wpis blogowy po polsku na bazie insightów."""
    if not insights:
        return None

    title = f"Market Insights: {utc_now_naive().strftime('%Y-%m-%d %H:%M UTC')}"
    summary_lines = []
    content_lines = [
        "## Najważniejsze wnioski rynkowe",
        "",
    ]

    for ins in insights:
        summary_lines.append(
            f"{ins['symbol']}: {ins['signal_type']} (pewność {int(ins['confidence']*100)}%)"
        )
        content_lines.append(
            f"### {ins['symbol']} ({ins['timeframe']})"
        )
        content_lines.append(f"Sygnał: **{ins['signal_type']}**")
        content_lines.append(f"Pewność: **{int(ins['confidence']*100)}%**")
        content_lines.append(f"Uzasadnienie: {ins['reason']}")
        if ins.get("range"):
            r = ins["range"]
            content_lines.append(
                f"Zakres zakupu: **{r.get('buy_low')} - {r.get('buy_high')}**"
            )
            content_lines.append(
                f"Zakres sprzedaży: **{r.get('sell_low')} - {r.get('sell_high')}**"
            )
            if r.get("buy_action"):
                content_lines.append(
                    f"Decyzja kupna: **{r.get('buy_action')}** (cel: {r.get('buy_target')})"
                )
            if r.get("sell_action"):
                content_lines.append(
                    f"Decyzja sprzedaży: **{r.get('sell_action')}** (cel: {r.get('sell_target')})"
                )
            if r.get("comment"):
                content_lines.append(f"Komentarz: {r.get('comment')}")
        if ins.get("quantum"):
            q = ins["quantum"]
            content_lines.append(
                f"Analiza kwantowa: waga portfela **{q.get('weight')}**, zmienność **{q.get('volatility')}**"
            )
        content_lines.append("")

    summary = " | ".join(summary_lines)
    content = "\n".join(content_lines)

    post = BlogPost(
        title=title,
        content=content,
        summary=summary,
        market_insights=json.dumps(insights),
        status="draft",
        created_at=utc_now_naive(),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def maybe_generate_insights_and_blog(db, symbols: List[str], force: bool = False):
    """Generuj insighty i blog co najmniej raz na godzinę (lub natychmiast jeśli force=True)."""
    try:
        if not force:
            latest = db.query(BlogPost).order_by(BlogPost.created_at.desc()).first()
            if latest and (utc_now_naive() - latest.created_at) < timedelta(hours=1):
                return None

            backoff_seconds = int(os.getenv("OPENAI_BACKOFF_SECONDS", "600"))
            global _last_openai_error_ts
            if _last_openai_error_ts and (utc_now_naive() - _last_openai_error_ts).total_seconds() < backoff_seconds:
                return None

        insights = generate_market_insights(db, symbols, timeframe="1h")
        if not insights:
            return None

        # T-18: AI zakresy tylko dla top-N symboli (oszczędność tokenów API).
        # Kryterium sortowania: confidence × max(volume_ratio, 0.5).
        # Reszta watchlisty → heurystyka ATR (szybka, bezkosztowa).
        ai_top_n = int(os.getenv("AI_TOP_SYMBOLS", "5"))
        provider = os.getenv("AI_PROVIDER", "auto").strip().lower()

        if provider in ("heuristic", "offline") or len(insights) <= ai_top_n:
            top_insights = insights
            rest_insights: List[Dict] = []
        else:
            sorted_ins = sorted(
                insights,
                key=lambda ins: float(ins.get("confidence", 0.5)) * max(
                    float(ins.get("indicators", {}).get("volume_ratio") or 1.0), 0.5
                ),
                reverse=True,
            )
            top_insights = sorted_ins[:ai_top_n]
            rest_insights = sorted_ins[ai_top_n:]

        # Heurystyka dla symboli poza top-N (kalkulowana raz, taniej)
        heuristic_ranges_rest = _heuristic_ranges(rest_insights) if rest_insights else []

        if provider in ("heuristic", "offline"):
            ranges = _heuristic_ranges(insights)
        elif provider == "gemini":
            ranges = _gemini_ranges(top_insights, force=force) or _heuristic_ranges(top_insights)
        elif provider == "groq":
            ranges = _groq_ranges(top_insights, force=force) or _heuristic_ranges(top_insights)
        elif provider == "ollama":
            ranges = _ollama_ranges(top_insights, force=force) or _heuristic_ranges(top_insights)
        elif provider == "openai":
            ranges = _openai_ranges(top_insights, force=force) or _heuristic_ranges(top_insights)
        else:
            # auto (default): próbuj kolejno Gemini → Groq → OpenAI → Ollama (lokalne) → heurystyka
            ranges = (
                _gemini_ranges(top_insights, force=force)
                or _groq_ranges(top_insights, force=force)
                or _openai_ranges(top_insights, force=force)
                or _ollama_ranges(top_insights, force=force)
                or _heuristic_ranges(top_insights)
            )

        # Scal zakresy: AI (top-N) + heurystyka (reszta watchlisty)
        ranges = list(ranges) + heuristic_ranges_rest

        insights = _merge_ranges_with_insights(insights, ranges)

        # Log diagnostyczny: ile symboli dostało AI vs heurystykę
        ai_syms = [r.get("symbol") for r in ranges if (r.get("origin") or "").startswith("ai:")]
        heu_syms = [r.get("symbol") for r in ranges if r.get("origin") == "heuristic"]
        log_to_db(
            "INFO", "analysis",
            f"T-18 ranges: AI({provider})={len(ai_syms)} symboli"
            + (f" [{','.join(ai_syms[:5])}{'...' if len(ai_syms)>5 else ''}]" if ai_syms else " [fallback→heuristic]")
            + f"; heuristic={len(heu_syms)} symboli",
            db=db,
        )

        persist_insights_as_signals(db, insights)
        post = generate_blog_post(db, insights)
        log_to_db("INFO", "analysis", f"Wygenerowano Market Insights i wpis bloga (provider={provider})", db=db)
        # Telegram: automatyczna wysyłka tylko jeśli włączona w .env (domyślnie OFF).
        if os.getenv("TELEGRAM_AUTO_INSIGHTS", "false").lower() == "true":
            header = "AI – analiza rynku i decyzje"
            if provider in ("heuristic", "offline"):
                header = "AI (heurystyka) – analiza rynku i decyzje"
            elif provider == "ollama":
                header = f"Ollama ({os.getenv('OLLAMA_MODEL', 'qwen2.5:1.5b')}) – analiza rynku i decyzje"
            elif provider == "openai":
                header = "OpenAI – analiza rynku i decyzje"
            elif provider == "gemini":
                header = "Gemini – analiza rynku i decyzje"
            elif provider == "groq":
                header = "Groq – analiza rynku i decyzje"
            lines = [header]
            for ins in insights:
                r = ins.get("range")
                if r:
                    lines.append(
                        f"- {ins['symbol']}: kupno={r.get('buy_action')} (cel {r.get('buy_target')}), "
                        f"sprzedaż={r.get('sell_action')} (cel {r.get('sell_target')}). "
                        f"BUY {r.get('buy_low')}–{r.get('buy_high')} | SELL {r.get('sell_low')}–{r.get('sell_high')}. "
                        f"Uzasadnienie: {ins.get('reason')}"
                    )
            _send_telegram_message("\n".join(lines))
        return post
    except Exception as exc:
        log_exception("analysis", "Błąd generacji insights/blog", exc, db=db)
        return None
