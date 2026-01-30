"""Command handlers for the Telegram Bot.

This module contains all command handlers for the bot, including:
- /start: Welcome message
- /status: System status
- /portfolio: Portfolio summary
"""
from telegram import Update
from telegram.ext import ContextTypes

try:
    from portfolio_management.portfolio import PortfolioManager
except ImportError:
    # Fallback if module structure is different
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from portfolio_management.portfolio import PortfolioManager


# Create a shared portfolio instance for PoC
_portfolio = PortfolioManager(initial_cash=10000.0)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - welcome message.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    welcome_message = (
        "🤖 *Welcome to RLdC AI Analyzer Bot!*\n\n"
        "I'm your AI-powered trading assistant. Here's what I can do:\n\n"
        "📊 *Available Commands:*\n"
        "/start - Show this welcome message\n"
        "/status - Check system status\n"
        "/portfolio - View your portfolio summary\n\n"
        "💡 I can also send you real-time alerts about:\n"
        "• Trading signals\n"
        "• Risk warnings\n"
        "• Market updates\n\n"
        "Let's get started! Use /status to check if everything is running smoothly."
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - return system status.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # For PoC, return static status. In production, this would check actual services
    status_message = (
        "🔍 *System Status*\n\n"
        "✅ AI Trading: Active\n"
        "✅ Blockchain Connection: OK\n"
        "✅ Risk Engine: Running\n"
        "✅ Portfolio Manager: Online\n\n"
        "🟢 All systems operational!"
    )
    await update.message.reply_text(status_message, parse_mode='Markdown')


async def portfolio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /portfolio command - return portfolio summary.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get portfolio data from PortfolioManager
    summary = _portfolio.get_portfolio_summary()
    cash = summary['cash']
    holdings = summary['holdings']
    
    # Format holdings for display
    holdings_text = ""
    if holdings:
        for symbol, quantity in holdings.items():
            holdings_text += f"  • {symbol}: {quantity} units\n"
    else:
        holdings_text = "  No holdings currently\n"
    
    portfolio_message = (
        f"💼 *Portfolio Summary*\n\n"
        f"💵 *Cash Balance:* ${cash:,.2f}\n\n"
        f"📈 *Holdings:*\n{holdings_text}\n"
        f"💡 Use the trading commands to manage your portfolio."
    )
    await update.message.reply_text(portfolio_message, parse_mode='Markdown')
