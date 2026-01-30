"""
Backtesting Framework for Trading Strategies

This module provides tools for backtesting trading strategies against historical data.
"""

from .data_loader import HistoricalDataLoader
from .engine import Backtester
from .analytics import (
    calculate_total_return,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_sharpe_ratio,
    generate_report,
    print_report
)

__all__ = [
    'HistoricalDataLoader',
    'Backtester',
    'calculate_total_return',
    'calculate_max_drawdown',
    'calculate_win_rate',
    'calculate_sharpe_ratio',
    'generate_report',
    'print_report'
]
