"""
Sentiment Analysis Service

Demo script that integrates news fetching and sentiment analysis
to provide real-time market sentiment insights.
"""

from news_fetcher import NewsFetcher
from analyzer import SentimentEngine


def main():
    """
    Main service that demonstrates the sentiment analysis pipeline.
    
    Steps:
    1. Fetch latest live news from RSS feeds
    2. Run FinBERT sentiment analysis
    3. Display individual headline sentiments
    4. Output overall market sentiment
    """
    
    print("=" * 80)
    print("CRYPTO MARKET SENTIMENT ANALYZER")
    print("=" * 80)
    print()
    
    # Step 1: Fetch latest news
    print("Step 1: Fetching latest cryptocurrency news...")
    print("-" * 80)
    
    news_fetcher = NewsFetcher()
    headlines = news_fetcher.fetch_text_only(max_items=15)
    
    print(f"✓ Fetched {len(headlines)} headlines from RSS feeds\n")
    
    # Step 2: Initialize sentiment analysis engine
    print("Step 2: Initializing FinBERT Sentiment Analysis Engine...")
    print("-" * 80)
    
    sentiment_engine = SentimentEngine(model_name="ProsusAI/finbert")
    print()
    
    # Step 3: Analyze headlines
    print("Step 3: Analyzing headline sentiments...")
    print("-" * 80)
    
    results, market_sentiment = sentiment_engine.analyze_headlines(headlines)
    
    print(f"\n✓ Analysis complete!\n")
    
    # Step 4: Display results
    print("Step 4: Results")
    print("=" * 80)
    print()
    
    # Display top headlines with sentiment scores
    print("TOP HEADLINES WITH SENTIMENT SCORES:")
    print("-" * 80)
    
    # Show top 10 most confident predictions
    sorted_results = sorted(results, key=lambda x: x['score'], reverse=True)
    
    for i, result in enumerate(sorted_results[:10], 1):
        sentiment_emoji = {
            'positive': '📈 ',
            'negative': '📉 ',
            'neutral': '➡️  '
        }
        
        emoji = sentiment_emoji.get(result['label'], '')
        label = result['label'].upper()
        score = result['score']
        text = result['text']
        
        print(f"{i}. {emoji}{label} ({score:.2f})")
        print(f"   {text}")
        print()
    
    # Display sentiment summary
    summary = sentiment_engine.get_sentiment_summary(results)
    
    print("SENTIMENT DISTRIBUTION:")
    print("-" * 80)
    print(f"Positive: {summary['positive']:3d} ({summary['positive']/summary['total']*100:.1f}%)")
    print(f"Negative: {summary['negative']:3d} ({summary['negative']/summary['total']*100:.1f}%)")
    print(f"Neutral:  {summary['neutral']:3d} ({summary['neutral']/summary['total']*100:.1f}%)")
    print(f"Total:    {summary['total']:3d}")
    print()
    
    # Display overall market sentiment
    print("OVERALL MARKET SENTIMENT:")
    print("=" * 80)
    
    # Interpret the sentiment score
    if market_sentiment > 0.2:
        sentiment_text = "BULLISH 🚀"
        interpretation = "Strong positive sentiment in crypto news"
    elif market_sentiment > 0.05:
        sentiment_text = "SLIGHTLY BULLISH 📈"
        interpretation = "Moderately positive sentiment"
    elif market_sentiment < -0.2:
        sentiment_text = "BEARISH 📉"
        interpretation = "Strong negative sentiment in crypto news"
    elif market_sentiment < -0.05:
        sentiment_text = "SLIGHTLY BEARISH 📊"
        interpretation = "Moderately negative sentiment"
    else:
        sentiment_text = "NEUTRAL ➡️"
        interpretation = "Mixed or neutral sentiment"
    
    print(f"\nMarket Sentiment Score: {market_sentiment:+.3f}")
    print(f"Range: -1.0 (very negative) to +1.0 (very positive)")
    print()
    print(f"Interpretation: {sentiment_text}")
    print(f"{interpretation}")
    print()
    print("=" * 80)
    
    return market_sentiment, results


if __name__ == "__main__":
    try:
        market_sentiment, results = main()
        print("\n✓ Sentiment analysis completed successfully!")
        
    except KeyboardInterrupt:
        print("\n\nAnalysis interrupted by user.")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
