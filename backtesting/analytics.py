"""
Performance Analytics for backtesting results.
"""

import pandas as pd
import numpy as np
from typing import Dict, List


def calculate_total_return(equity_curve: pd.DataFrame, initial_capital: float) -> float:
    """
    Calculate the total return percentage.
    
    Args:
        equity_curve: DataFrame with equity curve data
        initial_capital: Initial capital amount
        
    Returns:
        Total return as a percentage
    """
    if equity_curve.empty:
        return 0.0
    
    final_value = equity_curve['total_value'].iloc[-1]
    return ((final_value - initial_capital) / initial_capital) * 100


def calculate_max_drawdown(equity_curve: pd.DataFrame) -> float:
    """
    Calculate the maximum drawdown percentage.
    
    Args:
        equity_curve: DataFrame with equity curve data
        
    Returns:
        Maximum drawdown as a percentage
    """
    if equity_curve.empty:
        return 0.0
    
    # Calculate running maximum
    running_max = equity_curve['total_value'].expanding().max()
    
    # Calculate drawdown at each point
    drawdown = (equity_curve['total_value'] - running_max) / running_max * 100
    
    # Return the maximum (most negative) drawdown
    return abs(drawdown.min())


def calculate_win_rate(trade_history: pd.DataFrame) -> float:
    """
    Calculate the win rate (percentage of profitable trades).
    
    Args:
        trade_history: DataFrame with trade history
        
    Returns:
        Win rate as a percentage
    """
    if trade_history.empty:
        return 0.0
    
    # Filter only SELL trades (which have PnL)
    sell_trades = trade_history[trade_history['type'] == 'SELL']
    
    if len(sell_trades) == 0:
        return 0.0
    
    # Count profitable trades
    winning_trades = len(sell_trades[sell_trades['pnl'] > 0])
    
    return (winning_trades / len(sell_trades)) * 100


def calculate_sharpe_ratio(equity_curve: pd.DataFrame, risk_free_rate: float = 0.0) -> float:
    """
    Calculate the Sharpe ratio (risk-adjusted return).
    
    Args:
        equity_curve: DataFrame with equity curve data
        risk_free_rate: Annual risk-free rate (default: 0.0)
        
    Returns:
        Sharpe ratio
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0
    
    # Calculate returns
    returns = equity_curve['total_value'].pct_change().dropna()
    
    if len(returns) == 0 or returns.std() == 0:
        return 0.0
    
    # Calculate excess returns
    excess_returns = returns - (risk_free_rate / 252)  # Assuming daily returns
    
    # Calculate Sharpe ratio
    sharpe = (excess_returns.mean() / returns.std()) * np.sqrt(252)
    
    return sharpe


def generate_report(equity_curve: pd.DataFrame, trade_history: pd.DataFrame, 
                   initial_capital: float) -> Dict:
    """
    Generate a comprehensive performance report.
    
    Args:
        equity_curve: DataFrame with equity curve data
        trade_history: DataFrame with trade history
        initial_capital: Initial capital amount
        
    Returns:
        Dictionary with performance metrics
    """
    total_return = calculate_total_return(equity_curve, initial_capital)
    max_drawdown = calculate_max_drawdown(equity_curve)
    win_rate = calculate_win_rate(trade_history)
    sharpe_ratio = calculate_sharpe_ratio(equity_curve)
    
    # Additional metrics
    final_value = equity_curve['total_value'].iloc[-1] if not equity_curve.empty else initial_capital
    
    # Count trades
    sell_trades = trade_history[trade_history['type'] == 'SELL'] if not trade_history.empty else pd.DataFrame()
    num_trades = len(sell_trades)
    
    # Average profit/loss per trade
    avg_pnl = sell_trades['pnl'].mean() if not sell_trades.empty else 0.0
    avg_pnl_pct = sell_trades['pnl_pct'].mean() if not sell_trades.empty else 0.0
    
    report = {
        'initial_capital': initial_capital,
        'final_value': final_value,
        'total_return_pct': total_return,
        'max_drawdown_pct': max_drawdown,
        'sharpe_ratio': sharpe_ratio,
        'win_rate_pct': win_rate,
        'num_trades': num_trades,
        'avg_pnl': avg_pnl,
        'avg_pnl_pct': avg_pnl_pct
    }
    
    return report


def print_report(report: Dict) -> None:
    """
    Print a formatted performance report.
    
    Args:
        report: Dictionary with performance metrics
    """
    print("\n" + "="*60)
    print("BACKTEST PERFORMANCE REPORT")
    print("="*60)
    print(f"Initial Capital:        ${report['initial_capital']:,.2f}")
    print(f"Final Value:            ${report['final_value']:,.2f}")
    print(f"Total Return:           {report['total_return_pct']:.2f}%")
    print(f"Max Drawdown:           {report['max_drawdown_pct']:.2f}%")
    print(f"Sharpe Ratio:           {report['sharpe_ratio']:.2f}")
    print(f"Win Rate:               {report['win_rate_pct']:.2f}%")
    print(f"Number of Trades:       {report['num_trades']}")
    print(f"Avg PnL per Trade:      ${report['avg_pnl']:.2f} ({report['avg_pnl_pct']:.2f}%)")
    print("="*60 + "\n")
