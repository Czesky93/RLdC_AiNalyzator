"""
Dynamic grid engine dla top-N USDC pairs.
Zgodnie z grid.md: selekcja top-N, builder planu gridu, recentering, persystencja.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.binance_client import BinanceClient
from backend.database import MarketData, RuntimeSetting, utc_now_naive
from backend.trading.grid_state_store import (
    load_active_grid_plans,
    save_active_grid_plans,
)

logger = logging.getLogger(__name__)

# Stable coins (nie handlujemy stable-stable parami)
STABLE_ASSETS = {"USDC", "USDT", "FDUSD", "TUSD", "BUSD", "DAI", "USD1", "EUR", "EURI"}


def clip(x: float, lo: float, hi: float) -> float:
    """Ogranicz wartość do przedziału [lo, hi]."""
    return max(lo, min(hi, x))


def zscore(values: List[float]) -> List[float]:
    """Oblicz z-score dla listy wartości."""
    if not values or len(values) < 2:
        return [0.0] * len(values)
    avg = mean(values)
    dev = pstdev(values) if len(values) > 1 else 0.001
    if dev == 0:
        dev = 0.001
    return [(v - avg) / dev for v in values]


@dataclass
class GridPlan:
    """Plan gridu dla pary: zakresy, poziomy, inwestycja."""

    symbol: str
    last_price: float
    center: float
    lower: float
    upper: float
    half_width_pct: float
    step_pct: float
    grid_count: int
    buy_levels: List[float] = field(default_factory=list)
    sell_levels: List[float] = field(default_factory=list)
    invest_quote: float = 0.0
    hard_stop: float = 0.0
    estimated_notional_per_level: float = 0.0
    created_at: Optional[str] = None
    reason_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Konwertuj na dict dla persystencji w DB."""
        d = asdict(self)
        d["created_at"] = self.created_at or utc_now_naive().isoformat()
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> GridPlan:
        """Załaduj z dict z DB."""
        return GridPlan(
            symbol=data.get("symbol", ""),
            last_price=float(data.get("last_price", 0)),
            center=float(data.get("center", 0)),
            lower=float(data.get("lower", 0)),
            upper=float(data.get("upper", 0)),
            half_width_pct=float(data.get("half_width_pct", 0)),
            step_pct=float(data.get("step_pct", 0)),
            grid_count=int(data.get("grid_count", 0)),
            buy_levels=[float(x) for x in data.get("buy_levels", [])],
            sell_levels=[float(x) for x in data.get("sell_levels", [])],
            invest_quote=float(data.get("invest_quote", 0)),
            hard_stop=float(data.get("hard_stop", 0)),
            estimated_notional_per_level=float(data.get("estimated_notional_per_level", 0)),
            created_at=data.get("created_at"),
            reason_codes=data.get("reason_codes", []),
        )


