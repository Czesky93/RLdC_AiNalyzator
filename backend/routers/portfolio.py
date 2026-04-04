"""
Portfolio API Router - endpoints dla portfolio
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta, timezone
import time as _time
import json

from backend.accounting import summarize_positions, compute_demo_account_state
from backend.database import get_db, Position, AccountSnapshot, ForecastRecord, MarketData, utc_now_naive
from backend.binance_client import get_binance_client

router = APIRouter()

# Cache dla _build_live_spot_portfolio — binance.get_balances() kosztuje ~2-3s per call
_live_spot_portfolio_cache: dict = {}
_LIVE_SPOT_TTL = 15  # sekund


def _load_plan_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _build_live_spot_portfolio(db: Session) -> Dict:
    """
    Czyta pełne saldo Binance spot i przelicza każde aktywo na EUR.
    Używa cen z MarketData (ostatni tick z DB) i fallback na Binance API.
    Zwraca słownik z: spot_positions, unpriced_assets, total_equity_eur, free_cash_eur, error
    Cache TTL 30s — get_balances() kosztuje ~2-3s per call.
    """
    cached = _live_spot_portfolio_cache.get("result")
    if cached and (_time.time() - cached["ts"]) < _LIVE_SPOT_TTL:
        return cached["data"]

    binance = get_binance_client()
    if not binance.api_key or not binance.api_secret:
        return {"error": "Brak kluczy Binance API — uzupełnij .env (BINANCE_API_KEY, BINANCE_API_SECRET)",
                "spot_positions": [], "unpriced_assets": [], "total_equity_eur": 0.0, "free_cash_eur": 0.0}

    balances = binance.get_balances() or []
    if not balances:
        return {"error": "Brak sald z Binance — sprawdź klucze API",
                "spot_positions": [], "unpriced_assets": [], "total_equity_eur": 0.0, "free_cash_eur": 0.0}

    # ─── Pobierz ceny EUR z DB (najnowszy tick dla każdego symbolu kończącego się na EUR)
    latest_ts_subq = (
        db.query(MarketData.symbol, func.max(MarketData.timestamp).label("ts"))
        .filter(MarketData.symbol.like("%EUR"))
        .group_by(MarketData.symbol)
        .subquery()
    )
    md_eur_rows = (
        db.query(MarketData)
        .join(latest_ts_subq,
              (MarketData.symbol == latest_ts_subq.c.symbol) &
              (MarketData.timestamp == latest_ts_subq.c.ts))
        .all()
    )
    eur_prices: Dict[str, float] = {}  # asset -> cena w EUR
    for md in md_eur_rows:
        asset = md.symbol[:-3]  # BTCEUR -> BTC
        if md.price and md.price > 0:
            eur_prices[asset] = float(md.price)

    # ─── Kurs USDT/EUR z DB lub Binance
    eur_per_usdt: Optional[float] = None
    eurusdt_md = (
        db.query(MarketData).filter(MarketData.symbol == "EURUSDT")
        .order_by(MarketData.timestamp.desc()).first()
    )
    if eurusdt_md and (eurusdt_md.price or 0) > 0:
        eur_per_usdt = round(1.0 / float(eurusdt_md.price), 6)
    else:
        try:
            t = binance.get_ticker_price("EURUSDT")
            if t and (t.get("price") or 0) > 0:
                eur_per_usdt = round(1.0 / float(t["price"]), 6)
        except Exception:
            eur_per_usdt = None

    # ─── Fallback: pobierz brakujące ceny z Binance API (tylko 1 request per asset)
    stable_stable = {"EUR", "BUSD"}
    stable_usdt = {"USDT", "USDC"}
    for b in balances:
        asset = b["asset"]
        if asset in eur_prices or asset in stable_stable or asset in stable_usdt:
            continue
        # Spróbuj {ASSET}EUR z Binance
        try:
            t = binance.get_ticker_price(f"{asset}EUR")
            if t and (t.get("price") or 0) > 0:
                eur_prices[asset] = float(t["price"])
                continue
        except Exception:
            pass
        # Spróbuj {ASSET}USDT + przelicz na EUR
        if eur_per_usdt:
            try:
                t = binance.get_ticker_price(f"{asset}USDT")
                if t and (t.get("price") or 0) > 0:
                    eur_prices[asset] = float(t["price"]) * eur_per_usdt
                    continue
            except Exception:
                pass

    # ─── Zbuduj listę pozycji
    spot_positions: List[Dict] = []
    unpriced_assets: List[Dict] = []
    total_equity_eur = 0.0
    free_cash_eur = 0.0

    for b in balances:
        asset = b["asset"]
        total_qty = float(b.get("total") or 0)
        free_qty = float(b.get("free") or 0)
        locked_qty = float(b.get("locked") or 0)
        if total_qty <= 0:
            continue

        if asset in stable_stable:
            price_eur = 1.0
            price_source = "stable_eur"
        elif asset in stable_usdt:
            price_eur = eur_per_usdt
            price_source = "usdt_conv"
        else:
            price_eur = eur_prices.get(asset)
            price_source = "market_data" if asset in eur_prices else None

        if price_eur and price_eur > 0:
            value_eur = round(total_qty * price_eur, 4)
            free_value_eur = round(free_qty * price_eur, 4)
            total_equity_eur += value_eur
            if asset in stable_stable or asset in stable_usdt:
                free_cash_eur += free_value_eur
            spot_positions.append({
                "asset": asset,
                "total": round(total_qty, 8),
                "free": round(free_qty, 8),
                "locked": round(locked_qty, 8),
                "price_eur": round(price_eur, 6),
                "price_source": price_source,
                "value_eur": value_eur,
                "free_value_eur": free_value_eur,
                "weight_pct": 0.0,  # wypełnione poniżej
            })
        else:
            unpriced_assets.append({"asset": asset, "total": round(total_qty, 8)})

    # Posortuj wg wartości i policz udziały
    spot_positions.sort(key=lambda x: -x["value_eur"])
    for p in spot_positions:
        p["weight_pct"] = round((p["value_eur"] / total_equity_eur * 100) if total_equity_eur > 0 else 0, 1)

    result = {
        "error": None,
        "spot_positions": spot_positions,
        "unpriced_assets": unpriced_assets,
        "total_equity_eur": round(total_equity_eur, 2),
        "free_cash_eur": round(free_cash_eur, 2),
        "assets_count": len(spot_positions),
        "unpriced_count": len(unpriced_assets),
        "eur_per_usdt": eur_per_usdt,
        "data_age_seconds": None,  # można dodać póżniej
    }
    # Zapisz do cache (tylko sukces — nie cache'uj błędów)
    _live_spot_portfolio_cache["result"] = {"data": result, "ts": _time.time()}
    return result


@router.get("")
def get_portfolio(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Pobierz portfolio (otwarte pozycje)
    """
    try:
        positions = db.query(Position).filter(
            Position.mode == mode
        ).all()
        
        # Jeśli brak pozycji w demo, zwracamy pusty wynik
        
        # Formatuj dane
        result = []
        total_unrealized_pnl = 0.0
        
        for pos in positions:
            # Aktualizuj current_price (w prawdziwym systemie z market data)
            # current_price = get_current_price(pos.symbol)
            unrealized_pnl = pos.unrealized_pnl or 0.0
            total_unrealized_pnl += unrealized_pnl
            
            result.append({
                "id": pos.id,
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "quantity": pos.quantity,
                "unrealized_pnl": unrealized_pnl,
                "pnl_percent": round((unrealized_pnl / (pos.entry_price * pos.quantity) * 100) if pos.entry_price > 0 else 0, 2),
                "opened_at": pos.opened_at.isoformat(),
                "updated_at": pos.updated_at.isoformat() if pos.updated_at else pos.opened_at.isoformat(),
                "plan_status": pos.plan_status,
                "requires_revision": bool(pos.requires_revision),
                "invalidation_reason": pos.invalidation_reason,
                "last_consulted_at": pos.last_consulted_at.isoformat() if pos.last_consulted_at else None,
                "plan": _load_plan_json(getattr(pos, "decision_plan_json", None)),
            })
        
        response = {
            "success": True,
            "mode": mode,
            "data": result,
            "count": len(result),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2)
        }
        
        # Jeśli LIVE, dołącz salda z Binance
        if mode == "live":
            binance = get_binance_client()
            spot_balances = binance.get_balances()
            simple_earn_account = binance.get_simple_earn_account() or {}
            simple_earn_flexible = binance.get_simple_earn_flexible_positions() or {}
            simple_earn_locked = binance.get_simple_earn_locked_positions() or {}
            futures_balance = binance.get_futures_balance() or []
            futures_account = binance.get_futures_account() or {}
            response["spot_balances"] = spot_balances
            response["simple_earn_account"] = simple_earn_account
            response["simple_earn_flexible"] = simple_earn_flexible
            response["simple_earn_locked"] = simple_earn_locked
            response["futures_balance"] = futures_balance
            response["futures_account"] = futures_account
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting portfolio: {str(e)}")


