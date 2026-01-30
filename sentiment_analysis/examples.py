"""
Example Usage of the Sentiment Analysis Module

This file demonstrates various ways to use the sentiment analysis module
in different scenarios.
"""

# Import from current directory when run as script
try:
    from sentiment_analysis import NewsFetcher, SentimentEngine
except ImportError:
    from news_fetcher import NewsFetcher
    from analyzer import SentimentEngine


def example_basic_usage():
    """Basic usage example - fetch and analyze news."""
    print("=" * 80)
    print("EXAMPLE 1: Basic Usage")
    print("=" * 80)
    print()
    
    # Fetch news
    fetcher = NewsFetcher()
    headlines = fetcher.fetch_text_only(max_items=10)
    
    print(f"Fetched {len(headlines)} headlines")
    
    # Analyze sentiment
    engine = SentimentEngine()
    results, market_score = engine.analyze_headlines(headlines)
    
    print(f"Market Sentiment Score: {market_score:+.3f}")
    
    # Interpret
    sentiment_text, interpretation = engine.interpret_market_sentiment(market_score)
    print(f"Interpretation: {sentiment_text} - {interpretation}")
    print()


def example_single_text_analysis():
    """Analyze a single piece of text."""
    print("=" * 80)
    print("EXAMPLE 2: Single Text Analysis")
    print("=" * 80)
    print()
    
    engine = SentimentEngine()
    
    # Analyze individual texts
    texts = [
        "Bitcoin surges to new all-time high!",
        "Major exchange hacked, millions lost",
        "Market remains stable amid uncertainty"
    ]
    
    for text in texts:
        result = engine.analyze_text(text)
        emoji = engine.get_sentiment_emoji(result['label'])
        print(f"{emoji} {result['label'].upper()} ({result['score']:.2f}): {text}")
    
    print()


def example_integration_with_trading():
    """Example of integrating with a trading strategy."""
    print("=" * 80)
    print("EXAMPLE 3: Trading Integration")
    print("=" * 80)
    print()
    
    # Get market sentiment
    fetcher = NewsFetcher()
    engine = SentimentEngine()
    
    headlines = fetcher.fetch_text_only(max_items=20)
    results, sentiment_score = engine.analyze_headlines(headlines)
    
    # Simple trading logic based on sentiment
    print(f"Current Market Sentiment: {sentiment_score:+.3f}")
    print()
    
    if sentiment_score > 0.2:
        recommendation = "STRONG BUY - Positive news sentiment"
    elif sentiment_score > 0.05:
        recommendation = "BUY - Moderately positive sentiment"
    elif sentiment_score < -0.2:
        recommendation = "STRONG SELL - Negative news sentiment"
    elif sentiment_score < -0.05:
        recommendation = "SELL - Moderately negative sentiment"
    else:
        recommendation = "HOLD - Neutral sentiment"
    
    print(f"Trading Recommendation: {recommendation}")
    
    # Get distribution
    summary = engine.get_sentiment_summary(results)
    print(f"\nSentiment Distribution:")
    print(f"  Positive: {summary['positive']} ({summary['positive']/summary['total']*100:.1f}%)")
    print(f"  Negative: {summary['negative']} ({summary['negative']/summary['total']*100:.1f}%)")
    print(f"  Neutral:  {summary['neutral']} ({summary['neutral']/summary['total']*100:.1f}%)")
    print()


def example_filtering_by_sentiment():
    """Filter headlines by sentiment type."""
    print("=" * 80)
    print("EXAMPLE 4: Filtering Headlines")
    print("=" * 80)
    print()
    
    fetcher = NewsFetcher()
    engine = SentimentEngine()
    
    headlines = fetcher.fetch_text_only(max_items=20)
    results, _ = engine.analyze_headlines(headlines)
    
    # Filter positive news only
    positive_news = [r for r in results if 'positive' in r['label']]
    print(f"POSITIVE NEWS ({len(positive_news)} items):")
    for i, r in enumerate(positive_news[:5], 1):
        print(f"  {i}. {r['text'][:60]}... ({r['score']:.2f})")
    print()
    
    # Filter negative news only
    negative_news = [r for r in results if 'negative' in r['label']]
    print(f"NEGATIVE NEWS ({len(negative_news)} items):")
    for i, r in enumerate(negative_news[:5], 1):
        print(f"  {i}. {r['text'][:60]}... ({r['score']:.2f})")
    print()


def example_monitoring_loop():
    """Example of continuous monitoring (pseudo-code)."""
    print("=" * 80)
    print("EXAMPLE 5: Continuous Monitoring (Pseudo-code)")
    print("=" * 80)
    print()
    
    code = '''
import time
from sentiment_analysis import NewsFetcher, SentimentEngine

def monitor_sentiment(interval_minutes=30):
    """Monitor sentiment every N minutes."""
    fetcher = NewsFetcher()
    engine = SentimentEngine()
    
    while True:
        try:
            # Fetch and analyze
            headlines = fetcher.fetch_text_only(max_items=20)
            results, sentiment_score = engine.analyze_headlines(headlines)
            
            # Log sentiment
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] Market Sentiment: {sentiment_score:+.3f}")
            
            # Alert on extreme sentiment
            if abs(sentiment_score) > 0.3:
                sentiment_text, _ = engine.interpret_market_sentiment(sentiment_score)
                print(f"  ⚠️  ALERT: {sentiment_text}")
            
            # Wait before next check
            time.sleep(interval_minutes * 60)
            
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)  # Wait 1 minute on error

# Run monitoring
monitor_sentiment(interval_minutes=30)
'''
    
    print(code)
    print()


if __name__ == "__main__":
    print("\n")
    print("SENTIMENT ANALYSIS MODULE - USAGE EXAMPLES")
    print("=" * 80)
    print()
    print("This file demonstrates different ways to use the module.")
    print("Note: Examples 1-4 require network access to run.")
    print()
    
    # Run examples that don't require network
    example_monitoring_loop()
    
    print("\nFor more examples, see:")
    print("  - sentiment_analysis/service.py (complete pipeline)")
    print("  - sentiment_analysis/test.py (testing with sample data)")
    print("  - sentiment_analysis/README.md (detailed documentation)")
    print()
