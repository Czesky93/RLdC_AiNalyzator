"""
Storage Module

Handles persistence of blog posts using JSON-based storage.
"""

import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path


class BlogStorage:
    """
    JSON-based storage handler for blog posts.
    
    Stores and retrieves blog posts from a JSON file, providing
    simple persistence without requiring a database.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize the BlogStorage.
        
        Args:
            storage_path: Path to the JSON storage file.
                         Defaults to './data/blog_posts.json'
        """
        if storage_path is None:
            storage_path = os.path.join(os.getcwd(), 'data', 'blog_posts.json')
        
        self.storage_path = storage_path
        self._ensure_storage_exists()
    
    def _ensure_storage_exists(self):
        """Ensure the storage directory and file exist."""
        # Create directory if it doesn't exist
        storage_dir = os.path.dirname(self.storage_path)
        if storage_dir:
            os.makedirs(storage_dir, exist_ok=True)
        
        # Create empty file if it doesn't exist
        if not os.path.exists(self.storage_path):
            with open(self.storage_path, 'w') as f:
                json.dump([], f)
    
    def save_post(self, post: Dict[str, Any]) -> str:
        """
        Save a blog post to storage.
        
        Args:
            post: Blog post dictionary to save.
            
        Returns:
            Post ID (generated from timestamp).
        """
        # Generate a unique ID based on timestamp
        post_id = post.get('timestamp', datetime.now().isoformat())
        post['id'] = post_id
        
        # Load existing posts
        posts = self.get_all_posts()
        
        # Add new post at the beginning (most recent first)
        posts.insert(0, post)
        
        # Save back to file
        with open(self.storage_path, 'w') as f:
            json.dump(posts, f, indent=2)
        
        return post_id
    
    def get_post(self, post_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific post by ID.
        
        Args:
            post_id: The ID of the post to retrieve.
            
        Returns:
            Post dictionary or None if not found.
        """
        posts = self.get_all_posts()
        for post in posts:
            if post.get('id') == post_id:
                return post
        return None
    
    def get_all_posts(self) -> List[Dict[str, Any]]:
        """
        Retrieve all blog posts.
        
        Returns:
            List of all blog posts, ordered by timestamp (newest first).
        """
        try:
            with open(self.storage_path, 'r') as f:
                posts = json.load(f)
                return posts if isinstance(posts, list) else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def get_latest_posts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve the most recent blog posts.
        
        Args:
            limit: Maximum number of posts to return.
            
        Returns:
            List of recent blog posts.
        """
        posts = self.get_all_posts()
        return posts[:limit]
    
    def get_posts_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """
        Retrieve posts filtered by tag.
        
        Args:
            tag: Tag to filter by.
            
        Returns:
            List of posts containing the specified tag.
        """
        posts = self.get_all_posts()
        return [post for post in posts if tag in post.get('tags', [])]
    
    def get_posts_by_sentiment(self, sentiment_label: str) -> List[Dict[str, Any]]:
        """
        Retrieve posts filtered by sentiment label.
        
        Args:
            sentiment_label: Sentiment label to filter by (e.g., 'bullish', 'bearish').
            
        Returns:
            List of posts with the specified sentiment.
        """
        posts = self.get_all_posts()
        return [post for post in posts if post.get('sentiment_label') == sentiment_label]
    
    def delete_post(self, post_id: str) -> bool:
        """
        Delete a post by ID.
        
        Args:
            post_id: The ID of the post to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        posts = self.get_all_posts()
        original_length = len(posts)
        posts = [post for post in posts if post.get('id') != post_id]
        
        if len(posts) < original_length:
            with open(self.storage_path, 'w') as f:
                json.dump(posts, f, indent=2)
            return True
        return False
    
    def clear_all_posts(self):
        """Clear all posts from storage. Use with caution!"""
        with open(self.storage_path, 'w') as f:
            json.dump([], f)
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get statistics about stored posts.
        
        Returns:
            Dictionary with storage statistics.
        """
        posts = self.get_all_posts()
        
        # Count posts by sentiment
        sentiment_counts = {}
        for post in posts:
            sentiment = post.get('sentiment_label', 'unknown')
            sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
        
        # Get all unique tags
        all_tags = set()
        for post in posts:
            all_tags.update(post.get('tags', []))
        
        return {
            'total_posts': len(posts),
            'sentiment_distribution': sentiment_counts,
            'unique_tags': list(all_tags),
            'storage_path': self.storage_path,
            'latest_post_timestamp': posts[0].get('timestamp') if posts else None
        }