@router.get("/summary")
def get_portfolio_summary(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Podsumowanie portfolio
    """
    try:
        positions = db.query(Position).filter(Position.mode == mode).all()
        summary = summarize_positions(positions, db=db, label=f"{mode}_portfolio")
        total_positions = int(summary.get("positions") or 0)
        winning = sum(1 for pos in positions if float(pos.unrealized_pnl or 0.0) > 0.0)
        losing = sum(1 for pos in positions if float(pos.unrealized_pnl or 0.0) < 0.0)
        return {
            "success": True,
            "mode": mode,
            "data": {
                "total_positions": total_positions,
                "total_value": round(float(summary.get("exposure") or 0.0), 2),
                "total_unrealized_pnl": round(sum(float(pos.unrealized_pnl or 0.0) for pos in positions), 2),
                "winning_positions": winning,
                "losing_positions": losing,
                "win_rate": round((winning / total_positions * 100) if total_positions > 0 else 0.0, 2),
                "gross_pnl": round(float(summary.get("gross_pnl") or 0.0), 2),
                "net_pnl": round(float(summary.get("net_pnl") or 0.0), 2),
                "total_cost": round(float(summary.get("total_cost") or 0.0), 2),
                "fee_cost": round(float(summary.get("fee_cost") or 0.0), 2),
                "slippage_cost": round(float(summary.get("slippage_cost") or 0.0), 2),
                "spread_cost": round(float(summary.get("spread_cost") or 0.0), 2),
            },
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting portfolio summary: {str(e)}")


@router.get("/wealth")
def get_portfolio_wealth(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Pełny majątek portfela — pozycje z wartościami EUR, historia equity (wykres), wolna gotówka.
    Obsługuje zarówno tryb demo jak i live (z graceful fallback).
    """
    try:
        positions = db.query(Position).filter(Position.mode == mode).all()

        total_positions_value = 0.0
        items = []
        for pos in positions:
            entry = float(pos.entry_price or 0)
            qty = float(pos.quantity or 0)
            current = float(pos.current_price or entry)
            value = current * qty
            cost = entry * qty
            pnl_eur = round(value - cost, 4)
            pnl_pct = round((pnl_eur / cost * 100) if cost > 0 else 0, 2)
            total_positions_value += value
            items.append({
                "symbol": pos.symbol,
                "side": pos.side or "BUY",
                "quantity": qty,
                "entry_price": entry,
                "current_price": current,
                "value_eur": round(value, 4),
                "cost_eur": round(cost, 4),
                "pnl_eur": pnl_eur,
                "pnl_pct": pnl_pct,
                "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
            })

        items.sort(key=lambda x: x["value_eur"], reverse=True)
        for item in items:
            item["weight_pct"] = round(
                (item["value_eur"] / total_positions_value * 100) if total_positions_value > 0 else 0, 1
            )

        # Historia equity (ostatnie 48h, max 60 punktów) — do wykresu portfela
        cutoff = utc_now_naive() - timedelta(hours=48)
        snapshots = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode, AccountSnapshot.timestamp >= cutoff)
            .order_by(AccountSnapshot.timestamp)
            .limit(60)
            .all()
        )
        equity_history = [
            {"t": s.timestamp.strftime("%d.%m %H:%M"), "equity": round(s.equity, 2)}
            for s in snapshots
        ]

        free_cash = 0.0
        total_equity = total_positions_value
        _info = None

        if mode == "demo":
            state = compute_demo_account_state(db)
            free_cash = float(state.get("cash") or 0.0)
            total_equity = float(state.get("equity") or (total_positions_value + free_cash))
        elif mode == "live":
            live_data = _build_live_spot_portfolio(db)
            if live_data.get("error"):
                _info = live_data["error"]
            else:
                # Zbierz mapping asset → Position z DB (dla unrealized PnL i entry price)
                live_db_pos = db.query(Position).filter(
                    Position.mode == "live", Position.quantity > 0
                ).all()
                _pos_by_asset: Dict[str, Position] = {}
                for _p in live_db_pos:
                    _sym = str(_p.symbol or "")
                    _asset = _sym.replace("EUR", "").replace("USDC", "").replace("USDT", "").strip()
                    if _asset:
                        _pos_by_asset[_asset] = _p

                # Zastąp items[] pełnymi danymi Binance spot, uzupełnionymi o DB PnL
                items = []
                for p in live_data["spot_positions"]:
                    _asset = p["asset"]
                    _dbp = _pos_by_asset.get(_asset)
                    _pnl_eur = round(float(_dbp.unrealized_pnl or 0.0), 4) if _dbp else 0.0
                    _entry = float(_dbp.entry_price or p["price_eur"]) if _dbp else p["price_eur"]
                    _cost = _entry * p["total"]
                    _pnl_pct = round((_pnl_eur / _cost * 100) if _cost > 0 else 0.0, 2)
                    _opened_at = _dbp.opened_at.isoformat() if (_dbp and _dbp.opened_at) else None
                    items.append({
                        "symbol": f"{_asset}EUR" if _asset not in ("EUR", "USDT", "USDC", "BUSD") else _asset,
                        "asset": _asset,
                        "side": "HOLD",
                        "quantity": p["total"],
                        "free": p["free"],
                        "locked": p["locked"],
                        "entry_price": _entry,
                        "current_price": p["price_eur"],
                        "value_eur": p["value_eur"],
                        "cost_eur": round(_cost, 4),
                        "pnl_eur": _pnl_eur,
                        "pnl_pct": _pnl_pct,
                        "weight_pct": p["weight_pct"],
                        "price_source": p["price_source"],
                        "opened_at": _opened_at,
                    })
                total_equity = live_data["total_equity_eur"]
                free_cash = live_data["free_cash_eur"]
                total_positions_value = total_equity

        # Dodatkowe pola z ostatniego snapshota (equity_change, margin_level)
        latest_snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode)
            .order_by(AccountSnapshot.timestamp.desc())
            .first()
        )
        equity_change = 0.0
        equity_change_pct = 0.0
        margin_level = 0.0
        used_margin = 0.0
        balance = round(total_equity, 2)
        if latest_snap:
            day_ago = utc_now_naive() - timedelta(hours=24)
            prev_snap = (
                db.query(AccountSnapshot)
                .filter(AccountSnapshot.mode == mode, AccountSnapshot.timestamp <= day_ago)
                .order_by(AccountSnapshot.timestamp.desc())
                .first()
            )
            if prev_snap and (prev_snap.equity or 0) > 0:
                equity_change = round((latest_snap.equity or 0) - prev_snap.equity, 2)
                equity_change_pct = round(equity_change / prev_snap.equity * 100, 2)
            margin_level = round(float(latest_snap.margin_level or 0), 2)
            used_margin = round(float(latest_snap.used_margin or 0), 2)
            balance = round(float(latest_snap.balance or total_equity), 2)

        # W trybie LIVE snapshots są rzadkie - używaj bieżących danych Binance
        if mode == "live" and not _info:
            # Nadpisz balance rzeczywistą wartością z Binance
            balance = round(total_equity, 2)

        total_pnl = round(sum(i.get("pnl_eur", 0) for i in items), 2)

        response: Dict = {
            "success": True,
            "mode": mode,
            "total_equity": round(total_equity, 2),
            "free_cash": round(free_cash, 2),
            "positions_value": round(total_positions_value, 2),
            "positions_count": len(items),
            "total_pnl": total_pnl,
            "unrealized_pnl": total_pnl,          # alias dla kompatybilności
            "equity_change": equity_change,
            "equity_change_pct": equity_change_pct,
            "margin_level": margin_level,
            "used_margin": used_margin,
            "balance": balance,
            "items": items,
            "equity_history": equity_history,
        }
        if _info:
            response["_info"] = _info
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania majątku: {str(e)}")


