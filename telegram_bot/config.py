"""Configuration module for Telegram Bot.

This module loads the Telegram Bot token from environment variables.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get the Telegram Bot token from environment
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN environment variable is not set. "
        "Please set it in your .env file or environment."
    )
