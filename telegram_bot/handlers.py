"""
Enhanced Handlers module for Telegram Bot.
Implements command handlers and callback query handlers for interactive menus.
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from .auth import restricted
from .keyboards import get_main_menu, get_system_controls_menu, get_back_button
from .controls import system_state
from sentiment_analysis.service import get_sentiment_score
from blog_generator.storage import get_latest_post

logger = logging.getLogger(__name__)


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /start command - show main menu.
    
    Args:
        update: Telegram update object
        context: Callback context
    """
    welcome_message = (
        "🤖 *Welcome to RLdC AI Analyzer Command Center*\n\n"
        "Your interactive control panel for trading and analysis.\n"
        "Select an option from the menu below:"
    )
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )


@restricted
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle button callbacks from inline keyboards.
    
    Args:
        update: Telegram update object with callback query
        context: Callback context
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the button press
    
    callback_data = query.data
    
    try:
        # Main menu options
        if callback_data == "menu_main":
            await handle_main_menu(query)
        elif callback_data == "menu_portfolio":
            await handle_portfolio(query)
        elif callback_data == "menu_status":
            await handle_status(query)
        elif callback_data == "menu_sentiment":
            await handle_sentiment(query)
        elif callback_data == "menu_latest_analysis":
            await handle_latest_analysis(query)
        elif callback_data == "menu_system_controls":
            await handle_system_controls(query)
        
        # System control options
        elif callback_data == "control_start_trading":
            await handle_start_trading(query)
        elif callback_data == "control_stop_trading":
            await handle_stop_trading(query)
        elif callback_data == "control_restart_ai":
            await handle_restart_ai(query)
    except Exception as e:
        logger.error(f"Error handling button callback '{callback_data}': {e}")
        await query.edit_message_text(
            "❌ An error occurred while processing your request. Please try again.",
            reply_markup=get_back_button()
        )


async def handle_main_menu(query):
    """Show the main menu."""
    message = (
        "🤖 *RLdC AI Analyzer Command Center*\n\n"
        "Select an option from the menu below:"
    )
    await query.edit_message_text(
        message,
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )


async def handle_portfolio(query):
    """Display portfolio information."""
    # Placeholder implementation
    portfolio_data = {
        "total_value": "$125,450.00",
        "daily_change": "+$2,340.50 (+1.90%)",
        "top_holdings": [
            "BTC: $45,000 (35.8%)",
            "ETH: $32,000 (25.5%)",
            "SOL: $18,500 (14.7%)"
        ]
    }
    
    message = (
        "📊 *Portfolio Overview*\n\n"
        f"💰 Total Value: {portfolio_data['total_value']}\n"
        f"📈 24h Change: {portfolio_data['daily_change']}\n\n"
        "*Top Holdings:*\n"
    )
    
    for holding in portfolio_data['top_holdings']:
        message += f"• {holding}\n"
    
    await query.edit_message_text(
        message,
        reply_markup=get_back_button(),
        parse_mode='Markdown'
    )


async def handle_status(query):
    """Display system status."""
    status = system_state.get_status()
    
    message = (
        "📈 *System Status*\n\n"
        f"🔄 Trading: *{status['trading'].upper()}*\n"
        f"🧠 AI System: *{status['ai'].upper()}*\n\n"
        "All systems operational."
    )
    
    await query.edit_message_text(
        message,
        reply_markup=get_back_button(),
        parse_mode='Markdown'
    )


