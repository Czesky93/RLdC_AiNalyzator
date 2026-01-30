#!/usr/bin/env python3
"""
Demo script to test the AI Blog Engine components.
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blog_generator.aggregator import ContextAggregator
from blog_generator.engine import BlogAuthor
from blog_generator.storage import BlogStorage


def demo_aggregator():
    """Demo the ContextAggregator."""
    print("=" * 60)
    print("DEMO: Context Aggregator")
    print("=" * 60)
    
    aggregator = ContextAggregator()
    
    print("\n1. Sentiment Context:")
    sentiment = aggregator.get_sentiment_context()
    print(f"   - Sentiment: {sentiment['sentiment_label']} ({sentiment['sentiment_score']})")
    print(f"   - Topics: {', '.join(sentiment['key_topics'])}")
    
    print("\n2. Market Context:")
    market = aggregator.get_market_context()
    print(f"   - BTC: ${market['BTC']['price']:,.2f} ({market['BTC']['change_24h']:+.2f}%)")
    print(f"   - ETH: ${market['ETH']['price']:,.2f} ({market['ETH']['change_24h']:+.2f}%)")
    
    print("\n3. Portfolio Activity:")
    portfolio = aggregator.get_portfolio_activity()
    print(f"   - Recent trades: {len(portfolio['recent_trades'])}")
    print(f"   - Portfolio value: ${portfolio['portfolio_value']:,.2f}")
    print(f"   - 24h P&L: ${portfolio['total_pnl_24h']:+,.2f}")
    
    print("\n4. Full Context:")
    context = aggregator.get_full_context()
    print(f"   - Aggregated at: {context['aggregated_at']}")
    print("   ✓ Context aggregation successful!")


def demo_blog_author():
    """Demo the BlogAuthor."""
    print("\n" + "=" * 60)
    print("DEMO: Blog Author (Content Generator)")
    print("=" * 60)
    
    aggregator = ContextAggregator()
    author = BlogAuthor()
    
    print("\nGenerating blog post...")
    context = aggregator.get_full_context()
    post = author.generate_post(context)
    
    print(f"\n✓ Blog post generated!")
    print(f"\nTitle: {post['title']}")
    print(f"Timestamp: {post['timestamp']}")
    print(f"Sentiment: {post['sentiment_label']}")
    print(f"Tags: {', '.join(post['tags'])}")
    print(f"\nContent Preview (first 200 chars):")
    print(f"{post['content'][:200]}...")


def demo_storage():
    """Demo the BlogStorage."""
    print("\n" + "=" * 60)
    print("DEMO: Blog Storage")
    print("=" * 60)
    
    # Use a test storage path
    test_storage_path = './data/test_blog_posts.json'
    storage = BlogStorage(storage_path=test_storage_path)
    
    # Clear any existing test data
    storage.clear_all_posts()
    
    # Generate and save some posts
    aggregator = ContextAggregator()
    author = BlogAuthor()
    
    print("\nGenerating and saving 3 blog posts...")
    for i in range(3):
        context = aggregator.get_full_context()
        post = author.generate_post(context)
        post_id = storage.save_post(post)
        print(f"   {i+1}. Saved post: {post_id[:30]}...")
    
    print("\n✓ Posts saved successfully!")
    
    # Retrieve posts
    print("\nRetrieving latest posts...")
    latest = storage.get_latest_posts(limit=2)
    print(f"   - Retrieved {len(latest)} posts")
    
    # Get stats
    print("\nStorage statistics:")
    stats = storage.get_storage_stats()
    print(f"   - Total posts: {stats['total_posts']}")
    print(f"   - Unique tags: {len(stats['unique_tags'])}")
    print(f"   - Sentiment distribution: {stats['sentiment_distribution']}")
    
    print("\n✓ Storage operations successful!")


def demo_full_workflow():
    """Demo the complete workflow."""
    print("\n" + "=" * 60)
    print("DEMO: Complete Workflow")
    print("=" * 60)
    
    # Initialize all components
    aggregator = ContextAggregator()
    author = BlogAuthor()
    storage = BlogStorage()
    
    print("\n1. Aggregating context data...")
    context = aggregator.get_full_context()
    print("   ✓ Context aggregated")
    
    print("\n2. Generating blog post...")
    post = author.generate_post(context)
    print(f"   ✓ Generated: '{post['title']}'")
    
    print("\n3. Saving to storage...")
    post_id = storage.save_post(post)
    print(f"   ✓ Saved with ID: {post_id[:30]}...")
    
    print("\n4. Retrieving from storage...")
    retrieved_post = storage.get_post(post_id)
    if retrieved_post:
        print(f"   ✓ Retrieved: '{retrieved_post['title']}'")
    
    print("\n✓ Complete workflow successful!")


def main():
    """Run all demos."""
    print("\n" + "=" * 60)
    print("AI BLOG ENGINE - COMPONENT DEMO")
    print("=" * 60)
    
    try:
        demo_aggregator()
        demo_blog_author()
        demo_storage()
        demo_full_workflow()
        
        print("\n" + "=" * 60)
        print("ALL DEMOS COMPLETED SUCCESSFULLY! ✓")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start the API server: python web_portal/api/endpoints.py")
        print("2. Generate a post: curl -X POST http://localhost:5000/blog/generate")
        print("3. View latest posts: curl http://localhost:5000/blog/latest")
        print("")
        
    except Exception as e:
        print(f"\n✗ Error during demo: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