def select_top_usdc_pairs(
    client: BinanceClient,
    top_n: int = 10,
    min_quote_volume_abs: float = 100000,
    min_trade_count_abs: int = 100,
    max_spread_bps_cap: float = 50.0,
) -> List[Dict[str, Any]]:
    """
    Wybierz top-N par USDC z Binance.

    Algorytm:
    1. Pobierz alle USDC pary z ticker/24hr
    2. Filtruj stable-stable
    3. Stosuj filtry płynności (relatywnie, nie sztywnie)
    4. Policz z-score skoring (range, zmiana, atr%, wolumen, trades, spread)
    5. Zwróć top-N

    Args:
        client: Binance klient
        top_n: Liczba top par do zwrócenia
        min_quote_volume_abs: Minimalna objętość (fallback)
        min_trade_count_abs: Minimalna liczba transakcji (fallback)
        max_spread_bps_cap: Maksymalny spread w basis points

    Returns:
        Lista słowników z polami: symbol, base_asset, score, quote_volume, spread_bps, ...
    """
    try:
        # Pobierz alle USDC pary
        usdc_pairs = client.get_usdc_pairs()
        if not usdc_pairs:
            logger.warning("⚠️ select_top_usdc_pairs: brak par USDC z Binance")
            return []

        logger.info(f"📊 select_top_usdc_pairs: znaleziono {len(usdc_pairs)} par USDC")

        # Filtruj stable-stable
        eligible = []
        for p in usdc_pairs:
            base = p.get("base_asset", "").upper()
            if base not in STABLE_ASSETS:
                eligible.append(p)

        logger.info(
            f"📊 select_top_usdc_pairs: {len(eligible)} par po filtrowaniu stable-stable"
        )

        if not eligible:
            return []

        # Ekstrahuj cechy do scoringu i zastosuj twarde floor/cap filtry.
        ranges_24h = []
        abs_changes = []
        atrs_pct = []
        volumes = []
        trades = []
        spreads_bps = []
        filtered = []

        for p in eligible:
            high = float(p.get("high_price", 0) or 0)
            low = float(p.get("low_price", 0) or 0)
            last = float(p.get("last_price", 0) or 0)
            vol = float(p.get("quote_volume", 0) or 0)
            trade_cnt = int(p.get("count", 0) or 0)
            spread = float(p.get("spread_bps", 0) or 0)

            if last <= 0:
                continue
            if vol < float(min_quote_volume_abs):
                continue
            if trade_cnt < int(min_trade_count_abs):
                continue
            if spread > float(max_spread_bps_cap):
                continue

            filtered.append(p)

            if last > 0 and high > low:
                r = (high - low) / low * 100
                ranges_24h.append(r)
            else:
                ranges_24h.append(0)

            pct_change = abs(float(p.get("price_change_percent", 0) or 0))
            abs_changes.append(pct_change)

            volumes.append(vol)

            trades.append(trade_cnt)

            spreads_bps.append(spread)

        eligible = filtered
        if not eligible:
            logger.warning("⚠️ select_top_usdc_pairs: brak par po filtrach płynności/spread")
            return []

        # Z-score normalizacja
        z_ranges = zscore(ranges_24h)
        z_changes = zscore(abs_changes)
        z_spreads = zscore(spreads_bps)
        z_volumes = zscore([math.log1p(v) for v in volumes])
        z_trades = zscore([math.log1p(t) for t in trades])

        # Scoring (wagi z grid.md)
        scores = []
        for i, p in enumerate(eligible):
            score = (
                0.30 * z_ranges[i]
                + 0.20 * z_changes[i]
                + 0.20 * z_volumes[i]
                + 0.15 * z_trades[i]
                + 0.10 * max(0, -z_spreads[i])  # ujemna kara za spread
            )
            scores.append((p, score))

        # Sortuj i zwróć top-N
        scores.sort(key=lambda x: x[1], reverse=True)
        result = []
        for p, score in scores[:top_n]:
            p_dict = dict(p)
            p_dict["score"] = score
            result.append(p_dict)

        logger.info(f"✅ select_top_usdc_pairs: wybrano {len(result)} top par USDC")
        return result

    except Exception as e:
        logger.error(f"❌ select_top_usdc_pairs: {e}")
        return []


