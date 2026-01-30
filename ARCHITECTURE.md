# Bot Architecture

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Telegram User                            │
│                    (Bot Owner Only)                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ /start, /help, button clicks
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   telegram_bot/bot.py                        │
│                   (Main Entry Point)                         │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  - Initialize Application                             │  │
│  │  - Register Handlers                                  │  │
│  │  - Start Polling                                      │  │
│  └───────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────────┐
         │   telegram_bot/auth.py            │
         │   (@restricted decorator)         │
         │                                   │
         │   ✓ Verify Owner ID               │
         │   ✓ Log Access Attempts           │
         │   ✓ Block Unauthorized Users      │
         └───────────────┬───────────────────┘
                         │ (if authorized)
                         ▼
         ┌───────────────────────────────────┐
         │   telegram_bot/handlers.py        │
         │   (Command & Callback Handlers)   │
         │                                   │
         │   • start()                       │
         │   • button_handler()              │
         │   • help_command()                │
         └───────────┬───────────────────────┘
                     │
         ┌───────────┴───────────────────────────────┐
         │                                           │
         ▼                                           ▼
┌──────────────────────┐                ┌──────────────────────┐
│ telegram_bot/        │                │ telegram_bot/        │
│ keyboards.py         │                │ controls.py          │
│                      │                │                      │
│ • get_main_menu()    │                │ SystemState:         │
│ • get_system_        │                │  • is_trading_paused │
│   controls_menu()    │                │  • pause_trading()   │
│ • get_back_button()  │                │  • resume_trading()  │
│                      │                │  • restart_ai()      │
└──────────────────────┘                │  • get_status()      │
                                        │                      │
                                        │ Persisted in:        │
                                        │ system_state.json    │
                                        └──────────────────────┘
                     │
         ┌───────────┴───────────────────────────────┐
         │                                           │
         ▼                                           ▼
┌──────────────────────┐                ┌──────────────────────┐
│ sentiment_analysis/  │                │ blog_generator/      │
│ service.py           │                │ storage.py           │
│                      │                │                      │
│ get_sentiment_score()│                │ get_latest_post()    │
│                      │                │                      │
│ Returns:             │                │ Returns:             │
│ • score              │                │ • title              │
│ • label              │                │ • summary            │
│ • confidence         │                │ • timestamp          │
│ • description        │                │ • url                │
└──────────────────────┘                └──────────────────────┘
```

## Data Flow

### User Interaction Flow

```
1. User sends /start
   ↓
2. Auth decorator checks OWNER_ID
   ↓
3. start() handler called
   ↓
4. get_main_menu() creates keyboard
   ↓
5. User sees main menu with buttons
   ↓
6. User clicks [🧠 Sentiment]
   ↓
7. Auth decorator checks OWNER_ID again
   ↓
8. button_handler() receives callback
   ↓
9. handle_sentiment() called
   ↓
10. get_sentiment_score() fetches data
    ↓
11. Message formatted and sent to user
```

### System Control Flow

```
1. User clicks [⚙️ System Controls]
   ↓
2. Auth decorator validates user
   ↓
3. handle_system_controls() called
   ↓
4. Checks system_state.is_trading_paused
   ↓
5. Shows control menu with appropriate buttons
   ↓
6. User clicks [🔴 Stop Trading]
   ↓
7. Auth decorator validates user
   ↓
8. handle_stop_trading() called
   ↓
9. system_state.pause_trading() updates state
   ↓
10. State saved to system_state.json
    ↓
11. Confirmation message shown to user
```

## State Management

```
SystemState Singleton
         │
         ├── In-Memory State
         │   ├── trading_paused: bool
         │   └── ai_status: str
         │
         └── Persistent Storage
             └── system_state.json
                 {
                   "trading_paused": false,
                   "ai_status": "running"
                 }
```

## Security Layers

```
┌─────────────────────────────────────┐
│  Layer 1: Telegram Protocol         │
│  (Built-in encryption)               │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Layer 2: Bot Token Authentication   │
│  (TELEGRAM_BOT_TOKEN)                │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Layer 3: Owner ID Verification      │
│  (@restricted decorator)             │
│                                      │
│  • Checks update.effective_user.id   │
│  • Compares with OWNER_ID            │
│  • Logs unauthorized attempts        │
│  • Blocks non-owner access           │
└─────────────────────────────────────┘
```

## Module Dependencies

```
main.py
  └── telegram_bot/bot.py
       ├── telegram_bot/handlers.py
       │    ├── telegram_bot/auth.py
       │    ├── telegram_bot/keyboards.py
       │    ├── telegram_bot/controls.py
       │    ├── sentiment_analysis/service.py
       │    └── blog_generator/storage.py
       └── python-telegram-bot (external)
```

## Error Handling Flow

```
User Action
    ↓
Try Block in Handler
    ↓
    ├── Success → Format & Send Response
    │
    └── Exception
         ↓
         ├── Log Error
         │    (logger.error())
         │
         └── Send User-Friendly Message
              ("❌ Unable to retrieve data")
```

## Extension Points

To extend the bot, modify these components:

1. **New Menu Items**: `keyboards.py` + `handlers.py`
2. **New Data Sources**: Create new service modules like `sentiment_analysis/`
3. **New Controls**: Extend `SystemState` in `controls.py`
4. **New Commands**: Add handlers in `handlers.py` and register in `bot.py`
