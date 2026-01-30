"""Telegram Bot Application.

This module initializes and runs the Telegram bot application.
"""
from telegram.ext import Application, CommandHandler
import logging

from .config import TELEGRAM_BOT_TOKEN
from .handlers import start_handler, status_handler, portfolio_handler

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def create_application() -> Application:
    """Create and configure the Telegram bot application.
    
    Returns:
        Configured Application instance
    """
    # Initialize the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(CommandHandler("portfolio", portfolio_handler))
    
    logger.info("Bot application created and handlers registered")
    return application


def run():
    """Start the bot and run it until interrupted.
    
    This function starts polling for updates and runs until Ctrl+C is pressed.
    """
    logger.info("Starting Telegram bot...")
    
    # Create the application
    application = create_application()
    
    # Start the bot
    logger.info("Bot is now running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    from telegram import Update
    run()
