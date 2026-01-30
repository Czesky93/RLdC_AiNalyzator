"""Risk Engine for validating trades against risk limits."""

from typing import Dict, Literal
from .portfolio import PortfolioManager


class RiskEngine:
    """
    Validates trades against risk management rules.
    
    Implements position sizing and drawdown checks to prevent
    excessive risk exposure.
    """
    
    def __init__(
        self,
        max_position_size_pct: float = 0.25,
        max_drawdown_pct: float = 0.20
    ):
        """
        Initialize the risk engine.
        
        Args:
            max_position_size_pct: Maximum percentage of portfolio value for a single trade (default 25%)
            max_drawdown_pct: Maximum drawdown percentage from initial balance (default 20%)
        """
        self.max_position_size_pct = max_position_size_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.initial_balance: float = 0.0
    
    def set_initial_balance(self, balance: float) -> None:
        """
        Set the initial balance for drawdown tracking.
        
        Args:
            balance: Initial portfolio balance
        """
        self.initial_balance = balance
    
    def check_trade_risk(
        self,
        portfolio: PortfolioManager,
        symbol: str,
        side: Literal['buy', 'sell'],
        amount: float,
        price: float,
        current_prices: Dict[str, float] = None
    ) -> bool:
        """
        Check if a trade passes risk management rules.
        
        Args:
            portfolio: The portfolio manager instance
            symbol: Trading symbol
            side: 'buy' or 'sell'
            amount: Trade amount
            price: Trade price
            current_prices: Dictionary of current market prices (required for position size check)
        
        Returns:
            True if trade passes all risk checks, False otherwise
        """
        # For buy orders, check max position size rule
        if side == 'buy':
            if current_prices is None:
                # Cannot check position size without current prices
                return False
            
            trade_value = amount * price
            total_portfolio_value = portfolio.get_total_value(current_prices)
            
            # Avoid division by zero
            if total_portfolio_value <= 0:
                return False
            
            position_size_pct = trade_value / total_portfolio_value
            
            if position_size_pct > self.max_position_size_pct:
                return False
        
        # Check max drawdown (if initial balance was set)
        if self.initial_balance > 0:
            if current_prices is None:
                current_prices = {}
            
            current_value = portfolio.get_total_value(current_prices)
            drawdown = (self.initial_balance - current_value) / self.initial_balance
            
            if drawdown > self.max_drawdown_pct:
                return False
        
        return True
    
    def check_max_drawdown(
        self,
        portfolio: PortfolioManager,
        current_prices: Dict[str, float] = None
    ) -> bool:
        """
        Check if current drawdown exceeds maximum allowed.
        
        Args:
            portfolio: The portfolio manager instance
            current_prices: Dictionary of current market prices
        
        Returns:
            True if within drawdown limits, False if exceeds
        """
        if self.initial_balance <= 0:
            # No initial balance set, cannot check drawdown
            return True
        
        if current_prices is None:
            current_prices = {}
        
        current_value = portfolio.get_total_value(current_prices)
        drawdown = (self.initial_balance - current_value) / self.initial_balance
        
        return drawdown <= self.max_drawdown_pct
