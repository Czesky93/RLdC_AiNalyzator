"""Example script demonstrating the paper trading system with database persistence."""
from database.session import SessionLocal, init_db
from decision_engine.paper_trader import PaperTrader
from database.models import Trade, PortfolioSnapshot

def main():
    """Run a simple trading example."""
    # Initialize database
    print("Initializing database...")
    init_db()
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Create paper trader with $10,000 initial balance
        print("\nCreating paper trader with $10,000 initial balance...")
        trader = PaperTrader(db, initial_balance=10000.0)
        
        # Simulate some trades
        print("\n=== Executing Trades ===")
        
        # Buy BTC
        print("\n1. Buy 0.1 BTC at $50,000")
        trade1 = trader.execute_order("BTCUSDT", "BUY", 0.1, 50000.0)
        print(f"   Trade ID: {trade1.id}, Cash balance: ${trader.cash_balance:.2f}")
        
        # Update with current prices and save snapshot
        trader.step({"BTCUSDT": 51000.0})
        
        # Buy ETH
        print("\n2. Buy 1.0 ETH at $3,000")
        trade2 = trader.execute_order("ETHUSDT", "BUY", 1.0, 3000.0)
        print(f"   Trade ID: {trade2.id}, Cash balance: ${trader.cash_balance:.2f}")
        
        # Update with current prices
        trader.step({"BTCUSDT": 52000.0, "ETHUSDT": 3100.0})
        
        # Sell BTC with profit
        print("\n3. Sell 0.1 BTC at $52,000 (Profit: $200)")
        trade3 = trader.execute_order("BTCUSDT", "SELL", 0.1, 52000.0, profit_loss=200.0)
        print(f"   Trade ID: {trade3.id}, Cash balance: ${trader.cash_balance:.2f}")
        
        # Update with current prices
        trader.step({"ETHUSDT": 3200.0})
        
        # Sell ETH with profit
        print("\n4. Sell 1.0 ETH at $3,200 (Profit: $200)")
        trade4 = trader.execute_order("ETHUSDT", "SELL", 1.0, 3200.0, profit_loss=200.0)
        print(f"   Trade ID: {trade4.id}, Cash balance: ${trader.cash_balance:.2f}")
        
        # Final snapshot
        trader.step({})
        
        # Display results
        print("\n=== Trading Summary ===")
        print(f"Final cash balance: ${trader.cash_balance:.2f}")
        print(f"Total profit: ${trader.cash_balance - 10000.0:.2f}")
        
        # Query database for verification
        print("\n=== Database Verification ===")
        all_trades = db.query(Trade).all()
        print(f"Total trades in database: {len(all_trades)}")
        
        all_snapshots = db.query(PortfolioSnapshot).all()
        print(f"Total snapshots in database: {len(all_snapshots)}")
        
        print("\n=== Trade Details ===")
        for trade in all_trades:
            pnl_str = f", P/L: ${trade.profit_loss:.2f}" if trade.profit_loss else ""
            print(f"  {trade.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - "
                  f"{trade.side.value} {trade.amount} {trade.symbol} @ ${trade.price:.2f}{pnl_str}")
        
        print("\n=== Portfolio Snapshots ===")
        for snapshot in all_snapshots:
            print(f"  {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - "
                  f"Equity: ${snapshot.total_equity_usdt:.2f}, Cash: ${snapshot.cash_balance:.2f}")
        
        print("\n✓ Example completed successfully!")
        print("\nYou can now:")
        print("  1. Start the API server: python -m web_portal.api.main")
        print("  2. View trading history: GET http://localhost:8000/trading/history")
        print("  3. View equity curve: GET http://localhost:8000/trading/equity")
        print("  4. View trading stats: GET http://localhost:8000/trading/stats")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
