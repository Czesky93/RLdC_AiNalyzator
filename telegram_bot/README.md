# Telegram Bot Interface

This module implements the Telegram Bot interface for RLdC AI Analyzer as described in Section 4.6 of the Project Plan.

## Features

- **Command Handlers**: `/start`, `/status`, `/portfolio`
- **Real-time Alerts**: Push notifications from Risk Engine and AI Trading modules
- **Portfolio Integration**: Access to real portfolio data via PortfolioManager

## Setup

### 1. Install Dependencies

```bash
cd telegram_bot
pip install -r requirements.txt
```

### 2. Configure Bot Token

Create a `.env` file in the project root (copy from `.env.example`):

```bash
cp ../.env.example ../.env
```

Then edit `.env` and add your Telegram bot token:

```
TELEGRAM_BOT_TOKEN=your_actual_bot_token_from_botfather
```

To get a bot token:
1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the instructions
3. Copy the token provided

### 3. Run the Bot

```bash
# From the telegram_bot directory
python -m telegram_bot.bot

# Or from the project root
python -m telegram_bot.bot
```

## Usage

Once the bot is running, open Telegram and:

1. Find your bot by the username you created
2. Send `/start` to see the welcome message
3. Use `/status` to check system status
4. Use `/portfolio` to view your portfolio

## Components

### `config.py`
Loads the `TELEGRAM_BOT_TOKEN` from environment variables using `python-dotenv`.

### `handlers.py`
Contains command handlers:
- `/start`: Welcome message explaining bot capabilities
- `/status`: Returns current system status (AI Trading, Blockchain, etc.)
- `/portfolio`: Returns portfolio summary (Cash balance, Holdings)

### `bot.py`
Initializes the Telegram `Application`, registers handlers, and provides a `run()` function to start polling.

### `notifier.py`
Alerting system with `send_alert(chat_id, message)` function for pushing notifications from other modules like Risk Engine or AI Trading.

## Integration Example

### Sending Alerts from Other Modules

```python
import asyncio
from telegram_bot.notifier import send_alert

# Send an alert
async def notify_risk_warning(chat_id):
    message = "⚠️ Risk Alert: Portfolio volatility exceeds threshold!"
    success = await send_alert(chat_id, message)
    if success:
        print("Alert sent successfully")

# Run it
asyncio.run(notify_risk_warning(123456789))
```

### Using Portfolio Manager

```python
from portfolio_management.portfolio import PortfolioManager

# Create portfolio instance
portfolio = PortfolioManager(initial_cash=10000.0)

# Get summary
summary = portfolio.get_portfolio_summary()
print(f"Cash: ${summary['cash']}")
print(f"Holdings: {summary['holdings']}")
```

## Architecture

The Telegram Bot serves as the **User Interface Layer**, enabling:

- Real-time monitoring of system status
- Portfolio overview and management
- Alert notifications for trading signals and risk warnings
- User interaction with the AI Trading system

## Security Notes

- Never commit your `.env` file or expose your bot token
- The `.env` file is listed in `.gitignore`
- Keep your bot token secret and rotate it if compromised

## Future Enhancements

- User authentication and authorization
- Trading command handlers (`/buy`, `/sell`)
- Historical performance charts
- Real-time price updates
- Multi-user support with individual portfolios
