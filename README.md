# RLdC_AiNalyzator

AI-powered cryptocurrency trading analysis platform with automated blog generation.

## Overview

RLdC_AiNalyzator is a comprehensive trading analysis platform that automatically generates professional blog posts about cryptocurrency markets using AI. The system aggregates data from sentiment analysis, market tracking, and portfolio management modules to create insightful trading analysis content.

## Features

### AI Blog Engine

- **Context Aggregation**: Automatically collects data from:
  - Sentiment analysis (market mood, trending topics)
  - Market data (BTC/ETH prices, volume, changes)
  - Portfolio activity (recent trades, P&L)

- **AI Content Generation**: 
  - Uses OpenAI GPT for professional blog post generation
  - Automatic fallback to mock content when API key is unavailable
  - Generates titles, tags, and structured content

- **Persistent Storage**:
  - JSON-based file storage
  - Tag and sentiment filtering
  - Statistics tracking

- **REST API**:
  - Flask-based API endpoints
  - Full CRUD operations for blog posts
  - Health monitoring

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/Czesky93/RLdC_AiNalyzator.git
cd RLdC_AiNalyzator

# Install dependencies
pip install -r requirements.txt

# (Optional) Configure OpenAI API key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Running the Demo

```bash
# Test all components
python demo_blog_engine.py

# Test API endpoints
python test_api.py
```

### Starting the API Server

```bash
python web_portal/api/endpoints.py
```

The API will be available at `http://localhost:5000`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/blog/generate` | Generate new blog post |
| GET | `/blog/latest?limit=N` | Get latest N posts |
| GET | `/blog/post/<id>` | Get specific post |
| GET | `/blog/tag/<tag>` | Get posts by tag |
| GET | `/blog/sentiment/<sentiment>` | Get posts by sentiment |
| GET | `/blog/stats` | Get storage statistics |

### Example Usage

```bash
# Generate a new blog post
curl -X POST http://localhost:5000/blog/generate

# Get latest 5 posts
curl http://localhost:5000/blog/latest?limit=5

# Get posts tagged with 'bitcoin-rally'
curl http://localhost:5000/blog/tag/bitcoin-rally

# Get blog statistics
curl http://localhost:5000/blog/stats
```

## Project Structure

```
RLdC_AiNalyzator/
├── blog_generator/           # Core blog generation module
│   ├── __init__.py
│   ├── aggregator.py        # Data aggregation from various sources
│   ├── engine.py            # AI-powered content generation
│   └── storage.py           # JSON-based storage handler
│
├── web_portal/              # Web interface and API
│   └── api/
│       ├── __init__.py
│       └── endpoints.py     # Flask REST API endpoints
│
├── demo_blog_engine.py      # Component demonstration script
├── test_api.py              # API testing script
├── requirements.txt         # Python dependencies
├── .env.example            # Environment configuration template
└── BLOG_ENGINE_README.md   # Detailed blog engine documentation
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# OpenAI API key (optional - uses mock mode if not set)
OPENAI_API_KEY=your_api_key_here

# Storage path
BLOG_STORAGE_PATH=./data/blog_posts.json
```

## Development

### Running Tests

```bash
# Run component tests
python demo_blog_engine.py

# Run API tests
python test_api.py
```

### Code Style

The project follows PEP 8 style guidelines. Run linters:

```bash
flake8 blog_generator/ web_portal/
```

## Architecture

The AI Blog Engine follows a modular architecture:

1. **ContextAggregator**: Fetches and aggregates data from multiple sources
2. **BlogAuthor**: Uses LLM to generate blog content from context
3. **BlogStorage**: Persists blog posts to JSON file
4. **API Endpoints**: Exposes functionality via REST API

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License

## Author

Czesky93

---

For detailed blog engine documentation, see [BLOG_ENGINE_README.md](BLOG_ENGINE_README.md)