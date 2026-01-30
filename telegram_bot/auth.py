"""
Authentication module for Telegram Bot.
Provides security decorator to restrict commands to the bot owner.
"""
import os
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes


def restricted(func):
    """
    Decorator to restrict command access to the bot owner only.
    
    Checks if the user's ID matches the OWNER_ID from environment variables.
    If not authorized, sends a warning message and blocks the command.
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        owner_id = os.getenv('OWNER_ID')
        
        if owner_id is None:
            await update.effective_message.reply_text(
                "⚠️ Bot is not configured properly. OWNER_ID not set."
            )
            return
        
        try:
            owner_id = int(owner_id)
        except ValueError:
            await update.effective_message.reply_text(
                "⚠️ Bot is not configured properly. OWNER_ID is invalid."
            )
            return
        
        if user_id != owner_id:
            await update.effective_message.reply_text(
                "⛔ Access denied. This bot is restricted to the owner only."
            )
            return
        
        return await func(update, context, *args, **kwargs)
    
    return wrapped
