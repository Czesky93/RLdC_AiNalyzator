"""Paper trading engine with database persistence."""
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session
from database.models import Trade, PortfolioSnapshot, TradeSide


class PaperTrader:
    """Paper trading engine that persists trades to database."""
    
    def __init__(self, db_session: Session, initial_balance: float = 10000.0):
        """
        Initialize paper trader.
        
        Args:
            db_session: SQLAlchemy database session
            initial_balance: Starting cash balance in USDT
        """
        self.db = db_session
        self.cash_balance = initial_balance
        self.positions: Dict[str, float] = {}  # symbol -> amount
        self._step_counter = 0
        
        # Save initial portfolio snapshot
        self._save_portfolio_snapshot()
    
    def execute_order(
        self, 
        symbol: str, 
        side: str, 
        amount: float, 
        price: float,
        profit_loss: Optional[float] = None
    ) -> Trade:
        """
        Execute a trade order and persist it to database.
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            side: 'BUY' or 'SELL'
            amount: Amount to trade
            price: Price per unit
            profit_loss: Optional profit/loss for this trade
            
        Returns:
            The created Trade object
            
        Raises:
            ValueError: If invalid side or insufficient funds
        """
        if side not in ['BUY', 'SELL']:
            raise ValueError(f"Invalid side: {side}. Must be 'BUY' or 'SELL'")
        
        trade_side = TradeSide.BUY if side == 'BUY' else TradeSide.SELL
        total_cost = amount * price
        
        # Update internal state
        if side == 'BUY':
            if total_cost > self.cash_balance:
                raise ValueError(f"Insufficient funds. Need {total_cost}, have {self.cash_balance}")
            self.cash_balance -= total_cost
            self.positions[symbol] = self.positions.get(symbol, 0) + amount
        else:  # SELL
            if self.positions.get(symbol, 0) < amount:
                raise ValueError(f"Insufficient {symbol}. Need {amount}, have {self.positions.get(symbol, 0)}")
            self.cash_balance += total_cost
            self.positions[symbol] -= amount
            if self.positions[symbol] == 0:
                del self.positions[symbol]
        
        # Create and persist trade record
        trade = Trade(
            symbol=symbol,
            side=trade_side,
            amount=amount,
            price=price,
            timestamp=datetime.utcnow(),
            profit_loss=profit_loss
        )
        
        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)
        
        return trade
    
    def step(self, current_prices: Optional[Dict[str, float]] = None):
        """
        Perform a step in the trading simulation.
        Save portfolio snapshot periodically.
        
        Args:
            current_prices: Dictionary of symbol -> current price
        """
        self._step_counter += 1
        
        # Save portfolio snapshot every step
        self._save_portfolio_snapshot(current_prices)
    
    def _save_portfolio_snapshot(self, current_prices: Optional[Dict[str, float]] = None):
        """
        Save current portfolio state to database.
        
        Args:
            current_prices: Dictionary of symbol -> current price for calculating equity
        """
        # Calculate total equity
        total_equity = self.cash_balance
        
        if current_prices:
            for symbol, amount in self.positions.items():
                if symbol in current_prices:
                    total_equity += amount * current_prices[symbol]
        
        snapshot = PortfolioSnapshot(
            timestamp=datetime.utcnow(),
            total_equity_usdt=total_equity,
            cash_balance=self.cash_balance
        )
        
        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
    
    def get_portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate current total portfolio value.
        
        Args:
            current_prices: Dictionary of symbol -> current price
            
        Returns:
            Total portfolio value in USDT
        """
        total = self.cash_balance
        for symbol, amount in self.positions.items():
            if symbol in current_prices:
                total += amount * current_prices[symbol]
        return total