@router.get("/live-sync")
def get_live_sync(db: Session = Depends(get_db)):
    """
    Diagnostyka: pełne zestawienie Binance spot vs panel.
    Pokazuje każde aktywo z ceną EUR, wartością i źródłem danych.
    """
    try:
        live_data = _build_live_spot_portfolio(db)
        if live_data.get("error"):
            return {
                "success": False,
                "error": live_data["error"],
                "total_binance_eur": 0.0,
                "spot_positions": [],
                "unpriced_assets": [],
                "eur_per_usdt": None,
                "synced_at": utc_now_naive().isoformat(),
            }

        # Ostatni snapshot dla porównania
        latest_snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == "live")
            .order_by(AccountSnapshot.timestamp.desc())
            .first()
        )
        panel_equity = round(float(latest_snap.equity or 0), 2) if latest_snap else 0.0
        diff_eur = round(live_data["total_equity_eur"] - panel_equity, 2)

        return {
            "success": True,
            "total_binance_eur": live_data["total_equity_eur"],
            "panel_last_snapshot_eur": panel_equity,
            "diff_eur": diff_eur,
            "assets_count": live_data["assets_count"],
            "unpriced_count": live_data["unpriced_count"],
            "free_cash_eur": live_data["free_cash_eur"],
            "eur_per_usdt": live_data["eur_per_usdt"],
            "spot_positions": live_data["spot_positions"],
            "unpriced_assets": live_data["unpriced_assets"],
            "synced_at": utc_now_naive().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd live-sync: {str(e)}")


@router.get("/forecast")
def get_portfolio_forecast(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Prognoza wartości portfela za 1h / 2h / 7 dni.
    Bazuje na prognozach poszczególnych symboli (ForecastRecord) ważonych wartością pozycji.
    7d = ekstrapolacja z prognozy 24h (szacunkowa).
    """
    try:
        positions = db.query(Position).filter(Position.mode == mode).all()
        if not positions:
            return {
                "success": True,
                "mode": mode,
                "current_value": 0.0,
                "forecast_1h": None,
                "forecast_2h": None,
                "forecast_7d": None,
                "confidence": "brak danych",
                "note": "Brak pozycji w portfelu",
            }

        # Oblicz bieżącą wartość portfela
        current_value = 0.0
        for pos in positions:
            current = float(pos.current_price or pos.entry_price or 0)
            qty = float(pos.quantity or 0)
            current_value += current * qty

        # Zbierz prognozy dla każdego symbolu i horyzontu
        forecasts_by_symbol: Dict[str, Dict[str, float]] = {}
        for pos in positions:
            sym = pos.symbol
            for horizon in ("1h", "4h", "24h"):
                fr = (
                    db.query(ForecastRecord)
                    .filter(
                        ForecastRecord.symbol == sym,
                        ForecastRecord.horizon == horizon,
                        ForecastRecord.checked == False,  # noqa: E712
                    )
                    .order_by(desc(ForecastRecord.forecast_ts))
                    .first()
                )
                if fr and fr.current_price_at_forecast and fr.current_price_at_forecast > 0:
                    pct = (float(fr.forecast_price) - float(fr.current_price_at_forecast)) / float(fr.current_price_at_forecast)
                    if sym not in forecasts_by_symbol:
                        forecasts_by_symbol[sym] = {}
                    forecasts_by_symbol[sym][horizon] = pct

        # Oblicz prognozowane wartości portfela
        f1h = current_value
        f2h = current_value
        f7d = current_value
        has_1h = has_2h = has_7d = False

        for pos in positions:
            sym = pos.symbol
            current = float(pos.current_price or pos.entry_price or 0)
            qty = float(pos.quantity or 0)
            value = current * qty
            sym_fc = forecasts_by_symbol.get(sym, {})

            c1h = sym_fc.get("1h")
            c4h = sym_fc.get("4h")
            c24h = sym_fc.get("24h")

            if c1h is not None:
                f1h += value * c1h
                has_1h = True
            if c1h is not None and c4h is not None:
                # Interpolacja liniowa: 2h = 1/3 drogi między 1h a 4h
                c2h = c1h + (c4h - c1h) / 3.0
                f2h += value * c2h
                has_2h = True
            elif c1h is not None:
                f2h += value * c1h
                has_2h = True
            elif c4h is not None:
                f2h += value * (c4h / 2.0)
                has_2h = True
            if c24h is not None:
                # 7d ≈ ekstrapolacja 24h × 7 (szacunkowa)
                f7d += value * c24h * 7
                has_7d = True

        n_with_fc = len(forecasts_by_symbol)
        n_total = len(positions)
        if n_total > 0 and n_with_fc >= n_total:
            confidence = "wysoka"
        elif n_with_fc > 0:
            confidence = "niska" if n_with_fc < n_total / 2 else "średnia"
        else:
            confidence = "brak danych"

        return {
            "success": True,
            "mode": mode,
            "current_value": round(current_value, 2),
            "forecast_1h": round(f1h, 2) if has_1h else None,
            "forecast_2h": round(f2h, 2) if has_2h else None,
            "forecast_7d": round(f7d, 2) if has_7d else None,
            "confidence": confidence,
            "symbols_with_forecast": n_with_fc,
            "total_symbols": n_total,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd prognozy portfela: {str(e)}")
