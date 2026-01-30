# RLdC_AiNalyzator

AI-powered trading analyzer with Telegram bot interface.

## Features

- **Telegram Bot Interface**: User-friendly interface for monitoring and controlling the system
- **Portfolio Management**: Track cash balance and holdings
- **Real-time Alerts**: Receive notifications about trading signals and risk warnings
- **System Status Monitoring**: Check if all components are operational

## Quick Start

### 1. Installation

```bash
# Install dependencies
pip install -r telegram_bot/requirements.txt
```

### 2. Configuration

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and add your Telegram bot token (get one from [@BotFather](https://t.me/botfather)):

```
TELEGRAM_BOT_TOKEN=your_actual_bot_token
```

### 3. Run the Bot

```bash
python -m telegram_bot.bot
```

### 4. Use the Bot

Open Telegram and find your bot, then use these commands:
- `/start` - Get started with the bot
- `/status` - Check system status
- `/portfolio` - View your portfolio

## Project Structure

```
RLdC_AiNalyzator/
├── telegram_bot/           # Telegram bot interface
│   ├── bot.py             # Main bot application
│   ├── handlers.py        # Command handlers
│   ├── notifier.py        # Alerting system
│   ├── config.py          # Configuration
│   ├── requirements.txt   # Python dependencies
│   └── README.md          # Detailed documentation
├── portfolio_management/   # Portfolio management module
│   └── portfolio.py       # PortfolioManager class
└── test_integration.py    # Integration tests

```

## Testing

Run the integration tests to verify all components:

```bash
python test_integration.py
```

## Documentation

See [telegram_bot/README.md](telegram_bot/README.md) for detailed documentation about the Telegram bot interface.

## Security

- Never commit your `.env` file
- Keep your Telegram bot token secret
- The `.env` file is already listed in `.gitignore`