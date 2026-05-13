"""
Moduł analizy technicznej i generacji bloga.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd
import pandas_ta as ta
import requests

from backend.database import BlogPost, Kline, Signal, utc_now_naive
from backend.system_logger import log_exception, log_to_db

_last_openai_error_ts: Optional[datetime] = None
_last_gemini_error_ts: Optional[datetime] = None
_last_groq_error_ts: Optional[datetime] = None
_last_ollama_error_ts: Optional[datetime] = None

# Cache dla zewnętrznych źródeł danych (bez klucza API)
_fear_greed_cache: dict = {"value": None, "ts": None}
_coingecko_cache: dict = {"data": None, "ts": None}
_FEAR_GREED_TTL = 300  # 5 min
_COINGECKO_TTL = 600  # 10 min


def _fetch_fear_greed_index() -> Optional[int]:
    """Pobiera Fear & Greed Index z alternative.me (darmowe, bez klucza API).

    Wartość 0-100: 0-24 = Extreme Fear, 25-49 = Fear, 50-74 = Greed, 75-100 = Extreme Greed.
    Cache: 5 minut. Fallback: ostatnia znana wartość lub None.
    """
    global _fear_greed_cache
    now = datetime.now(timezone.utc)
    ts = _fear_greed_cache.get("ts")
    if (
        ts
        and (now - ts).total_seconds() < _FEAR_GREED_TTL
        and _fear_greed_cache["value"] is not None
    ):
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
    if (
        ts
        and (now - ts).total_seconds() < _COINGECKO_TTL
        and _coingecko_cache["data"] is not None
    ):
        return _coingecko_cache["data"]
    try:
        resp = requests.get("https://api.coingecko.com/api/v3/global", timeout=4)
        if resp.status_code == 200:
            raw = resp.json().get("data", {})
            result = {
                "btc_dominance": raw.get("btc_dominance"),
                "market_cap_change_24h": raw.get(
                    "market_cap_change_percentage_24h_usd"
                ),
                "total_market_cap_usd": (raw.get("total_market_cap") or {}).get("usd"),
            }
            _coingecko_cache = {"data": result, "ts": now}
            return result
    except Exception:
        pass
    return _coingecko_cache.get("data")


def _get_openai_api_key() -> str:
    key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    # Support keys accidentally wrapped in quotes in `.env`.
    if (key.startswith('"') and key.endswith('"')) or (
        key.startswith("'") and key.endswith("'")
    ):
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
            k_col = next(
                (c for c in stoch.columns if "STOCHk" in c or c.startswith("K_")), None
            )
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
            df["vwap_24"] = (typical * df["volume"]).rolling(24).sum() / df[
                "volume"
            ].rolling(24).sum()
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
            if (
                prev_bearish
                and curr_bullish
                and curr_body_lo < prev_body_lo
                and curr_body_hi > prev_body_hi
            ):
                df.loc[df.index[-1], "engulfing"] = 1.0  # bycze
            elif (
                prev_bullish
                and curr_bearish
                and curr_body_lo < prev_body_lo
                and curr_body_hi > prev_body_hi
            ):
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
            df["high"],
            df["low"],
            df["close"],
            bb_length=20,
            kc_length=20,
            asint=True,
        )
        if sq is not None and not sq.empty:
            if "SQZ_ON" in sq.columns:
                df["squeeze_on"] = sq["SQZ_ON"]
            if "SQZ_OFF" in sq.columns:
                df["squeeze_off"] = sq["SQZ_OFF"]
            # Histogram momentum Squeeze (kierunek wybicia)
            hist_col = next(
                (
                    c
                    for c in sq.columns
                    if sq[c].dtype in ["float64", "float32"]
                    and c not in ("SQZ_ON", "SQZ_OFF", "SQZ_NO")
                ),
                None,
            )
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
        "ema_20",
        "ema_50",
        "rsi_14",
        "atr_14",
        "macd",
        "macd_hist",
        "bb_upper",
        "bb_lower",
        "adx",
        "stoch_k",
        "volume_ratio",
        "price_change_1h",
        "price_change_24h",
        "doji_signal",
        "inside_bar",
        "vwap_24",
        "donchian_lower",
        "donchian_upper",
        "mfi_14",
        "obv_trend",
        "fib_382",
        "fib_618",
        "fib_236",
        "engulfing",
        "supertrend_dir",
        "squeeze_on",
        "squeeze_off",
        "squeeze_hist",
        "rsi_divergence",
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
    doji_signal = indicators.get("doji_signal")  # != 0 → doji pattern
    inside_bar = indicators.get("inside_bar")  # 100 → inside bar (konsolidacja)
    vwap_24 = indicators.get("vwap_24")  # rolling VWAP 24-period
    mfi_14 = indicators.get("mfi_14")  # Money Flow Index (volume-weighted RSI)
    obv_trend = indicators.get("obv_trend")  # +1 akumulacja, -1 dystrybucja
    engulfing = indicators.get("engulfing")  # +1 bycze, -1 niedźwiedzie
    supertrend_dir = indicators.get("supertrend_dir")  # +1 bycze, -1 niedźwiedzie
    squeeze_on = indicators.get("squeeze_on")  # 1 = squeeze aktywny (niska zmienność)
    squeeze_off = indicators.get("squeeze_off")  # 1 = właśnie wyszedł ze squeeze
    squeeze_hist = indicators.get(
        "squeeze_hist"
    )  # momentum kierunek po wyjściu ze squeeze
    rsi_divergence = indicators.get(
        "rsi_divergence"
    )  # +1 bycza, -1 niedźwiedzia dywergencja

    reasons = []
    score = 0  # >0 = BUY, <0 = SELL
    base_confidence = 0.58

    # ---- RSI (waga: 2) ----
    if rsi is not None:
        if rsi < 30:
            score += 2
            reasons.append(f"RSI={rsi:.0f} — skrajne wyprzedanie (SILNY sygnał BUY)")
        elif rsi < 40:
            score += 1
            reasons.append(f"RSI={rsi:.0f} — strefa kupna")
        elif rsi > 70:
            score -= 2
            reasons.append(f"RSI={rsi:.0f} — skrajne wykupienie (SILNY sygnał SELL)")
        elif rsi > 60:
            score -= 1
            reasons.append(f"RSI={rsi:.0f} — strefa sprzedaży")
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
            reasons.append(
                f"MACD hist rosnący ({macd_hist:.4f}), ale MACD ujemny — wczesny sygnał"
            )
        else:
            reasons.append(f"MACD hist malejący ({macd_hist:.4f})")

    # ---- Bollinger Bands (waga: 2) ----
    if close is not None and bb_lower is not None and bb_upper is not None:
        bb_range = bb_upper - bb_lower
        pct_b = (close - bb_lower) / bb_range if bb_range > 0 else 0.5
        if close < bb_lower:
            score += 2
            reasons.append(f"%B={pct_b:.2f} — cena poniżej dolnego BB (rebound BUY)")
        elif pct_b < 0.25:
            score += 1
            reasons.append(f"%B={pct_b:.2f} — cena w dolnej ćwiartce BB")
        elif close > bb_upper:
            score -= 2
            reasons.append(f"%B={pct_b:.2f} — cena powyżej górnego BB (sprzedaż)")
        elif pct_b > 0.75:
            score -= 1
            reasons.append(f"%B={pct_b:.2f} — cena w górnej ćwiartce BB")
        else:
            reasons.append(f"%B={pct_b:.2f} — cena w środku BB")

    # ---- Stochastic %K (waga: 1) ----
    if stoch_k is not None:
        if stoch_k < 20:
            score += 1
            reasons.append(f"Stoch%K={stoch_k:.0f} — wyprzedanie")
        elif stoch_k > 80:
            score -= 1
            reasons.append(f"Stoch%K={stoch_k:.0f} — wykupienie")

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
            score += 1  # nagły spadek = szansa na odbicie
            reasons.append(f"Spadek {pct_1h:.1f}% w 1h — potencjalne odbicie")
        elif pct_1h > 2.0:
            score -= 1  # nagły wzrost = ryzyko korekty
            reasons.append(f"Wzrost {pct_1h:.1f}% w 1h — możliwa korekta")

    # ---- VWAP rolling 24h (waga: 1) ----
    if vwap_24 is not None and close is not None and vwap_24 > 0:
        vwap_diff_pct = (close - vwap_24) / vwap_24 * 100
        if close > vwap_24 * 1.005:
            score += 1
            reasons.append(
                f"Cena +{vwap_diff_pct:.1f}% powyżej VWAP(24) — kupujący dominują"
            )
        elif close < vwap_24 * 0.995:
            score -= 1
            reasons.append(
                f"Cena {vwap_diff_pct:.1f}% poniżej VWAP(24) — sprzedający dominują"
            )
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
            score += 1
            reasons.append(f"MFI={mfi_14:.0f} — skrajny outflow (BUY)")
        elif mfi_14 < 35:
            reasons.append(f"MFI={mfi_14:.0f} — strefa kupna")
        elif mfi_14 > 80:
            score -= 1
            reasons.append(f"MFI={mfi_14:.0f} — skrajny inflow (SELL)")
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
            reasons.append(
                "Supertrend ↑ — trend wzrostowy (silny ATR-based sygnał BUY)"
            )
        else:
            score -= 2
            reasons.append(
                "Supertrend ↓ — trend spadkowy (silny ATR-based sygnał SELL)"
            )

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
            reasons.append(
                "Niedźwiedzia dywergencja RSI — cena wyższy szczyt, RSI niższy szczyt"
            )

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


def get_live_context(
    db, symbol: str, timeframe: str = "1h", limit: int = 200
) -> Optional[Dict[str, float]]:
    """
    Dynamiczny kontekst rynkowy na podstawie live danych.
    Zwraca: EMA20/21/50/200, RSI14, ATR14, MACD hist, volume_ratio, progi RSI.
    """
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
    df["ema_21"] = ta.ema(df["close"], length=21)
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["rsi_14"] = ta.rsi(df["close"], length=14)
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    # EMA200 tylko gdy wystarczająco danych
    if len(df) >= 200:
        df["ema_200"] = ta.ema(df["close"], length=200)
    else:
        df["ema_200"] = None

    # MACD histogram
    try:
        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd_df is not None and "MACDh_12_26_9" in macd_df.columns:
            df["macd_hist"] = macd_df["MACDh_12_26_9"]
        else:
            df["macd_hist"] = None
    except Exception:
        df["macd_hist"] = None

    # Volume ratio: bieżący wolumen / SMA20 wolumenu
    vol_ratio: Optional[float] = None
    if "volume" in df.columns:
        try:
            vol_sma = df["volume"].rolling(20).mean()
            last_vol = df["volume"].iloc[-1]
            last_sma = vol_sma.iloc[-1]
            if pd.notna(last_vol) and pd.notna(last_sma) and last_sma > 0:
                vol_ratio = float(last_vol / last_sma)
        except Exception:
            pass

    rsi_series = df["rsi_14"].dropna()
    if rsi_series.empty:
        return None

    rsi_buy = float(rsi_series.quantile(0.2))
    rsi_sell = float(rsi_series.quantile(0.8))

    last = df.iloc[-1]

    def _f(col: str) -> Optional[float]:
        v = (
            last.get(col)
            if hasattr(last, "get")
            else last[col] if col in df.columns else None
        )
        if v is None:
            return None
        try:
            fv = float(v)
            return fv if pd.notna(fv) else None
        except Exception:
            return None

    return {
        "ema_20": _f("ema_20"),
        "ema_21": _f("ema_21"),
        "ema_50": _f("ema_50"),
        "ema_200": _f("ema_200"),
        "rsi": _f("rsi_14"),
        "atr": _f("atr_14"),
        "macd_hist": _f("macd_hist"),
        "volume_ratio": vol_ratio,
        "rsi_buy": rsi_buy,
        "rsi_sell": rsi_sell,
        "close": float(last["close"]),
    }


def get_regime_indicators(db, symbol: str) -> Optional[Dict]:
    """
    Zbiera wskaźniki z 15m i 1h do wykrywania reżimu rynkowego.
    Zwraca słownik gotowy do przekazania do risk.detect_regime().
    Graceful fallback: jeśli brak 15m, używa 1h dla obu zestawów.
    """
    ctx_15m = get_live_context(db, symbol, timeframe="15m", limit=300)
    ctx_1h = get_live_context(db, symbol, timeframe="1h", limit=300)

    if not ctx_1h and not ctx_15m:
        return None

    c15 = ctx_15m or {}
    c1h = ctx_1h or {}

    price = c1h.get("close") or c15.get("close")
    if not price:
        return None

    # 15m indicators — fallback na 1h gdy brak danych 15m
    ema21_15m = (
        c15.get("ema_21") or c15.get("ema_20") or c1h.get("ema_21") or c1h.get("ema_20")
    )
    ema50_15m = c15.get("ema_50") or c1h.get("ema_50")
    rsi_15m = c15.get("rsi") or c1h.get("rsi")
    macd_hist_15m = c15.get("macd_hist") or c1h.get("macd_hist")
    volume_ratio_15m = c15.get("volume_ratio") or c1h.get("volume_ratio")

    # 1h indicators
    ema21_1h = c1h.get("ema_21") or c1h.get("ema_20")
    ema50_1h = c1h.get("ema_50")
    ema200_1h = c1h.get("ema_200") or ema50_1h  # fallback na EMA50 gdy brak danych
    atr_1h = c1h.get("atr") or c15.get("atr")

    return {
        "price": float(price),
        "ema21_15m": float(ema21_15m) if ema21_15m is not None else None,
        "ema50_15m": float(ema50_15m) if ema50_15m is not None else None,
        "ema21_1h": float(ema21_1h) if ema21_1h is not None else None,
        "ema50_1h": float(ema50_1h) if ema50_1h is not None else None,
        "ema200_1h": float(ema200_1h) if ema200_1h is not None else None,
        "rsi_15m": float(rsi_15m) if rsi_15m is not None else None,
        "macd_hist_15m": float(macd_hist_15m) if macd_hist_15m is not None else None,
        "volume_ratio_15m": (
            float(volume_ratio_15m) if volume_ratio_15m is not None else None
        ),
        "atr_1h": float(atr_1h) if atr_1h is not None else None,
        # Proxies dla wait-status i scoring
        "rsi_1h": c1h.get("rsi"),
        "ema_20_1h": c1h.get("ema_20"),
        "ema_50_1h": ema50_1h,
        "rsi_buy_1h": c1h.get("rsi_buy"),
        "rsi_sell_1h": c1h.get("rsi_sell"),
        "close": float(price),
    }


def _compute_quantum_weights(
    db, symbols: List[str], timeframe: str = "1h", limit: int = 200
) -> Dict[str, Dict[str, float]]:
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


def generate_market_insights(
    db, symbols: List[str], timeframe: str = "1h", limit: int = 200
) -> List[Dict]:
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
            if fg <= 20:
                # Extreme Fear — kontrariański sygnał BUY
                if insight["signal"] == "BUY":
                    insight["confidence"] = min(0.95, insight["confidence"] + 0.04)
                online_notes.append(f"F&G={fg}🔴EkstrStrah(BUY)")
            elif fg <= 40:
                if insight["signal"] == "BUY":
                    insight["confidence"] = min(0.95, insight["confidence"] + 0.02)
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
                sym_norm = (
                    (symbol or "").strip().upper().replace("/", "").replace("-", "")
                )
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

        close_series = [
            float(v) for v in df["close"].tail(30).tolist() if v is not None
        ]
        trend_label = (
            "UP"
            if indicators.get("ema_20", 0) >= indicators.get("ema_50", 0)
            else "DOWN"
        )

        insights.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal_type": insight["signal"],
                "confidence": insight["confidence"],
                "price": indicators.get("close"),
                "candles": close_series,
                "trend": trend_label,
                "indicators": indicators,
                "reason": insight["reason"],
                "quantum": quantum.get(symbol),
                "htf_bias": htf_bias,
                "fear_greed": fear_greed,
                "coingecko": coingecko,
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

    price = (
        _to_float(
            insight.get("price") or insight.get("indicators", {}).get("close") or 0
        )
        or 0.0
    )
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
        ranges.append(
            {
                "symbol": ins.get("symbol"),
                "buy_low": round(buy_low, 6),
                "buy_high": round(buy_high, 6),
                "sell_low": round(sell_low, 6),
                "sell_high": round(sell_high, 6),
                "buy_action": buy_action,
                "buy_target": buy_target,
                "sell_action": sell_action,
                "sell_target": sell_target,
                "comment": "Zakresy wyliczone automatycznie na bazie ceny",
            }
        )
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

        trend_up = ema_20 is not None and ema_50 is not None and ema_20 > ema_50
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
            parts.append(
                f"ADX={adx:.0f}({'silny' if strong_trend else 'boczny' if adx < 20 else 'umiar.'})"
            )
        if rsi is not None:
            parts.append(f"RSI={rsi:.0f}")
        if stoch_k is not None:
            parts.append(f"Stoch={stoch_k:.0f}")
        if volume_ratio is not None:
            parts.append(f"Vol={volume_ratio:.1f}x")
        if vwap_24 is not None and price > 0:
            vwap_bias = (
                "↑"
                if price > vwap_24 * 1.002
                else "↓" if price < vwap_24 * 0.998 else "≈"
            )
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
    """Parsuje JSON z odpowiedzi LLM, zwraca listę zakresów."""
    extracted = _extract_json_from_text(text)
    if not extracted:
        log_to_db(
            "ERROR", "analysis", f"{provider}: brak JSON do parsowania w odpowiedzi"
        )
        return []
    try:
        ranges = json.loads(extracted)
        if isinstance(ranges, list):
            return ranges
    except json.JSONDecodeError as exc:
        log_to_db("ERROR", "analysis", f"{provider}: błąd parsowania JSON: {exc}")
    return []


def _build_ai_input_payload(insights: List[Dict]) -> List[Dict]:
    """Buduje jawny payload dla AI z kluczowymi polami rynkowymi."""
    payload: List[Dict] = []
    for ins in insights or []:
        indicators = ins.get("indicators") or {}
        candles = ins.get("candles") or []
        payload.append(
            {
                "symbol": ins.get("symbol"),
                "timeframe": ins.get("timeframe"),
                "signal_type": ins.get("signal_type"),
                "confidence": ins.get("confidence"),
                "price": ins.get("price"),
                "candles": candles,
                "rsi": indicators.get("rsi_14"),
                "ema20": indicators.get("ema_20"),
                "ema50": indicators.get("ema_50"),
                "volume": indicators.get("volume"),
                "volume_ratio": indicators.get("volume_ratio"),
                "trend": ins.get("trend"),
                "reason": ins.get("reason"),
            }
        )
    return payload


# ---------------------------------------------------------------------------
# Provider: Local Ollama (local-first — zero cost, max privacy)
# ---------------------------------------------------------------------------


def _ollama_ranges(insights: List[Dict], force: bool = False) -> List[Dict]:
    """Generuj zakresy buy/sell za pomocą lokalnego Ollama (local-first)."""
    from backend.ai_orchestrator import _ollama_base_url, _ollama_model  # lazy import

    base_url = _ollama_base_url()
    model = _ollama_model()
    timeout_s = float(
        os.getenv("OLLAMA_TIMEOUT_SECONDS")
        or os.getenv("AI_LOCAL_TIMEOUT_SECONDS")
        or os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", "90")
        or "90"
    )
    backoff_seconds = int(os.getenv("AI_BACKOFF_SECONDS", "120"))

    global _last_ollama_error_ts
    if (
        (not force)
        and _last_ollama_error_ts
        and (utc_now_naive() - _last_ollama_error_ts).total_seconds() < backoff_seconds
    ):
        return []

    ai_payload = _build_ai_input_payload(insights)
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _RANGES_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": "Dane:\n"
                        + json.dumps(ai_payload, ensure_ascii=False),
                    },
                ],
                "stream": False,
                "keep_alive": "10m",
                "options": {"num_predict": 4096, "temperature": 0.2},
            },
            timeout=timeout_s,
        )
        if resp.status_code >= 400:
            _last_ollama_error_ts = utc_now_naive()
            log_to_db(
                "ERROR",
                "analysis",
                f"Ollama HTTP {resp.status_code}: {resp.text[:200]}",
            )
            return []
        data = resp.json()
        text = (data.get("message") or {}).get("content") or ""
        if not text:
            _last_ollama_error_ts = utc_now_naive()
            log_to_db("ERROR", "analysis", "Ollama: pusta odpowiedź")
            return []
        result = _parse_ranges_response(text, "Ollama")
        if result:
            for r in result:
                r["comment"] = r.get("comment", "") + " [Ollama-local]"
        return result
    except Exception as exc:
        _last_ollama_error_ts = utc_now_naive()
        log_exception("analysis", "Błąd zapytania Ollama", exc)
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
    if (
        (not force)
        and _last_gemini_error_ts
        and (utc_now_naive() - _last_gemini_error_ts).total_seconds() < backoff_seconds
    ):
        return []

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    ai_payload = _build_ai_input_payload(insights)
    user_text = (
        _RANGES_SYSTEM_PROMPT
        + "\n\nDane:\n"
        + json.dumps(ai_payload, ensure_ascii=False)
    )
    payload = {
        "contents": [{"parts": [{"text": user_text}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code >= 400:
            _last_gemini_error_ts = utc_now_naive()
            log_to_db(
                "ERROR",
                "analysis",
                f"Gemini HTTP {resp.status_code}: {_sanitize_api_keys(resp.text or '')[:220]}",
            )
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
    if (
        (not force)
        and _last_groq_error_ts
        and (utc_now_naive() - _last_groq_error_ts).total_seconds() < backoff_seconds
    ):
        return []

    ai_payload = _build_ai_input_payload(insights)
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _RANGES_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Dane:\n" + json.dumps(ai_payload, ensure_ascii=False),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code >= 400:
            _last_groq_error_ts = utc_now_naive()
            log_to_db(
                "ERROR",
                "analysis",
                f"Groq HTTP {resp.status_code}: {_sanitize_api_keys(resp.text or '')[:220]}",
            )
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
    base_url = (os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") or "").rstrip(
        "/"
    )
    backoff_seconds = int(os.getenv("AI_BACKOFF_SECONDS", "600"))
    per_symbol_timeout = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
    global _last_ollama_error_ts
    if (
        (not force)
        and _last_ollama_error_ts
        and (utc_now_naive() - _last_ollama_error_ts).total_seconds() < backoff_seconds
    ):
        return []

    url = f"{base_url}/v1/chat/completions"
    all_results: List[Dict] = []

    for insight in _build_ai_input_payload(insights):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _RANGES_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Dane:\n" + json.dumps([insight], ensure_ascii=False),
                },
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
                log_to_db(
                    "ERROR",
                    "analysis",
                    f"Ollama HTTP {resp.status_code}: {resp.text[:200]}",
                )
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
            log_to_db(
                "WARNING",
                "analysis",
                f"Ollama timeout ({per_symbol_timeout}s) dla {insight.get('symbol')} — pomijam symbol",
            )
            continue
        except requests.exceptions.ConnectionError:
            _last_ollama_error_ts = utc_now_naive()
            log_to_db(
                "WARNING",
                "analysis",
                f"Ollama niedostępna ({base_url}) — fallback do heurystyki",
            )
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

    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    backoff_seconds = int(os.getenv("OPENAI_BACKOFF_SECONDS", "600"))
    global _last_openai_error_ts
    if (
        (not force)
        and _last_openai_error_ts
        and (utc_now_naive() - _last_openai_error_ts).total_seconds() < backoff_seconds
    ):
        return []
    ai_payload = _build_ai_input_payload(insights)
    payload = {
        "model": model,
        "input": (
            _RANGES_SYSTEM_PROMPT
            + "\nDane: "
            + json.dumps(ai_payload, ensure_ascii=False)
        ),
    }

    try:
        resp = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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
                log_to_db(
                    "ERROR",
                    "analysis",
                    f"OpenAI HTTP {resp.status_code} ({code}): {msg[:220]}",
                )
            except Exception:
                log_to_db(
                    "ERROR",
                    "analysis",
                    f"OpenAI HTTP {resp.status_code}: {_sanitize_api_keys(resp.text or '')[:220]}",
                )
            return []
        data = resp.json()
        text = data.get("output_text")
        if not text:
            output = data.get("output", [])
            parts = []
            for item in output:
                for c in item.get("content", []):
                    if c.get("type") == "output_text" and c.get("text"):
                        parts.append(c["text"])
            text = "\n".join(parts)
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


def persist_insights_as_signals(db, insights: List[Dict]):
    """Zapisz insighty jako sygnały AI."""
    for ins in insights:
        signal = Signal(
            symbol=ins["symbol"],
            signal_type=ins["signal_type"],
            confidence=ins["confidence"],
            price=ins.get("price") or 0.0,
            indicators=json.dumps(ins.get("indicators", {})),
            reason=ins.get("reason", ""),
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
        content_lines.append(f"### {ins['symbol']} ({ins['timeframe']})")
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
            if (
                _last_openai_error_ts
                and (utc_now_naive() - _last_openai_error_ts).total_seconds()
                < backoff_seconds
            ):
                return None

        insights = generate_market_insights(db, symbols, timeframe="1h")
        if not insights:
            return None

        provider = os.getenv("AI_PROVIDER", "auto").strip().lower()
        if provider in ("heuristic", "offline"):
            ranges = _heuristic_ranges(insights)
        elif provider == "gemini":
            ranges = _gemini_ranges(insights, force=force) or _heuristic_ranges(
                insights
            )
        elif provider == "groq":
            ranges = _groq_ranges(insights, force=force) or _heuristic_ranges(insights)
        elif provider == "ollama":
            ranges = _ollama_ranges(insights, force=force) or _heuristic_ranges(
                insights
            )
        elif provider == "openai":
            ranges = _openai_ranges(insights, force=force) or _heuristic_ranges(
                insights
            )
        else:
            # auto (default): próbuj kolejno Ollama → Gemini → Groq → OpenAI → heurystyka
            ranges = (
                _ollama_ranges(insights, force=force)
                or _gemini_ranges(insights, force=force)
                or _groq_ranges(insights, force=force)
                or _openai_ranges(insights, force=force)
                or _heuristic_ranges(insights)
            )

        insights = _merge_ranges_with_insights(insights, ranges)

        persist_insights_as_signals(db, insights)
        post = generate_blog_post(db, insights)
        log_to_db(
            "INFO",
            "analysis",
            f"Wygenerowano Market Insights i wpis bloga (provider={provider})",
            db=db,
        )
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


def get_ai_providers_status() -> List[Dict]:
    """Zwraca aktualny status każdego AI providera (backoff / ok / unconfigured).

    Używane przez /api/account/ai-status i panel diagnostyczny.
    """
    backoff_seconds = int(os.getenv("AI_BACKOFF_SECONDS", "600"))
    now = utc_now_naive()

    def _provider_status(name: str, env_key: str, last_error_ts) -> Dict:
        has_key = bool(os.getenv(env_key, "").strip())
        if not has_key:
            return {"name": name, "status": "unconfigured", "label": "brak klucza"}
        if last_error_ts and (now - last_error_ts).total_seconds() < backoff_seconds:
            remaining = int(backoff_seconds - (now - last_error_ts).total_seconds())
            return {
                "name": name,
                "status": "backoff",
                "label": f"backoff {remaining}s",
                "last_error": last_error_ts.isoformat() if last_error_ts else None,
            }
        return {"name": name, "status": "ok", "label": "aktywny"}

    ollama_url = os.getenv("OLLAMA_URL", "") or os.getenv("OLLAMA_BASE_URL", "")
    ollama_configured = (
        bool(ollama_url.strip()) or os.getenv("USE_OLLAMA", "false").lower() == "true"
    )
    if not ollama_configured:
        ollama_entry: Dict = {
            "name": "ollama",
            "status": "unconfigured",
            "label": "brak konfiguracji",
        }
    elif (
        _last_ollama_error_ts
        and (now - _last_ollama_error_ts).total_seconds() < backoff_seconds
    ):
        remaining = int(backoff_seconds - (now - _last_ollama_error_ts).total_seconds())
        ollama_entry = {
            "name": "ollama",
            "status": "backoff",
            "label": f"backoff {remaining}s",
        }
    else:
        ollama_entry = {"name": "ollama", "status": "ok", "label": "aktywny"}

    return [
        _provider_status("openai", "OPENAI_API_KEY", _last_openai_error_ts),
        _provider_status("gemini", "GEMINI_API_KEY", _last_gemini_error_ts),
        _provider_status("groq", "GROQ_API_KEY", _last_groq_error_ts),
        ollama_entry,
    ]
