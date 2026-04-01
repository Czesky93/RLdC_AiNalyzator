"""
Debug / Diagnostics API Router — spójność danych i analiza wyjść
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import (
    get_db, Position, Order, AccountSnapshot, ExitQuality,
    MarketData, PendingOrder, utc_now_naive
)

router = APIRouter()

_REASON_PL = {
    "stop_loss_hit": "Stop Loss — limit straty osiągnięty",
    "trailing_lock_profit": "Trailing Stop — zabezpieczenie zysku",
    "tp_partial_keep_trend": "Częściowe TP (25%) — trend nadal trwał",
    "tp_full_reversal": "Pełny TP — odwrócenie trendu",
    "weak_trend_after_tp": "TP przy słabym trendzie — zabezpieczono zysk",
    "pending_confirmed_execution": "Ręczne potwierdzenie operatora",
    "tp_sl_exit_triggered": "TP lub SL osiągnięty (legaAcy)",
    "forced_risk_exit": "Wymuszone wyjście — ochrona kapitału",
    "user_target_reached": "Osiągnięto cel użytkownika",
    "portfolio_target_reached": "Osiągnięto cel portfela",
}


@router.get("/state-consistency")
async def get_state_consistency(
    mode: str = Query("demo", description="demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Diagnozuje spójność stanu systemu:
    pozycje ↔ zlecenia ↔ portfolio ↔ equity.

    Pomaga odpowiedzieć na pytanie: dlaczego portfel jest pusty skoro bot handluje?
    """
    try:
        positions = db.query(Position).filter(Position.mode == mode).all()
        buy_filled = db.query(Order).filter(Order.mode == mode, Order.side == "BUY", Order.status == "FILLED").count()
        sell_filled = db.query(Order).filter(Order.mode == mode, Order.side == "SELL", Order.status == "FILLED").count()
        pending_active = db.query(PendingOrder).filter(
            PendingOrder.mode == mode, PendingOrder.status.in_(["PENDING", "CONFIRMED"])
        ).count()

        latest_snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode)
            .order_by(AccountSnapshot.timestamp.desc())
            .first()
        )
        earliest_snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode)
            .order_by(AccountSnapshot.timestamp.asc())
            .first()
        )
        equity_now = float(latest_snap.equity) if latest_snap else 0.0
        equity_start = float(earliest_snap.equity) if earliest_snap else 0.0

        inconsistencies: list[str] = []

        if sell_filled > buy_filled:
            inconsistencies.append(
                f"SELL ({sell_filled}) > BUY ({buy_filled}) — możliwy problem z historią zleceń"
            )

        for p in positions:
            if not p.current_price or float(p.current_price) <= 0:
                inconsistencies.append(f"Pozycja {p.symbol} (ID={p.id}) — brak aktualnej ceny")
            if not p.quantity or float(p.quantity) <= 0:
                inconsistencies.append(f"Pozycja {p.symbol} (ID={p.id}) — zerowa ilość (powinna być usunięta)")

        # --- LIVE: porównanie Binance spot vs local DB ---
        spot_comparison = None
        if mode == "live":
            from backend.routers.positions import _get_live_spot_positions
            try:
                spots = _get_live_spot_positions(db)
                spot_symbols = {s["symbol"] for s in spots}
                local_symbols = {p.symbol for p in positions}

                in_binance_not_local = spot_symbols - local_symbols
                in_local_not_binance = local_symbols - spot_symbols

                if in_binance_not_local:
                    inconsistencies.append(
                        f"Binance spot ma aktywa nieobecne w lokalnej DB: {', '.join(sorted(in_binance_not_local))}"
                    )
                if in_local_not_binance:
                    inconsistencies.append(
                        f"Lokalna DB ma pozycje nieobecne w Binance spot: {', '.join(sorted(in_local_not_binance))}"
                    )

                spot_comparison = {
                    "binance_spot_count": len(spots),
                    "local_positions_count": len(positions),
                    "in_binance_not_local": sorted(in_binance_not_local),
                    "in_local_not_binance": sorted(in_local_not_binance),
                    "binance_total_value_eur": round(sum(s.get("value_eur", 0) for s in spots), 2),
                    "spot_positions": [
                        {
                            "symbol": s["symbol"],
                            "asset": s["asset"],
                            "quantity": s["quantity"],
                            "value_eur": round(s.get("value_eur", 0), 2),
                        }
                        for s in spots
                    ],
                }
            except Exception as spot_exc:
                spot_comparison = {"error": f"Nie udało się pobrać Binance spot: {spot_exc}"}

        # Wyjaśnienie typowego scenariusza "portfolio puste ale equity rośnie"
        explanation = None
        if mode == "live" and spot_comparison and not spot_comparison.get("error"):
            sc = spot_comparison
            if sc["binance_spot_count"] > 0 and len(positions) == 0:
                explanation = (
                    f"Binance spot zawiera {sc['binance_spot_count']} aktyw(ów) "
                    f"o łącznej wartości {sc['binance_total_value_eur']:.2f} EUR, "
                    f"ale lokalna tabela Position jest pusta. "
                    f"To normalne w trybie LIVE — źródłem prawdy jest Binance."
                )
        elif len(positions) == 0 and sell_filled > 0:
            profit = round(equity_now - equity_start, 2)
            if profit > 0:
                explanation = (
                    f"Bot przeprowadził {buy_filled} kupno(a) i {sell_filled} sprzedaż(e). "
                    f"Wszystkie pozycje zostały zamknięte z zyskiem +{profit:.2f} EUR. "
                    f"Portfolio jest teraz puste — bot szuka kolejnych okazji."
                )
            elif profit == 0 and sell_filled > 0:
                explanation = (
                    f"Bot przeprowadził transakcje, ale wszystkie pozycje są zamknięte. "
                    f"Portfolio tymczasowo puste — system czeka na sygnały."
                )

        result = {
            "success": True,
            "mode": mode,
            "orders_buy_filled": buy_filled,
            "orders_sell_filled": sell_filled,
            "pending_orders_active": pending_active,
            "positions_count": len(positions),
            "portfolio_items_count": len(positions),
            "equity_now": round(equity_now, 2),
            "equity_start": round(equity_start, 2),
            "equity_change": round(equity_now - equity_start, 2),
            "positions": [
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "qty": float(p.quantity or 0),
                    "entry_price": float(p.entry_price or 0),
                    "current_price": float(p.current_price or 0),
                    "unrealized_pnl": float(p.unrealized_pnl or 0),
                    "trailing_active": bool(p.trailing_active),
                    "partial_take_count": int(p.partial_take_count or 0),
                }
                for p in positions
            ],
            "inconsistencies": inconsistencies,
            "diagnosis": "spójny" if not inconsistencies else "wykryto niezgodności",
            "explanation": explanation,
        }

        if spot_comparison is not None:
            result["spot_comparison"] = spot_comparison

        return result

    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.get("/last-exits")
