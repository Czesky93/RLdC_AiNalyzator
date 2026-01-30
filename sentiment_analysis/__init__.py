"""
Sentiment Analysis Module - "The Eyes and Ears" of the bot

This module provides real-time sentiment analysis of cryptocurrency news
using advanced NLP techniques with FinBERT model.
"""

from .news_fetcher import NewsFetcher
from .analyzer import SentimentEngine

__all__ = ['NewsFetcher', 'SentimentEngine']
