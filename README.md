# RLdC AI Analyzer - Telegram Bot Command Center

Interactive Telegram Bot for managing and monitoring your AI-powered trading platform.

## Features

🤖 **Interactive Command Center**
- 📊 Portfolio overview
- 📈 System status monitoring
- 🧠 Real-time sentiment analysis
- 📰 Latest AI-generated analysis
- ⚙️ System controls for trading and AI management

🔒 **Secure Access**
- Owner-only authentication
- Restricted command access
- Callback query validation

🎛️ **System Controls**
- Start/Stop trading operations
- Restart AI systems
- Real-time status updates

## Setup

### Prerequisites

- Python 3.8 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- Your Telegram User ID

### Installation

1. Clone the repository:
```bash
git clone https://github.com/Czesky93/RLdC_AiNalyzator.git
cd RLdC_AiNalyzator
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
```

Edit `.env` and add your credentials:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
OWNER_ID=your_telegram_user_id_here
```

**How to get your Telegram User ID:**
- Message [@userinfobot](https://t.me/userinfobot) on Telegram
- It will reply with your user ID

### Running the Bot

```bash
python main.py
```

Or run the bot module directly:
```bash
python -m telegram_bot.bot
```

## Usage

Once the bot is running:

1. Open Telegram and find your bot
2. Send `/start` to initialize the command center
3. Use the interactive menu buttons to:
   - View your portfolio
   - Check system status
   - Analyze market sentiment
   - Read latest AI analysis
   - Control trading operations

### Available Commands

- `/start` - Show the main command center menu
- `/help` - Display help information

### Main Menu Options

- **📊 Portfolio** - View your current portfolio holdings and performance
- **📈 Status** - Check the status of trading and AI systems
- **🧠 Sentiment** - Get real-time market sentiment analysis
- **📰 Latest Analysis** - Read the most recent AI-generated market analysis
- **⚙️ System Controls** - Access trading and AI management controls

### System Controls

From the System Controls menu, you can:

- **🔴 Stop Trading** / **🟢 Start Trading** - Pause or resume automated trading
- **🔄 Restart AI** - Restart the AI analysis system

## Architecture

```
RLdC_AiNalyzator/
├── telegram_bot/
│   ├── __init__.py
│   ├── bot.py           # Main bot initialization
│   ├── handlers.py      # Command and callback handlers
│   ├── keyboards.py     # Inline keyboard layouts
│   ├── controls.py      # System state management
│   └── auth.py          # Authentication decorator
├── sentiment_analysis/
│   ├── __init__.py
│   └── service.py       # Sentiment analysis service
├── blog_generator/
│   ├── __init__.py
│   └── storage.py       # Blog post storage
├── main.py              # Entry point
├── requirements.txt     # Python dependencies
└── .env.example         # Environment variables template
```

## Security

- All commands are restricted to the bot owner (defined by OWNER_ID)
- Unauthorized access attempts are logged and denied
- System state is persisted securely

## Development

### Adding New Features

1. **New Menu Options**: Add buttons in `keyboards.py` and handlers in `handlers.py`
2. **New Controls**: Extend `controls.py` with new state management functions
3. **New Services**: Create modules similar to `sentiment_analysis` and `blog_generator`

### Testing

The bot uses mock data for sentiment analysis and blog posts. Replace these with your actual implementations:

- `sentiment_analysis/service.py` - Implement real sentiment analysis
- `blog_generator/storage.py` - Connect to your blog storage system

## License

This project is provided as-is for the RLdC AI Analyzer platform.

## Support

For issues or questions, please open an issue on GitHub.