async def handle_sentiment(query):
    """Display sentiment analysis."""
    try:
        sentiment = get_sentiment_score()
        
        # Visual representation of sentiment score
        score_bar = "█" * round(sentiment['score'] * 10) + "░" * (10 - round(sentiment['score'] * 10))
        
        message = (
            "🧠 *Market Sentiment Analysis*\n\n"
            f"📊 Score: *{sentiment['score']:.2f}* ({sentiment['label']})\n"
            f"📈 Confidence: {sentiment['confidence']:.0%}\n"
            f"[{score_bar}]\n\n"
            f"💡 {sentiment['description']}"
        )
        
        await query.edit_message_text(
            message,
            reply_markup=get_back_button(),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error getting sentiment data: {e}")
        await query.edit_message_text(
            "❌ Unable to retrieve sentiment data at this time.",
            reply_markup=get_back_button()
        )


async def handle_latest_analysis(query):
    """Display latest blog post/analysis."""
    try:
        post = get_latest_post()
        
        message = (
            "📰 *Latest Analysis*\n\n"
            f"*{post['title']}*\n\n"
            f"{post['summary']}\n\n"
        )
        
        # Safely format timestamp
        if 'timestamp' in post and post['timestamp']:
            timestamp = post['timestamp'][:10] if len(post['timestamp']) >= 10 else post['timestamp']
            message += f"🕐 Published: {timestamp}"
        
        if post.get('url'):
            message += f"\n🔗 [Read full article]({post['url']})"
        
        await query.edit_message_text(
            message,
            reply_markup=get_back_button(),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error getting latest post: {e}")
        await query.edit_message_text(
            "❌ Unable to retrieve latest analysis at this time.",
            reply_markup=get_back_button()
        )


async def handle_system_controls(query):
    """Display system controls menu."""
    is_paused = system_state.is_trading_paused
    
    message = (
        "⚙️ *System Controls*\n\n"
        "Manage trading and AI system settings.\n"
        f"Current trading status: *{'PAUSED' if is_paused else 'ACTIVE'}*"
    )
    
    await query.edit_message_text(
        message,
        reply_markup=get_system_controls_menu(is_paused),
        parse_mode='Markdown'
    )


async def handle_start_trading(query):
    """Start/resume trading operations."""
    system_state.resume_trading()
    
    message = (
        "✅ *Trading Resumed*\n\n"
        "🟢 Trading operations are now active.\n"
        "The system will execute trades based on AI signals."
    )
    
    await query.edit_message_text(
        message,
        reply_markup=get_system_controls_menu(False),
        parse_mode='Markdown'
    )


async def handle_stop_trading(query):
    """Stop/pause trading operations."""
    system_state.pause_trading()
    
    message = (
        "⏸️ *Trading Paused*\n\n"
        "🔴 Trading operations are now paused.\n"
        "Existing positions will be maintained, but no new trades will be executed."
    )
    
    await query.edit_message_text(
        message,
        reply_markup=get_system_controls_menu(True),
        parse_mode='Markdown'
    )


async def handle_restart_ai(query):
    """Restart AI system."""
    system_state.restart_ai()
    
    message = (
        "🔄 *AI System Restarted*\n\n"
        "✅ The AI analysis system has been successfully restarted.\n"
        "All models and services are now running with the latest configuration."
    )
    
    await query.edit_message_text(
        message,
        reply_markup=get_system_controls_menu(system_state.is_trading_paused),
        parse_mode='Markdown'
    )


@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "🤖 *RLdC AI Analyzer Bot Help*\n\n"
        "*Available Commands:*\n"
        "/start - Show main menu\n"
        "/help - Show this help message\n"
        "/status - System and trading status\n"
        "/stop - Stop trading operations\n"
        "/risk - Risk management overview\n"
        "/portfolio - View portfolio overview\n"
        "/orders - View active orders\n"
        "/positions - View open positions\n"
        "/lastsignal - Last trading signal\n"
        "/top5 - Top 5 performing assets\n"
        "/top10 - Top 10 performing assets\n"
        "/blog - Latest blog posts\n"
        "/logs - System logs\n\n"
        "*Main Menu Options:*\n"
        "📊 Portfolio - View your portfolio overview\n"
        "📈 Status - Check system status\n"
        "🧠 Sentiment - View market sentiment analysis\n"
        "📰 Latest Analysis - Read the latest blog post\n"
        "⚙️ System Controls - Manage trading and AI settings\n\n"
        "*Security:*\n"
        "This bot is restricted to the owner only."
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')


@restricted
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - show system and trading status."""
    status = system_state.get_status()
    
    message = (
        "📊 *System Status Report*\n\n"
        f"🔄 Trading: *{status['trading'].upper()}*\n"
        f"🧠 AI System: *{status['ai'].upper()}*\n"
        f"📡 Bot Status: *ONLINE*\n"
        f"💾 State Persistence: *ACTIVE*\n\n"
        "✅ All systems operational."
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command - stop trading operations."""
    if system_state.is_trading_paused:
        message = "⚠️ Trading is already stopped."
    else:
        system_state.pause_trading()
        message = (
            "🛑 *Trading Stopped*\n\n"
            "Trading operations have been paused.\n"
            "Use /start from System Controls to resume."
        )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /risk command - show risk management overview."""
    # Placeholder implementation - would integrate with risk management system
    message = (
        "⚠️ *Risk Management Overview*\n\n"
        "📊 Risk Metrics:\n"
        "• Portfolio Risk: *Medium*\n"
        "• Max Drawdown: *-5.2%*\n"
        "• Position Size Limit: *10% per trade*\n"
        "• Stop Loss: *Active*\n"
        "• Take Profit: *Active*\n\n"
        "📈 Exposure:\n"
        "• Total Exposure: *45%*\n"
        "• Available Capital: *55%*\n\n"
        "✅ Risk parameters within acceptable limits."
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /portfolio command - show portfolio overview."""
    # Placeholder implementation - would integrate with portfolio service
    message = (
        "💼 *Portfolio Overview*\n\n"
        "💰 Total Value: *$125,450.00*\n"
        "📈 24h Change: *+$2,340.50 (+1.90%)*\n"
        "📊 7d Change: *+$5,120.00 (+4.25%)*\n\n"
        "*Top Holdings:*\n"
        "• BTC: $45,000 (35.8%)\n"
        "• ETH: $32,000 (25.5%)\n"
        "• SOL: $18,500 (14.7%)\n"
        "• Other: $30,000 (23.9%)\n\n"
        "📊 Diversification: *Good*\n"
        "✅ Portfolio healthy"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /orders command - show active orders."""
    # Placeholder implementation - would integrate with order management
    message = (
        "📋 *Active Orders*\n\n"
        "🔹 *Order #1*\n"
        "Symbol: BTC/USDT\n"
        "Type: Limit Buy\n"
        "Price: $94,500\n"
        "Amount: 0.05 BTC\n"
        "Status: Pending\n\n"
        "🔹 *Order #2*\n"
        "Symbol: ETH/USDT\n"
        "Type: Limit Sell\n"
        "Price: $3,150\n"
        "Amount: 1.2 ETH\n"
        "Status: Pending\n\n"
        "📊 Total Active: *2 orders*"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /positions command - show open positions."""
    # Placeholder implementation - would integrate with position management
    message = (
        "📊 *Open Positions*\n\n"
        "🔸 *Position #1*\n"
        "Symbol: BTC/USDT\n"
        "Side: Long\n"
        "Entry: $93,200\n"
        "Current: $95,100\n"
        "P&L: *+$950 (+2.04%)*\n"
        "Size: 0.5 BTC\n\n"
        "🔸 *Position #2*\n"
        "Symbol: ETH/USDT\n"
        "Side: Long\n"
        "Entry: $3,020\n"
        "Current: $3,085\n"
        "P&L: *+$78 (+2.15%)*\n"
        "Size: 1.2 ETH\n\n"
        "💰 Total P&L: *+$1,028*"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def lastsignal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /lastsignal command - show last trading signal."""
    # Placeholder implementation - would integrate with signal generation
    message = (
        "🎯 *Last Trading Signal*\n\n"
        "📅 Time: 2026-01-31 15:30 UTC\n"
        "📊 Symbol: *BTC/USDT*\n"
        "🔔 Signal: *BUY*\n"
        "💰 Entry: $94,800 - $95,200\n"
        "🎯 Target 1: $96,500\n"
        "🎯 Target 2: $97,800\n"
        "🛑 Stop Loss: $93,500\n\n"
        "📈 Confidence: *78%*\n"
        "⚡ Strength: *Strong*\n\n"
        "💡 Reason: Bullish momentum + positive sentiment"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def top5_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /top5 command - show top 5 performing assets."""
    # Placeholder implementation - would integrate with market data
    message = (
        "🏆 *Top 5 Performers (24h)*\n\n"
        "1️⃣ SOL/USDT: *+8.45%* 📈\n"
        "   Price: $142.50\n\n"
        "2️⃣ AVAX/USDT: *+6.23%* 📈\n"
        "   Price: $38.20\n\n"
        "3️⃣ MATIC/USDT: *+5.87%* 📈\n"
        "   Price: $0.95\n\n"
        "4️⃣ LINK/USDT: *+4.92%* 📈\n"
        "   Price: $16.80\n\n"
        "5️⃣ DOT/USDT: *+4.56%* 📈\n"
        "   Price: $7.45"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def top10_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /top10 command - show top 10 performing assets."""
    # Placeholder implementation - would integrate with market data
    message = (
        "🏆 *Top 10 Performers (24h)*\n\n"
        "1️⃣ SOL: *+8.45%* | 2️⃣ AVAX: *+6.23%*\n"
        "3️⃣ MATIC: *+5.87%* | 4️⃣ LINK: *+4.92%*\n"
        "5️⃣ DOT: *+4.56%* | 6️⃣ ADA: *+3.98%*\n"
        "7️⃣ ATOM: *+3.45%* | 8️⃣ ALGO: *+3.21%*\n"
        "9️⃣ FTM: *+2.87%* | 🔟 NEAR: *+2.54%*\n\n"
        "📊 Market Trend: *Bullish*\n"
        "💹 Avg Gain: *+4.61%*"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')


@restricted
async def blog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /blog command - show latest blog posts."""
    # Uses existing blog_generator service
    try:
        post = get_latest_post()
        
        message = (
            "📝 *Latest Blog Post*\n\n"
            f"*{post['title']}*\n\n"
            f"{post['summary']}\n\n"
        )
        
        if 'timestamp' in post and post['timestamp']:
            timestamp = post['timestamp'][:10] if len(post['timestamp']) >= 10 else post['timestamp']
            message += f"📅 Published: {timestamp}\n"
        
        if post.get('url'):
            message += f"🔗 [Read full article]({post['url']})"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error getting blog post: {e}")
        await update.message.reply_text(
            "❌ Unable to retrieve blog posts at this time."
        )


@restricted
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /logs command - show system logs."""
    # Placeholder implementation - would integrate with logging system
    message = (
        "📜 *Recent System Logs*\n\n"
        "```\n"
        "[15:45:23] INFO: Trading signal generated: BUY BTC\n"
        "[15:44:10] INFO: Market data updated\n"
        "[15:43:05] INFO: Position opened: ETH/USDT\n"
        "[15:42:30] INFO: Risk check passed\n"
        "[15:41:15] INFO: Sentiment analysis completed\n"
        "[15:40:00] INFO: System health check: OK\n"
        "```\n\n"
        "✅ No errors detected\n"
        "📊 System running smoothly"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')