def build_grid_plan(
    db: Session,
    symbol: str,
    grid_context: Dict[str, Any],
    equity: float,
    config: Dict[str, Any],
) -> Optional[GridPlan]:
    """
    Zbuduj plan gridu dla pary (zgodnie z grid.md).

    Wejścia:
    - grid_context: dict z 15m, 1h, 4h wskaźnikami
    - equity: dostępny kapitał
    - config: runtime config z RuntimeSetting

    Wyjście:
    - GridPlan lub None przy braku danych

    Logika:
    1. Pobierz wskaźniki z grid_context (15m, 1h, 4h)
    2. Oblicz centrum zakresu (trend bias + VWAP)
    3. Oblicz połowę szerokości (vol_regime + ADX)
    4. Oblicz krok i liczbę gridów
    5. Buduj geometryczne poziomy
    6. Obsługa min/max inwestycji
    """
    try:
        if not grid_context or not equity or equity <= 0:
            logger.warning(f"⚠️ build_grid_plan {symbol}: brak wystarczających danych (context={grid_context is not None}, equity={equity})")
            return None

        last_price = float(grid_context.get("last_price", 0) or 0)
        if last_price <= 0:
            logger.warning(f"⚠️ build_grid_plan {symbol}: cena <= 0")
            return None

        # Pobierz wskaźniki
        ctx_15m = grid_context.get("15m", {})
        ctx_1h = grid_context.get("1h", {})
        ctx_4h = grid_context.get("4h", {})

        ema20_15 = float(ctx_15m.get("ema_20", last_price) or last_price)
        ema50_15 = float(ctx_15m.get("ema_50", last_price) or last_price)
        ema20_1h = float(ctx_1h.get("ema_20", last_price) or last_price)
        ema50_1h = float(ctx_1h.get("ema_50", last_price) or last_price)
        atr15_pct = float(ctx_15m.get("atr", last_price * 0.01) or (last_price * 0.01)) / last_price
        adx_1h = float(ctx_1h.get("adx", 20) or 20)
        vwap_24h = float(ctx_1h.get("vwap_24", last_price) or last_price)
        spread_bps = float(grid_context.get("spread_bps", 10) or 10)
        spread_pct = spread_bps / 10000

        # Trend bias (EMA ratio)
        trend_bias_raw = (
            0.5 * ((ema20_15 / max(ema50_15, 1e-9)) - 1.0)
            + 0.5 * ((ema20_1h / max(ema50_1h, 1e-9)) - 1.0)
        )
        trend_bias = clip(trend_bias_raw / max(atr15_pct, 1e-9), -1.0, 1.0)

        # Centrum zakresu
        base_anchor = (
            0.45 * last_price
            + 0.35 * vwap_24h
            + 0.20 * ((ema20_15 + ema20_1h) / 2)
        )
        center = base_anchor * (1.0 + 0.35 * trend_bias * atr15_pct)

        # Połowa szerokości (ATR + ADX)
        vol_regime = clip(atr15_pct / max(0.015, 1e-9), 0.5, 2.5)
        adx_norm = clip(adx_1h / max(25, 1e-9), 0.5, 1.5)
        width_mult = clip(2.20 * vol_regime + 0.40 * adx_norm, 1.8, 5.5)
        half_width_pct_raw = max(
            width_mult * atr15_pct,
            spread_pct * 2.5,
            0.02,
        )
        half_width_pct = clip(half_width_pct_raw, 0.02, 0.15)

        lower = center * (1.0 - half_width_pct)
        upper = center * (1.0 + half_width_pct)

        # Krok i liczba gridów
        step_pct_raw = max(
            atr15_pct * 1.5,
            spread_pct * 1.8,
            0.005,
        )
        step_pct = clip(step_pct_raw, 0.003, 0.08)
        grid_count = clip(
            int(math.log(upper / lower) / math.log(1 + step_pct)),
            3,
            30,
        )

        # Geometryczne poziomy
        buy_levels = []
        sell_levels = []
        log_step = math.log(1 + step_pct)

        for i in range(grid_count):
            buy_level = center * math.exp(-i * log_step)
            sell_level = center * math.exp(i * log_step)

            # Przycnij do zakresu
            buy_level = clip(buy_level, lower, upper)
            sell_level = clip(sell_level, lower, upper)

            buy_levels.append(buy_level)
            sell_levels.append(sell_level)

        # Inwestycja i hardstop
        invest_pct = float(
            config.get(
                "dynamic_grid_base_invest_pct",
                config.get("dynamic_grid_invest_pct", 0.1),
            )
            or 0.1
        )
        max_symbol_exposure = float(
            config.get("dynamic_grid_max_symbol_exposure_pct", invest_pct) or invest_pct
        )
        invest_pct = clip(invest_pct, 0.0, max_symbol_exposure)
        invest_quote = equity * invest_pct
        estimated_notional_per_level = invest_quote / max(grid_count, 1)

        stop_pad_pct = clip(spread_pct + atr15_pct, 0.01, 0.05)
        hard_stop = lower * (1.0 - stop_pad_pct)

        plan = GridPlan(
            symbol=symbol,
            last_price=last_price,
            center=center,
            lower=lower,
            upper=upper,
            half_width_pct=half_width_pct,
            step_pct=step_pct,
            grid_count=grid_count,
            buy_levels=buy_levels,
            sell_levels=sell_levels,
            invest_quote=invest_quote,
            hard_stop=hard_stop,
            estimated_notional_per_level=estimated_notional_per_level,
            created_at=utc_now_naive().isoformat(),
        )

        logger.info(
            f"✅ build_grid_plan {symbol}: center={center:.8f}, range=[{lower:.8f}, {upper:.8f}], "
            f"levels={grid_count}, invest={invest_quote:.2f}"
        )
        return plan

    except Exception as e:
        logger.error(f"❌ build_grid_plan {symbol}: {e}")
        return None