async def get_last_exits(
    mode: str = Query("demo", description="demo lub live"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Ostatnie zamknięcia pozycji z pełną analizą:
    - powód zamknięcia (po polsku)
    - czy wyszliśmy za wcześnie (premature_exit)
    - ile % ruchu oddaliśmy rynkowi po wyjściu
    """
    try:
        exits = (
            db.query(ExitQuality)
            .filter(ExitQuality.mode == mode)
            .order_by(ExitQuality.closed_at.desc())
            .limit(limit)
            .all()
        )

        items = []
        for ex in exits:
            # Wykryj przedwczesne wyjście — czy cena rosła po SELL?
            premature_exit = None
            post_exit_move_pct = None
            if ex.exit_price and ex.closed_at and ex.symbol:
                later_md = (
                    db.query(MarketData)
                    .filter(
                        MarketData.symbol == ex.symbol,
                        MarketData.timestamp > ex.closed_at,
                    )
                    .order_by(MarketData.timestamp.asc())
                    .first()
                )
                if later_md and float(later_md.price or 0) > 0:
                    post_exit_move_pct = round(
                        (float(later_md.price) - float(ex.exit_price)) / float(ex.exit_price) * 100, 2
                    )
                    # Dla LONG: jeśli cena po wyjściu wzrosła > 1.5% → przedwczesne
                    if ex.side in ("LONG", "BUY") and post_exit_move_pct > 1.5:
                        premature_exit = True
                    elif ex.side in ("LONG", "BUY"):
                        premature_exit = False

            reason_code = ex.exit_reason_code or "pending_confirmed_execution"
            duration_h = round(float(ex.duration_seconds or 0) / 3600, 2) if ex.duration_seconds else None
            entry = float(ex.entry_price or 0)
            exit_p = float(ex.exit_price or 0)
            qty = float(ex.quantity or 0)
            cost = entry * qty
            gross = float(ex.gross_pnl or 0)
            pnl_pct = round(gross / cost * 100, 2) if cost > 0 else 0.0

            items.append({
                "symbol": ex.symbol,
                "side": ex.side or "LONG",
                "entry_price": entry,
                "exit_price": exit_p,
                "quantity": qty,
                "gross_pnl": round(gross, 4),
                "net_pnl": round(float(ex.net_pnl or 0), 4),
                "pnl_eur": round(gross, 4),
                "pnl_pct": pnl_pct,
                "held_duration_h": duration_h,
                "reason_code": reason_code,
                "reason_pl": _REASON_PL.get(reason_code, reason_code),
                "mfe_pnl": round(float(ex.mfe_pnl or 0), 4) if ex.mfe_pnl is not None else None,
                "gave_back_pct": round(float(ex.gave_back_pct or 0), 2) if ex.gave_back_pct is not None else None,
                "tp_hit": bool(ex.tp_hit),
                "sl_hit": bool(ex.sl_hit),
                "realized_rr": round(float(ex.realized_rr or 0), 2) if ex.realized_rr is not None else None,
                "closed_at": ex.closed_at.isoformat() if ex.closed_at else None,
                "premature_exit": premature_exit,
                "post_exit_move_pct": post_exit_move_pct,
                "market_context_after_exit": (
                    "wzrostowy" if post_exit_move_pct is not None and post_exit_move_pct > 0
                    else "spadkowy" if post_exit_move_pct is not None and post_exit_move_pct < 0
                    else None
                ),
            })

        premature_count = sum(1 for it in items if it["premature_exit"] is True)
        avg_net = sum(it["net_pnl"] for it in items) / len(items) if items else 0.0
        total_gave_back = sum(it["gave_back_pct"] or 0 for it in items if it["mfe_pnl"])

        return {
            "success": True,
            "mode": mode,
            "count": len(items),
            "premature_exits_count": premature_count,
            "premature_exits_pct": round(premature_count / len(items) * 100, 1) if items else 0,
            "avg_net_pnl": round(avg_net, 4),
            "total_gave_back_pct": round(total_gave_back, 2),
            "data": items,
        }

    except Exception as exc:
        return {"success": False, "error": str(exc)}
