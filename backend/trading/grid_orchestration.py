"""
Grid Entry/Exit Orchestration — integracja grid plans z trading cycle.
Zgadnie z grid.md: place BUY orders na buy_levels, manage SL/TP na sell_levels.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.database import Position, PendingOrder, utc_now_naive
from backend.trading.pending_order_factory import create_pending_order_from_grid

logger = logging.getLogger(__name__)


def orchestrate_grid_entries(
    db: Session,
    symbol: str,
    grid_plan: Dict[str, Any],
    current_price: float,
    equity: float,
    available_cash: float,
    config: Dict[str, Any],
    open_positions: List[Position],
) -> Tuple[int, List[str]]:
    """
    Orchestruj wejścia gridu dla symbolu (place BUY orders na buy_levels).
    
    Logika:
    1. Pobierz plan gridu (zakresy, poziomy, inwestycja)
    2. Dla każdego buy_level: sprawdź czy current_price <= buy_level
    3. Jeśli TAK i nie ma już order na tym poziomie:
       - Oblicz qty: invest_per_level / current_price
       - Utwórz pending BUY order
    4. Tracking: zapamiętaj które poziomy są already covered (pending/open orders)
    
    Returns:
    - (orders_placed, reasons) — ile orderów utworzono i powody
    """
    try:
        buy_levels = grid_plan.get("buy_levels", [])
        invest_quote = grid_plan.get("invest_quote", 0)
        
        if not buy_levels or invest_quote <= 0 or current_price <= 0:
            return (0, ["invalid_grid_plan"])
        
        # Liczba pozycji USDT do inwestycji per level
        invest_per_level = invest_quote / len(buy_levels) if len(buy_levels) > 0 else 0
        
        if invest_per_level <= 0 or available_cash < invest_per_level:
            return (0, ["insufficient_cash"])
        
        mode = str(config.get("mode") or grid_plan.get("mode") or "demo").lower()

        # Zbierz już istniejące pending BUY dla tego symbolu na buy_levels
        existing_buy_orders = db.query(PendingOrder).filter(
            PendingOrder.symbol == symbol,
            PendingOrder.side == "BUY",
            PendingOrder.mode == mode,
            PendingOrder.status.in_(
                ["PENDING_CREATED", "PENDING_CONFIRMED", "PENDING", "CONFIRMED"]
            ),
        ).all()
        
        # Ekstrahuj cenę z istniejących orderów (czy jest już order na tym level)
        existing_buy_prices = {
            float(o.price or 0) for o in existing_buy_orders if o.price
        }
        
        # Zbierz existing open positions
        existing_positions = [p for p in open_positions if p.symbol == symbol]
        
        orders_placed = 0
        reasons = []
        
        for buy_level in sorted(buy_levels):
            # Skip jeśli już mamy order na tym poziomie
            level_tolerance = max(abs(float(buy_level)) * 1e-6, 1e-8)
            if any(abs(price - buy_level) <= level_tolerance for price in existing_buy_prices):
                continue
            
            # Skip jeśli cena nie dotarła do buy_level (czekaj aż cena spadnie)
            if current_price > buy_level:
                continue
            
            # Skip jeśli brakuje cash
            if available_cash < invest_per_level:
                reasons.append(f"insufficient_cash_for_level_{buy_level}")
                break
            
            # Oblicz qty
            qty = invest_per_level / current_price
            
            # Minimalny check: nie za mała ilość
            min_qty = float(config.get("min_qty", 0.001))
            if qty < min_qty:
                reasons.append(f"qty_too_small_for_level_{buy_level}")
                continue
            
            # Utwórz pending BUY order zgodny z modelem DB.
            try:
                pending = create_pending_order_from_grid(
                    symbol=symbol,
                    side="BUY",
                    quantity=qty,
                    price=buy_level,
                    mode=mode,
                    reason=f"grid_buy_level level={buy_level:.8f}",
                    plan_payload={
                        "symbol": symbol,
                        "level_price": buy_level,
                        "current_price": current_price,
                        "invest_per_level": invest_per_level,
                        "grid_count": grid_plan.get("grid_count"),
                    },
                )
                db.add(pending)
                db.flush()
                db.commit()
                available_cash -= invest_per_level
                existing_buy_prices.add(float(buy_level))
                
                orders_placed += 1
                reasons.append(f"placed_buy_level_{buy_level:.8f}")
                
                logger.info(
                    f"📊 Grid BUY order placed: {symbol} @ {buy_level:.8f} qty {qty:.8f}"
                )
                
            except Exception as e:
                logger.error(f"❌ Failed to create grid BUY order for {symbol} @ {buy_level}: {e}")
                reasons.append(f"error_creating_order_level_{buy_level}")
                continue
        
        return (orders_placed, reasons)
        
    except Exception as e:
        logger.error(f"❌ orchestrate_grid_entries failed: {e}")
        return (0, [f"error: {e}"])


def orchestrate_grid_exits(
    db: Session,
    symbol: str,
    grid_plan: Dict[str, Any],
    current_price: float,
    open_position: Position,
    config: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Orchestruj wyjścia gridu dla symbolu (check sell_levels i hard_stop).
    
    Logika:
    1. Jeśli current_price >= hard_stop: zamknij całą pozycję (emergency kill)
    2. Dla każdego sell_level: sprawdź czy current_price >= sell_level
    3. Jeśli TAK: ustaw TP na tym poziomie
    4. Jeśli trailing_sl włączony: update trailing SL wg grid.md rules
    
    Returns:
    - (exit_triggered, reasons) — czy exit się aktywował i powody
    """
    try:
        if not open_position:
            return (False, ["no_position"])
        
        sell_levels = grid_plan.get("sell_levels", [])
        hard_stop = grid_plan.get("hard_stop", 0)
        
        reasons = []
        
        # 1) Hard stop (emergency)
        if hard_stop > 0 and current_price <= hard_stop:
            reasons.append(f"hard_stop_triggered_{hard_stop}")
            logger.warning(
                f"⚠️ Grid hard stop triggered for {symbol}: price {current_price} <= stop {hard_stop}"
            )
            return (True, reasons)
        
        # 2) Sell levels
        for sell_level in sorted(sell_levels):
            if current_price >= sell_level:
                # Cena osiągnęła/przekroczyła sell_level
                # Ustaw TP na tym poziomie (jeśli nie ma już TP)
                if open_position and not open_position.planned_tp:
                    try:
                        open_position.planned_tp = sell_level
                        db.add(open_position)
                        db.flush()
                        db.commit()
                        reasons.append(f"tp_set_to_sell_level_{sell_level}")
                        logger.info(
                            f"📊 Grid TP set for {symbol}: {sell_level:.8f}"
                        )
                    except Exception as e:
                        logger.error(f"❌ Failed to set TP: {e}")
                        reasons.append(f"error_setting_tp: {e}")
        
        return (False, reasons)
        
    except Exception as e:
        logger.error(f"❌ orchestrate_grid_exits failed: {e}")
        return (False, [f"error: {e}"])
