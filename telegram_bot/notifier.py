"""Alerting and Notification System for Telegram Bot.

This module provides functionality to send alerts and notifications
to users via Telegram. Can be used by Risk Engine or AI Trading module.
"""
import logging
from telegram import Bot
from telegram.error import TelegramError

from .config import TELEGRAM_BOT_TOKEN

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def send_alert(chat_id: int, message: str) -> bool:
    """Send an alert message to a specific chat.
    
    This function can be called by the Risk Engine or AI Trading module
    to push notifications to users.
    
    Args:
        chat_id: Telegram chat ID to send the alert to
        message: Alert message to send
        
    Returns:
        True if message was sent successfully, False otherwise
        
    Example:
        >>> await send_alert(123456789, "⚠️ Risk Alert: Portfolio volatility high!")
    """
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        logger.info(f"Alert sent to chat_id {chat_id}: {message[:50]}...")
        return True
    except TelegramError as e:
        logger.error(f"Failed to send alert to chat_id {chat_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending alert: {e}")
        return False


async def send_bulk_alert(chat_ids: list, message: str) -> dict:
    """Send an alert to multiple chats.
    
    Args:
        chat_ids: List of Telegram chat IDs
        message: Alert message to send
        
    Returns:
        Dictionary with 'success' and 'failed' lists of chat_ids
        
    Example:
        >>> result = await send_bulk_alert([123, 456], "Market update!")
        >>> print(f"Sent to {len(result['success'])} chats")
    """
    results = {'success': [], 'failed': []}
    
    for chat_id in chat_ids:
        success = await send_alert(chat_id, message)
        if success:
            results['success'].append(chat_id)
        else:
            results['failed'].append(chat_id)
    
    logger.info(
        f"Bulk alert complete: {len(results['success'])} success, "
        f"{len(results['failed'])} failed"
    )
    return results
