"""Portfolio Manager for AI Trading System.

This module manages the portfolio, tracking cash balance and holdings.
"""


class PortfolioManager:
    """Manages portfolio with cash and holdings."""
    
    def __init__(self, initial_cash: float = 10000.0):
        """Initialize portfolio with initial cash balance.
        
        Args:
            initial_cash: Starting cash balance (default: $10,000)
        """
        self.cash = initial_cash
        self.holdings = {}  # {symbol: quantity}
    
    def get_cash_balance(self) -> float:
        """Get current cash balance.
        
        Returns:
            Current cash balance
        """
        return self.cash
    
    def get_holdings(self) -> dict:
        """Get current holdings.
        
        Returns:
            Dictionary of holdings {symbol: quantity}
        """
        return self.holdings.copy()
    
    def get_portfolio_summary(self) -> dict:
        """Get a summary of the portfolio.
        
        Returns:
            Dictionary with cash and holdings information
        """
        return {
            'cash': self.cash,
            'holdings': self.holdings.copy()
        }
