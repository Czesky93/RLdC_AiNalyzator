"""
News Fetcher Module

Fetches real-time cryptocurrency news from reliable RSS feeds.
"""

import feedparser
import requests
from typing import List, Dict
from datetime import datetime


class NewsFetcher:
    """
    Fetches real-time cryptocurrency news headlines from RSS feeds.
    
    Uses reliable public crypto RSS feeds from sources like:
    - Cointelegraph
    - CoinDesk
    """
    
    def __init__(self):
        """Initialize the NewsFetcher with default RSS feed URLs."""
        self.rss_feeds = [
            'https://cointelegraph.com/rss',
            'https://www.coindesk.com/arc/outboundfeeds/rss/',
        ]
        
    def fetch_headlines(self, max_items: int = 20) -> List[Dict[str, str]]:
        """
        Fetch recent headlines from configured RSS feeds.
        
        Args:
            max_items: Maximum number of headlines to return per feed
            
        Returns:
            List of dictionaries containing 'title', 'summary', 'link', and 'published'
        """
        headlines = []
        
        for feed_url in self.rss_feeds:
            try:
                # Parse the RSS feed
                feed = feedparser.parse(feed_url)
                
                # Extract headlines from entries
                for entry in feed.entries[:max_items]:
                    headline = {
                        'title': entry.get('title', ''),
                        'summary': entry.get('summary', entry.get('description', '')),
                        'link': entry.get('link', ''),
                        'published': entry.get('published', '')
                    }
                    headlines.append(headline)
                    
            except Exception as e:
                print(f"Error fetching from {feed_url}: {str(e)}")
                continue
                
        return headlines
    
    def fetch_text_only(self, max_items: int = 20) -> List[str]:
        """
        Fetch recent headlines as text-only list for sentiment analysis.
        
        Combines title and summary for better context in analysis.
        
        Args:
            max_items: Maximum number of headlines to return per feed
            
        Returns:
            List of headline strings (title + summary combined)
        """
        headlines = self.fetch_headlines(max_items)
        
        # Combine title and summary for better context
        text_list = []
        for h in headlines:
            text = h.get('title', '')
            summary = h.get('summary', '')
            
            if summary and summary.strip() and summary.strip() != text.strip():
                # Add summary if it exists and is different from title
                text += ' - ' + summary
            text_list.append(text)
            
        return text_list
