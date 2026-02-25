"""
Moduł analizy technicznej i generacji bloga.
"""
from __future__ import annotations

from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json
import os
import requests
import re

import pandas as pd
import pandas_ta as ta

from backend.database import Kline, Signal, BlogPost
from backend.system_logger import log_to_db, log_exception

_last_openai_error_ts: Optional[datetime] = None


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

    last = df.iloc[-1]
    for key in ["ema_20", "ema_50", "rsi_14", "atr_14", "macd", "macd_hist", "bb_upper", "bb_lower"]:
        if key in df.columns and pd.notna(last.get(key)):
            indicators[key] = float(last[key])

    indicators["close"] = float(last["close"])
    return indicators


def _insight_from_indicators(indicators: Dict[str, float]) -> Dict[str, str]:
    """Proste wnioski po polsku na bazie wskaźników."""
    rsi = indicators.get("rsi_14")
    ema_20 = indicators.get("ema_20")
    ema_50 = indicators.get("ema_50")
    macd_hist = indicators.get("macd_hist")
    close = indicators.get("close")

    reasons = []
    signal = "HOLD"
    confidence = 0.6

    if rsi is not None:
        if rsi < 30:
            reasons.append("RSI wskazuje na wyprzedanie")
            signal = "BUY"
            confidence += 0.15
        elif rsi > 70:
            reasons.append("RSI wskazuje na wykupienie")
            signal = "SELL"
            confidence += 0.15
        else:
            reasons.append("RSI w neutralnej strefie")

    if ema_20 is not None and ema_50 is not None:
        if ema_20 > ema_50:
            reasons.append("EMA 20 jest powyżej EMA 50 (trend wzrostowy)")
            if signal == "HOLD":
                signal = "BUY"
            confidence += 0.1
        else:
            reasons.append("EMA 20 poniżej EMA 50 (trend spadkowy)")
            if signal == "HOLD":
                signal = "SELL"
            confidence += 0.1

    if macd_hist is not None:
        if macd_hist > 0:
            reasons.append("MACD potwierdza momentum wzrostowe")
            if signal == "HOLD":
                signal = "BUY"
            confidence += 0.05
        elif macd_hist < 0:
            reasons.append("MACD sygnalizuje momentum spadkowe")
            if signal == "HOLD":
                signal = "SELL"
            confidence += 0.05

    # Wzmocnij sygnały Bollinger
    bb_upper = indicators.get("bb_upper")
    bb_lower = indicators.get("bb_lower")
    if close is not None and bb_lower is not None and bb_upper is not None:
        if close < bb_lower:
            reasons.append("Cena poniżej dolnego pasma Bollingera")
            signal = "BUY"
            confidence += 0.1
        elif close > bb_upper:
            reasons.append("Cena powyżej górnego pasma Bollingera")
            signal = "SELL"
            confidence += 0.1

    confidence = max(0.55, min(confidence, 0.95))
    reason_text = "; ".join(reasons) if reasons else "Brak wystarczających danych do analizy"

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
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["rsi_14"] = ta.rsi(df["close"], length=14)
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)

    rsi_series = df["rsi_14"].dropna()
    if rsi_series.empty:
        return None

    rsi_buy = float(rsi_series.quantile(0.2))
    rsi_sell = float(rsi_series.quantile(0.8))

    last = df.iloc[-1]
    return {
        "ema_20": float(last["ema_20"]) if pd.notna(last["ema_20"]) else None,
        "ema_50": float(last["ema_50"]) if pd.notna(last["ema_50"]) else None,
        "rsi": float(last["rsi_14"]) if pd.notna(last["rsi_14"]) else None,
        "atr": float(last["atr_14"]) if pd.notna(last["atr_14"]) else None,
        "rsi_buy": rsi_buy,
        "rsi_sell": rsi_sell,
        "close": float(last["close"]),
    }


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


def generate_market_insights(db, symbols: List[str], timeframe: str = "1h", limit: int = 200) -> List[Dict]:
    """Generuje listę insightów na bazie danych z DB."""
    insights: List[Dict] = []
    quantum = _compute_quantum_weights(db, symbols, timeframe=timeframe, limit=limit)

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
                "timestamp": datetime.utcnow().isoformat(),
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
    except Exception:
        pass


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
    Darmowe zastępstwo dla OpenAI: zakresy z ATR + Bollinger.
    Cel: stabilne, rozsądne progi (bez zgadywania tekstem przez LLM).
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

        trend_up = (ema_20 is not None and ema_50 is not None and ema_20 > ema_50)

        # Default widths
        if atr and atr > 0:
            buy_low = price - (1.20 * atr)
            buy_high = price - (0.40 * atr)
            sell_low = price + (0.60 * atr)
            sell_high = price + (1.40 * atr)
        else:
            buy_low = price * 0.985
            buy_high = price * 0.995
            sell_low = price * 1.005
            sell_high = price * 1.015

        # Align to Bollinger bands if available
        if bb_lower is not None:
            buy_low = min(buy_low, bb_lower)
            buy_high = min(buy_high, max(bb_lower, (bb_lower + price) / 2))
        if bb_upper is not None:
            sell_high = max(sell_high, bb_upper)
            sell_low = max(sell_low, min(bb_upper, (bb_upper + price) / 2))

        # RSI tweaks: oversold => more willing to buy; overbought => more willing to sell
        if rsi is not None:
            if rsi < 30:
                buy_high = min(buy_high, price)  # allow BUY closer to market
            if rsi > 70:
                sell_low = max(sell_low, price)  # allow SELL closer to market

        # Trend tweak
        if trend_up:
            sell_low *= 1.002
            sell_high *= 1.002
        else:
            buy_low *= 0.998
            buy_high *= 0.998

        # Normalize
        buy_low, buy_high = sorted([buy_low, buy_high])
        sell_low, sell_high = sorted([sell_low, sell_high])

        buy_action = "KUP TERAZ" if buy_low <= price <= buy_high else "CZEKAJ"
        sell_action = "SPRZEDAJ TERAZ" if price >= sell_low else "CZEKAJ"
        buy_target = round(price if buy_action == "KUP TERAZ" else buy_high, 8)
        sell_target = round(price if sell_action == "SPRZEDAJ TERAZ" else sell_low, 8)

        comment = "Heurystyka (ATR/Bollinger) — OpenAI niedostępne"
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


