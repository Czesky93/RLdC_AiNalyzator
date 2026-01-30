# RLdC_AiNalyzator

AI-powered cryptocurrency market analyzer with advanced sentiment analysis.

## Features

### 📊 Sentiment Analysis Module - "The Eyes and Ears"

Real-time cryptocurrency sentiment analysis using advanced NLP:

- **Live News Fetching**: Retrieves headlines from Cointelegraph, CoinDesk via RSS
- **FinBERT Analysis**: Uses specialized financial BERT model for sentiment classification
- **Market Sentiment Score**: Aggregates individual sentiments (-1.0 to +1.0)
- **Qualitative Data**: Complements price/volume with news sentiment insights

## Quick Start

### Install Dependencies

```bash
cd sentiment_analysis
pip install -r requirements.txt
```

### Run Sentiment Analysis

```bash
cd sentiment_analysis
python service.py
```

This will:
1. Fetch latest crypto news from RSS feeds
2. Analyze sentiment using FinBERT
3. Display top headlines with scores
4. Show overall market sentiment

## Project Structure

```
RLdC_AiNalyzator/
├── sentiment_analysis/          # Sentiment analysis module
│   ├── __init__.py             # Module initialization
│   ├── requirements.txt        # Python dependencies
│   ├── news_fetcher.py         # RSS news fetching
│   ├── analyzer.py             # FinBERT sentiment analysis
│   ├── service.py              # Demo/service script
│   ├── test.py                 # Test script
│   └── README.md               # Module documentation
└── README.md                   # This file
```

## Documentation

See [sentiment_analysis/README.md](sentiment_analysis/README.md) for detailed documentation on the sentiment analysis module.

## Technical Details

### Sentiment Analysis Pipeline

1. **News Fetching** (`NewsFetcher`)
   - Fetches from multiple RSS feeds
   - Filters and processes headlines
   - Returns structured data

2. **NLP Analysis** (`SentimentEngine`)
   - Loads FinBERT model (ProsusAI/finbert)
   - Classifies: Positive, Negative, Neutral
   - Provides confidence scores

3. **Aggregation**
   - Individual sentiment scores
   - Overall market sentiment
   - Statistical distribution

### Requirements

- Python 3.8+
- transformers (HuggingFace)
- torch (PyTorch)
- feedparser
- requests

## Future Enhancements

- Integration with trading strategies
- Real-time streaming analysis
- Multi-source aggregation (Twitter, Reddit)
- Historical sentiment tracking
- Coin-specific sentiment analysis