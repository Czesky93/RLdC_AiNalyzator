"""
Account API Router - endpoints dla danych konta (demo i live)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timedelta
import random

from backend.database import get_db, AccountSnapshot
from backend.binance_client import get_binance_client

router = APIRouter()


class DemoAccount:
    """Symulator konta demo"""
    
    @staticmethod
    def generate_snapshot(db: Session) -> dict:
        """
        Generuj snapshot konta demo
        Symulacja realistycznych wartości equity i margin
        """
        # Pobierz ostatni snapshot
        last = db.query(AccountSnapshot).filter(
            AccountSnapshot.mode == "demo"
        ).order_by(desc(AccountSnapshot.timestamp)).first()
        
        if last:
            # Symuluj zmianę equity (±2% losowo)
            change_percent = random.uniform(-0.02, 0.02)
            equity = last.equity * (1 + change_percent)
            
            # Margin używany (50-80% equity)
            used_margin = equity * random.uniform(0.5, 0.8)
            free_margin = equity - used_margin
            margin_level = (equity / used_margin * 100) if used_margin > 0 else 0
            
            # Unrealized PnL
            unrealized_pnl = equity - last.balance
            
        else:
            # Pierwszy snapshot - wartości początkowe
            equity = 10000.0
            used_margin = 5000.0
            free_margin = 5000.0
            margin_level = 200.0
            unrealized_pnl = 0.0
        
        # Zapisz snapshot
        snapshot = AccountSnapshot(
            mode="demo",
            equity=equity,
            free_margin=free_margin,
            used_margin=used_margin,
            margin_level=margin_level,
            balance=10000.0,  # Balance bazowy nie zmienia się
            unrealized_pnl=unrealized_pnl,
            timestamp=datetime.utcnow()
        )
        db.add(snapshot)
        db.commit()
        
        return {
            "mode": "demo",
            "equity": round(equity, 2),
            "free_margin": round(free_margin, 2),
            "used_margin": round(used_margin, 2),
            "margin_level": round(margin_level, 2),
            "balance": 10000.0,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "timestamp": snapshot.timestamp.isoformat()
        }


@router.get("/summary")
async def get_account_summary(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Pobierz podsumowanie konta (Account Summary)
    - DEMO: symulowane dane
    - LIVE: rzeczywiste dane z Binance (read-only)
    """
    try:
        if mode == "demo":
            # Pobierz lub wygeneruj demo snapshot
            latest = db.query(AccountSnapshot).filter(
                AccountSnapshot.mode == "demo"
            ).order_by(desc(AccountSnapshot.timestamp)).first()
            
            # Jeśli ostatni snapshot jest starszy niż 5 min, wygeneruj nowy
            if not latest or (datetime.utcnow() - latest.timestamp).seconds > 300:
                data = DemoAccount.generate_snapshot(db)
            else:
                data = {
                    "mode": "demo",
                    "equity": latest.equity,
                    "free_margin": latest.free_margin,
                    "used_margin": latest.used_margin,
                    "margin_level": latest.margin_level,
                    "balance": latest.balance,
                    "unrealized_pnl": latest.unrealized_pnl,
                    "timestamp": latest.timestamp.isoformat()
                }
            
            return {
                "success": True,
                "data": data
            }
        
        elif mode == "live":
            # LIVE mode - pobierz z Binance (read-only)
            binance = get_binance_client()
            account = binance.get_account_info()
            
            if not account:
                raise HTTPException(
                    status_code=401,
                    detail="Brak kluczy API Binance lub błąd autoryzacji"
                )
            
            # Oblicz equity i margin z balansów
            total_equity = 0.0
            usdt_balance = 0.0
            
            for bal in account["balances"]:
                if bal["asset"] == "USDT":
                    usdt_balance = bal["total"]
                    total_equity += bal["total"]
                # TODO: dodać wycenę innych assetów w USDT
            
            # Dla futures trzeba użyć innego endpointu
            # Na razie uproszczenie - spot only
            data = {
                "mode": "live",
                "equity": round(total_equity, 2),
                "free_margin": round(usdt_balance * 0.5, 2),  # Uproszczenie
                "used_margin": round(usdt_balance * 0.5, 2),
                "margin_level": 200.0,  # Placeholder
                "balance": round(usdt_balance, 2),
                "unrealized_pnl": 0.0,
                "timestamp": datetime.utcnow().isoformat(),
                "balances": account["balances"][:10]  # Top 10 balances
            }
            
            # Zapisz snapshot do bazy
            snapshot = AccountSnapshot(
                mode="live",
                equity=data["equity"],
                free_margin=data["free_margin"],
                used_margin=data["used_margin"],
                margin_level=data["margin_level"],
                balance=data["balance"],
                unrealized_pnl=data["unrealized_pnl"],
                timestamp=datetime.utcnow()
            )
            db.add(snapshot)
            db.commit()
            
            return {
                "success": True,
                "data": data
            }
        
        else:
            raise HTTPException(status_code=400, detail="Invalid mode. Use 'demo' or 'live'")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting account summary: {str(e)}")


