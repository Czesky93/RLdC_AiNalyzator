"""Portfolio Manager for tracking assets and executing trades."""

from typing import Dict
from .transaction import Transaction


class InsufficientFundsError(Exception):
    """Raised when there are insufficient funds for a trade."""
    pass


class InsufficientHoldingsError(Exception):
    """Raised when there are insufficient holdings for a sell order."""
    pass


class PortfolioManager:
    """
    Manages portfolio cash balance and asset positions.
    
    Tracks cash balance and holdings across different assets,
    executes trades, and calculates portfolio value.
    """
    
    def __init__(self, initial_cash: float = 0.0):
        """
        Initialize the portfolio manager.
        
        Args:
            initial_cash: Starting cash balance
        """
        self.cash_balance = initial_cash
        self.positions: Dict[str, float] = {}
    
    def deposit(self, amount: float) -> None:
        """
        Deposit cash into the portfolio.
        
        Args:
            amount: Amount to deposit (must be positive)
        
        Raises:
            ValueError: If amount is not positive
        """
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.cash_balance += amount
    
    def withdraw(self, amount: float) -> None:
        """
        Withdraw cash from the portfolio.
        
        Args:
            amount: Amount to withdraw (must be positive)
        
        Raises:
            ValueError: If amount is not positive
            InsufficientFundsError: If withdrawal exceeds available cash
        """
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > self.cash_balance:
            raise InsufficientFundsError(
                f"Insufficient funds: requested {amount}, available {self.cash_balance}"
            )
        self.cash_balance -= amount
    
    def execute_trade(self, transaction: Transaction) -> None:
        """
        Execute a trade transaction.
        
        Updates cash balance and positions based on the transaction.
        For buy orders: decreases cash, increases position.
        For sell orders: increases cash, decreases position.
        
        Args:
            transaction: The transaction to execute
        
        Raises:
            ValueError: If transaction has invalid parameters
            InsufficientFundsError: If buying with insufficient cash
            InsufficientHoldingsError: If selling with insufficient holdings
        """
        # Validate transaction parameters
        if transaction.amount <= 0:
            raise ValueError("Transaction amount must be positive")
        if transaction.price <= 0:
            raise ValueError("Transaction price must be positive")
        if transaction.fee < 0:
            raise ValueError("Transaction fee cannot be negative")
        
        if transaction.side == 'buy':
            # For buy: total_cost = price * amount + fee
            if transaction.total_cost > self.cash_balance:
                raise InsufficientFundsError(
                    f"Insufficient funds for buy order: required {transaction.total_cost}, "
                    f"available {self.cash_balance}"
                )
            self.cash_balance -= transaction.total_cost
            current_position = self.positions.get(transaction.symbol, 0.0)
            self.positions[transaction.symbol] = current_position + transaction.amount
            
        elif transaction.side == 'sell':
            # For sell: total_cost = price * amount - fee (net proceeds)
            current_position = self.positions.get(transaction.symbol, 0.0)
            if transaction.amount > current_position:
                raise InsufficientHoldingsError(
                    f"Insufficient holdings for sell order: required {transaction.amount}, "
                    f"available {current_position}"
                )
            self.positions[transaction.symbol] = current_position - transaction.amount
            # Remove position if it becomes effectively zero (within floating point precision)
            if abs(self.positions[transaction.symbol]) < 1e-9:
                del self.positions[transaction.symbol]
            self.cash_balance += transaction.total_cost
        else:
            raise ValueError(f"Invalid transaction side: {transaction.side}")
    
    def get_total_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total portfolio value.
        
        Args:
            current_prices: Dictionary mapping symbols to their current market prices
        
        Returns:
            Total portfolio value (cash + sum of position values)
        """
        holdings_value = sum(
            amount * current_prices.get(symbol, 0.0)
            for symbol, amount in self.positions.items()
        )
        return self.cash_balance + holdings_value
    
    def get_portfolio_state(self) -> Dict:
        """
        Get current portfolio state.
        
        Returns:
            Dictionary containing cash balance and positions
        """
        return {
            'cash_balance': self.cash_balance,
            'positions': dict(self.positions)  # Return a copy
        }
