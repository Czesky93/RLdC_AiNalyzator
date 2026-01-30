"""
Authentication module for Telegram Bot.
Provides security decorator to restrict commands to the bot owner.
"""
import os
import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Cache OWNER_ID to avoid reading from environment on every call
_OWNER_ID = None


def _get_owner_id():
    """Get and cache the OWNER_ID from environment variables."""
    global _OWNER_ID
    if _OWNER_ID is None:
        owner_id = os.getenv('OWNER_ID')
        if owner_id is not None:
            try:
                _OWNER_ID = int(owner_id)
            except ValueError:
                logger.error("OWNER_ID environment variable is not a valid integer")
                return None
        else:
            logger.warning("OWNER_ID environment variable is not set")
            return None
    return _OWNER_ID


def restricted(func):
    """
    Decorator to restrict command access to the bot owner only.
    
    Checks if the user's ID matches the OWNER_ID from environment variables.
    If not authorized, sends a warning message and blocks the command.
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        owner_id = _get_owner_id()
        
        if owner_id is None:
            logger.warning(f"Access attempt by user {user_id} but OWNER_ID not configured")
            await update.effective_message.reply_text(
                "⚠️ Bot is not configured properly. OWNER_ID not set."
            )
            return
        
        if user_id != owner_id:
            logger.warning(f"Unauthorized access attempt by user {user_id} (expected {owner_id})")
            await update.effective_message.reply_text(
                "⛔ Access denied. This bot is restricted to the owner only."
            )
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapped
