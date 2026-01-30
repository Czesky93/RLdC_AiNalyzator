# AI Blog Engine

Automated trading analysis blog generator using AI.

## Features

- **Context Aggregation**: Collects data from sentiment analysis, market tracking, and portfolio modules
- **AI Content Generation**: Uses OpenAI GPT to generate professional blog posts (with mock fallback)
- **JSON Storage**: Simple file-based storage for blog posts
- **REST API**: Flask-based API for accessing and generating blog posts

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Set your OpenAI API key (optional - will use mock mode if not provided):

```
OPENAI_API_KEY=your_key_here
```

## Usage

### Starting the API Server

```bash
python web_portal/api/endpoints.py
```

The API will be available at `http://localhost:5000`

### API Endpoints

- `GET /blog/latest?limit=10` - Get latest blog posts
- `POST /blog/generate` - Generate a new blog post
- `GET /blog/post/<post_id>` - Get a specific post
- `GET /blog/tag/<tag>` - Get posts by tag
- `GET /blog/sentiment/<sentiment>` - Get posts by sentiment
- `GET /blog/stats` - Get blog statistics
- `GET /health` - Health check

### Example: Generate a Blog Post

```bash
curl -X POST http://localhost:5000/blog/generate
```

### Example: Get Latest Posts

```bash
curl http://localhost:5000/blog/latest?limit=5
```

## Module Structure

```
blog_generator/
├── __init__.py
├── aggregator.py    # Context data aggregation
├── engine.py        # AI content generation
└── storage.py       # JSON-based storage

web_portal/
└── api/
    ├── __init__.py
    └── endpoints.py # Flask REST API
```

## Development

### Running Tests

```bash
python -m pytest tests/
```

### Code Style

```bash
flake8 blog_generator/ web_portal/
```

## License

MIT
