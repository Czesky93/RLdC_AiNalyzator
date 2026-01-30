"""
Telegram Bot initialization and runner.
Main entry point for the RLdC AI Analyzer Telegram Bot.
"""
import os
import logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from .handlers import start, button_handler, help_command


# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """
    Main function to start the Telegram bot.
    """
    # Load environment variables
    load_dotenv()
    
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    owner_id = os.getenv('OWNER_ID')
    
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
        logger.error("Please create a .env file with your bot token.")
        logger.error("See .env.example for the required format.")
        return
    
    if not owner_id:
        logger.warning("OWNER_ID not found in environment variables!")
        logger.warning("Bot security will not work properly without OWNER_ID.")
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Register callback query handler for button interactions
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start the bot
    logger.info("Starting RLdC AI Analyzer Bot...")
    logger.info("Bot is running. Press Ctrl+C to stop.")
    
    # Run the bot until Ctrl+C
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == '__main__':
    main()
