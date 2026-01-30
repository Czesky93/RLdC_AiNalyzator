# Sentiment Analysis Module

**"The Eyes and Ears" of the RLdC AI Analyzer Bot**

This module provides real-time sentiment analysis of cryptocurrency news using advanced Natural Language Processing (NLP) techniques.

## Features

- 📰 **Real-time News Fetching**: Retrieves live headlines from reliable crypto RSS feeds (Cointelegraph, CoinDesk)
- 🧠 **Advanced NLP Analysis**: Uses FinBERT (Financial BERT) for specialized financial sentiment analysis
- 📊 **Market Sentiment Score**: Aggregates individual sentiments into an overall market score (-1.0 to +1.0)
- 🎯 **Qualitative Data Source**: Complements quantitative data (price/volume) with news sentiment

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

**Note**: The first run will download the FinBERT model (~450MB). This is a one-time download.

## Usage

### Quick Start

Run the demo service to see sentiment analysis in action:

```bash
cd sentiment_analysis
python service.py
```

This will:
1. Fetch the latest crypto news from RSS feeds
2. Analyze each headline using FinBERT
3. Display top headlines with sentiment scores
4. Show overall market sentiment

### Programmatic Usage

#### Fetch News Headlines

```python
from sentiment_analysis import NewsFetcher

# Initialize the news fetcher
fetcher = NewsFetcher()

# Get recent headlines (returns list of dicts with title, summary, link, etc.)
headlines = fetcher.fetch_headlines(max_items=20)

# Or get just the text for analysis
text_only = fetcher.fetch_text_only(max_items=20)
```

#### Analyze Sentiment

```python
from sentiment_analysis import SentimentEngine

# Initialize the sentiment engine (loads FinBERT model)
engine = SentimentEngine()

# Analyze a single headline
result = engine.analyze_text("Bitcoin reaches new all-time high!")
# Returns: {'label': 'positive', 'score': 0.95}

# Analyze multiple headlines
headlines = ["Bitcoin soars", "Market crash imminent", "Ethereum stable"]
results, market_score = engine.analyze_headlines(headlines)

# market_score: -1.0 (very bearish) to +1.0 (very bullish)
# results: list of individual sentiment results
```

#### Complete Pipeline

```python
from sentiment_analysis import NewsFetcher, SentimentEngine

# Fetch news
fetcher = NewsFetcher()
headlines = fetcher.fetch_text_only(max_items=15)

# Analyze sentiment
engine = SentimentEngine()
results, market_sentiment = engine.analyze_headlines(headlines)

# Get summary statistics
summary = engine.get_sentiment_summary(results)
print(f"Positive: {summary['positive']}, Negative: {summary['negative']}")
print(f"Market Sentiment Score: {market_sentiment:+.3f}")
```

## Components

### 1. NewsFetcher (`news_fetcher.py`)

Fetches real-time cryptocurrency news from RSS feeds.

**Key Methods:**
- `fetch_headlines(max_items)`: Returns full headline data (title, summary, link, published)
- `fetch_text_only(max_items)`: Returns text-only list optimized for sentiment analysis

**Default RSS Feeds:**
- Cointelegraph RSS
- CoinDesk RSS

### 2. SentimentEngine (`analyzer.py`)

Performs sentiment analysis using the FinBERT model.

**Key Methods:**
- `analyze_text(text)`: Analyzes a single text
- `analyze_headlines(headlines)`: Batch analyzes headlines and calculates market sentiment
- `get_sentiment_summary(results)`: Returns sentiment distribution statistics

**Model:**
- **ProsusAI/finbert**: A BERT-based model fine-tuned on financial text
- Classifies text as: Positive, Negative, or Neutral
- Provides confidence scores for each classification

### 3. Service (`service.py`)

Demo script that integrates fetching and analysis.

**Output:**
- Top headlines with sentiment scores
- Sentiment distribution (positive/negative/neutral %)
- Overall market sentiment interpretation

## Technical Details

### Dependencies

- **transformers**: HuggingFace library for FinBERT model
- **torch**: PyTorch backend for model inference
- **feedparser**: Reliable RSS feed parsing
- **requests**: HTTP requests (for future API integrations)

### Sentiment Scoring

Individual headlines are scored as:
- **Positive**: +score (e.g., +0.85 for 85% confident positive)
- **Negative**: -score (e.g., -0.92 for 92% confident negative)
- **Neutral**: 0.0

The **Market Sentiment Score** is the average of all individual scores:
- **> +0.2**: Strong bullish sentiment 🚀
- **+0.05 to +0.2**: Moderately bullish 📈
- **-0.05 to +0.05**: Neutral ➡️
- **-0.2 to -0.05**: Moderately bearish 📊
- **< -0.2**: Strong bearish sentiment 📉

## Example Output

```
================================================================================
CRYPTO MARKET SENTIMENT ANALYZER
================================================================================

Step 1: Fetching latest cryptocurrency news...
✓ Fetched 30 headlines from RSS feeds

Step 2: Initializing FinBERT Sentiment Analysis Engine...
Loading sentiment model: ProsusAI/finbert...
Model loaded successfully!

Step 3: Analyzing headline sentiments...
✓ Analysis complete!

TOP HEADLINES WITH SENTIMENT SCORES:
--------------------------------------------------------------------------------
1. 📈 POSITIVE (0.94)
   Bitcoin reaches new all-time high amid institutional adoption

2. 📉 NEGATIVE (0.89)
   SEC announces new cryptocurrency regulations

...

OVERALL MARKET SENTIMENT:
================================================================================
Market Sentiment Score: +0.152
Range: -1.0 (very negative) to +1.0 (very positive)

Interpretation: SLIGHTLY BULLISH 📈
Moderately positive sentiment
================================================================================
```

## Integration with Trading Bot

This module provides qualitative news sentiment data that can be combined with:
- **Quantitative Price Data**: Technical indicators, price movements
- **Volume Data**: Trading volume patterns
- **Other Metrics**: On-chain data, social media sentiment

The aggregated sentiment score can inform trading decisions or risk assessment.

## Future Enhancements

- [ ] Add more news sources (Twitter/X, Reddit, Telegram)
- [ ] Implement caching to avoid re-analyzing same headlines
- [ ] Add time-weighted sentiment (recent news weighted higher)
- [ ] Integration with specific coin/token filtering
- [ ] Real-time streaming analysis
- [ ] Sentiment trend analysis over time

## License

Part of the RLdC_AiNalyzator project.