@router.get("/history")
async def get_account_history(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    hours: int = Query(24, ge=1, le=168, description="Ile godzin wstecz (max 168 = tydzień)"),
    db: Session = Depends(get_db)
):
    """
    Pobierz historię equity/margin z ostatnich N godzin
    Do wykresów KPI
    """
    try:
        # Oblicz czas początkowy
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Pobierz snapshoty
        snapshots = db.query(AccountSnapshot).filter(
            AccountSnapshot.mode == mode,
            AccountSnapshot.timestamp >= since
        ).order_by(AccountSnapshot.timestamp).all()
        
        if not snapshots:
            # Wygeneruj placeholder dla demo
            if mode == "demo":
                DemoAccount.generate_snapshot(db)
                return await get_account_history(mode, hours, db)
            else:
                return {
                    "success": True,
                    "data": [],
                    "count": 0
                }
        
        # Formatuj dane
        history = []
        for snap in snapshots:
            history.append({
                "timestamp": snap.timestamp.isoformat(),
                "equity": snap.equity,
                "free_margin": snap.free_margin,
                "used_margin": snap.used_margin,
                "margin_level": snap.margin_level,
                "unrealized_pnl": snap.unrealized_pnl
            })
        
        return {
            "success": True,
            "mode": mode,
            "data": history,
            "count": len(history),
            "period_hours": hours
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting account history: {str(e)}")


@router.get("/kpi")
async def get_account_kpi(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Pobierz KPI konta (do dashboard)
    """
    try:
        # Pobierz aktualny snapshot
        latest = db.query(AccountSnapshot).filter(
            AccountSnapshot.mode == mode
        ).order_by(desc(AccountSnapshot.timestamp)).first()
        
        if not latest:
            if mode == "demo":
                # Wygeneruj pierwszy snapshot
                DemoAccount.generate_snapshot(db)
                return await get_account_kpi(mode, db)
            else:
                raise HTTPException(status_code=404, detail="No account data found")
        
        # Pobierz snapshot sprzed 24h
        day_ago = datetime.utcnow() - timedelta(hours=24)
        prev = db.query(AccountSnapshot).filter(
            AccountSnapshot.mode == mode,
            AccountSnapshot.timestamp <= day_ago
        ).order_by(desc(AccountSnapshot.timestamp)).first()
        
        # Oblicz zmiany
        equity_change = 0
        equity_change_percent = 0
        if prev:
            equity_change = latest.equity - prev.equity
            equity_change_percent = (equity_change / prev.equity * 100) if prev.equity > 0 else 0
        
        kpi = {
            "equity": round(latest.equity, 2),
            "equity_change": round(equity_change, 2),
            "equity_change_percent": round(equity_change_percent, 2),
            "free_margin": round(latest.free_margin, 2),
            "used_margin": round(latest.used_margin, 2),
            "margin_level": round(latest.margin_level, 2),
            "unrealized_pnl": round(latest.unrealized_pnl, 2),
            "balance": round(latest.balance, 2),
            "timestamp": latest.timestamp.isoformat()
        }
        
        return {
            "success": True,
            "mode": mode,
            "data": kpi
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting KPI: {str(e)}")