def _openai_ranges(insights: List[Dict], force: bool = False) -> List[Dict]:
    api_key = _get_openai_api_key()
    if not api_key:
        return []

    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    backoff_seconds = int(os.getenv("OPENAI_BACKOFF_SECONDS", "600"))
    global _last_openai_error_ts
    if (not force) and _last_openai_error_ts and (datetime.utcnow() - _last_openai_error_ts).total_seconds() < backoff_seconds:
        return []
    payload = {
        "model": model,
        "input": (
            "Jesteś analitykiem rynku. Dla każdej pozycji podaj zakresy zakupu i sprzedaży "
            "na bazie ceny i wskaźników. Zwróć WYŁĄCZNIE JSON: "
            "[{\"symbol\":\"BTCUSDT\",\"buy_low\":...,\"buy_high\":...,\"sell_low\":...,\"sell_high\":...,"
            "\"buy_action\":\"KUP TERAZ|CZEKAJ\",\"buy_target\":...,\"sell_action\":\"SPRZEDAJ TERAZ|CZEKAJ\",\"sell_target\":...,"
            "\"comment\":\"...\"}]. "
            "Dane: " + json.dumps(insights, ensure_ascii=False)
        ),
    }
    def _extract_json(text: str) -> Optional[str]:
        if not text:
            return None
        clean = text.strip()
        # remove ```json fences if present
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

    def _sanitize(msg: str) -> str:
        # Do not persist any key-like material in logs.
        return re.sub(r"sk-[^\s]+", "sk-[REDACTED]", msg or "")

    try:
        resp = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=25,
        )
        if resp.status_code >= 400:
            _last_openai_error_ts = datetime.utcnow()
            try:
                data = resp.json()
                err = (data or {}).get("error") or {}
                msg = _sanitize(str(err.get("message") or resp.text or ""))
                code = err.get("code") or err.get("type") or "openai_error"
                log_to_db("ERROR", "analysis", f"OpenAI HTTP {resp.status_code} ({code}): {msg[:220]}")
            except Exception:
                log_to_db("ERROR", "analysis", f"OpenAI HTTP {resp.status_code}: {_sanitize(resp.text or '')[:220]}")
            return []
        data = resp.json()
        # Spróbuj wyciągnąć tekst
        text = data.get("output_text")
        if not text:
            # Fallback: złącz content
            output = data.get("output", [])
            parts = []
            for item in output:
                for c in item.get("content", []):
                    if c.get("type") == "output_text" and c.get("text"):
                        parts.append(c["text"])
            text = "\n".join(parts)
        if not text:
            return []
        extracted = _extract_json(text)
        if not extracted:
            _last_openai_error_ts = datetime.utcnow()
            log_to_db("ERROR", "analysis", "OpenAI response: brak tekstu/JSON do parsowania")
            return []
        ranges = json.loads(extracted)
        if isinstance(ranges, list):
            return ranges
        return []
    except Exception as exc:
        _last_openai_error_ts = datetime.utcnow()
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
            timestamp=datetime.utcnow(),
        )
        db.add(signal)

    db.commit()


def generate_blog_post(db, insights: List[Dict]) -> Optional[BlogPost]:
    """Tworzy wpis blogowy po polsku na bazie insightów."""
    if not insights:
        return None

    title = f"Market Insights: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
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
        created_at=datetime.utcnow(),
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
            if latest and (datetime.utcnow() - latest.created_at) < timedelta(hours=1):
                return None

            backoff_seconds = int(os.getenv("OPENAI_BACKOFF_SECONDS", "600"))
            global _last_openai_error_ts
            if _last_openai_error_ts and (datetime.utcnow() - _last_openai_error_ts).total_seconds() < backoff_seconds:
                return None

        insights = generate_market_insights(db, symbols, timeframe="1h")
        if not insights:
            return None

        provider = os.getenv("AI_PROVIDER", "openai").strip().lower()
        if provider in ("heuristic", "offline"):
            ranges = _heuristic_ranges(insights)
        elif provider == "auto":
            ranges = _openai_ranges(insights, force=force) or _heuristic_ranges(insights)
        else:
            # default: OpenAI only
            ranges = _openai_ranges(insights, force=force)
            if not ranges:
                # _openai_ranges loguje szczegóły i ma backoff — nie spamuj logów.
                return None

        insights = _merge_ranges_with_insights(insights, ranges)

        persist_insights_as_signals(db, insights)
        post = generate_blog_post(db, insights)
        log_to_db("INFO", "analysis", f"Wygenerowano Market Insights i wpis bloga (provider={provider})", db=db)
        # Telegram: automatyczna wysyłka tylko jeśli włączona w .env (domyślnie OFF).
        if os.getenv("TELEGRAM_AUTO_INSIGHTS", "false").lower() == "true":
            header = "AI – analiza rynku i decyzje"
            if provider in ("heuristic", "offline"):
                header = "AI (heurystyka) – analiza rynku i decyzje"
            elif provider == "openai":
                header = "OpenAI – analiza rynku i decyzje"
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
