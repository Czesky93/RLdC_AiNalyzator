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
        "/help - Show this help message\n\n"
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