def check_recentering_needed(
    plan: GridPlan,
    current_price: float,
    current_position: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Sprawdź, czy plan gridu wymaga recentering (przesunięcia zakresu).

    Logika z grid.md:
    - position_in_range = (p - lower) / (upper - lower)
    - Jeśli position_in_range < 0.20 lub > 0.80 → recentering
    - Reguły zależą od trendu (uptrend/downtrend/sideways)

    Returns:
        {
            "recentering_needed": bool,
            "action": "none" | "shift_up" | "shift_down" | "rebuild",
            "reason": str,
            "new_center": Optional[float],
        }
    """
    try:
        if not plan or plan.upper <= plan.lower:
            return {"recentering_needed": False, "action": "none", "reason": "invalid_plan"}

        position_in_range = (current_price - plan.lower) / (plan.upper - plan.lower)

        # Prostá logika: jeśli zbyt blisko górnego lub dolnego progu, recenter
        if position_in_range < 0.15:
            return {
                "recentering_needed": True,
                "action": "shift_down",
                "reason": f"position_too_low ({position_in_range:.2%})",
                "new_center": plan.center * 0.95,
            }
        elif position_in_range > 0.85:
            return {
                "recentering_needed": True,
                "action": "shift_up",
                "reason": f"position_too_high ({position_in_range:.2%})",
                "new_center": plan.center * 1.05,
            }
        else:
            return {
                "recentering_needed": False,
                "action": "none",
                "reason": f"position_ok ({position_in_range:.2%})",
            }

    except Exception as e:
        logger.error(f"❌ check_recentering_needed: {e}")
        return {"recentering_needed": False, "action": "none", "reason": f"error: {e}"}


def persist_grid_plan(
    db: Session,
    symbol: str,
    plan: GridPlan,
) -> bool:
    """Utrwal plan gridu w zbiorczym active_grid_plans RuntimeSetting."""
    try:
        plans = load_active_grid_plans(db)
        plans[str(symbol or plan.symbol).strip().upper()] = plan.to_dict()
        save_active_grid_plans(db, plans)
        db.commit()
        logger.info(f"✅ persist_grid_plan {symbol}: persisted to active_grid_plans")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"❌ persist_grid_plan {symbol}: {e}")
        return False


def load_grid_plan(db: Session, symbol: str) -> Optional[GridPlan]:
    """Załaduj plan gridu z RuntimeSetting."""
    try:
        symbol_norm = str(symbol or "").strip().upper()
        plans = load_active_grid_plans(db)
        if symbol_norm in plans:
            plan = GridPlan.from_dict(plans[symbol_norm])
            logger.info(f"✅ load_grid_plan {symbol}: loaded from active_grid_plans")
            return plan

        # Backward-compatible read only for old local state. New writes use active_grid_plans.
        key = f"grid_plan#{symbol_norm}"
        setting = db.query(RuntimeSetting).filter(RuntimeSetting.key == key).first()
        if not setting:
            return None

        data = json.loads(setting.value)
        plan = GridPlan.from_dict(data)
        logger.info(f"✅ load_grid_plan {symbol}: loaded from DB")
        return plan
    except Exception as e:
        logger.error(f"❌ load_grid_plan {symbol}: {e}")
        return None
