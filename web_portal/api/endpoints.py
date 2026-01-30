"""
API Endpoints Module

Flask-based REST API endpoints for the blog engine.
"""

from flask import Flask, jsonify, request
from typing import Dict, Any
import sys
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path to import blog_generator modules
# Go two levels up from web_portal/api/ to reach the root directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from blog_generator.aggregator import ContextAggregator
from blog_generator.engine import BlogAuthor
from blog_generator.storage import BlogStorage


# Initialize Flask app
app = Flask(__name__)

# Initialize components
aggregator = ContextAggregator()
author = BlogAuthor()
storage = BlogStorage()


@app.route('/blog/latest', methods=['GET'])
def get_latest_blog_posts():
    """
    Get the latest blog posts.
    
    Query Parameters:
        limit (int): Number of posts to return (default: 10, max: 50)
    
    Returns:
        JSON response with list of blog posts.
    """
    try:
        limit = request.args.get('limit', default=10, type=int)
        
        # Validate limit parameter
        if limit < 1 or limit > 50:
            return jsonify({
                'success': False,
                'error': 'Invalid limit parameter. Must be between 1 and 50.'
            }), 400
        
        posts = storage.get_latest_posts(limit=limit)
        
        return jsonify({
            'success': True,
            'count': len(posts),
            'posts': posts
        }), 200
    except Exception as e:
        logger.error(f"Error getting latest posts: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An error occurred while retrieving posts'
        }), 500


@app.route('/blog/generate', methods=['POST'])
def generate_new_blog_post():
    """
    Generate a new blog post using current context data.
    
    Returns:
        JSON response with the newly generated blog post.
    """
    try:
        # Aggregate context from all sources
        context = aggregator.get_full_context()
        
        # Generate blog post
        post = author.generate_post(context)
        
        # Save to storage
        post_id = storage.save_post(post)
        
        return jsonify({
            'success': True,
            'message': 'Blog post generated successfully',
            'post_id': post_id,
            'post': post
        }), 201
    except Exception as e:
        logger.error(f"Error generating blog post: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An error occurred while generating the blog post'
        }), 500


@app.route('/blog/post/<post_id>', methods=['GET'])
def get_blog_post(post_id: str):
    """
    Get a specific blog post by ID.
    
    Args:
        post_id: The ID of the post to retrieve.
    
    Returns:
        JSON response with the blog post.
    """
    try:
        # Validate post_id length to prevent abuse
        if len(post_id) > 100:
            return jsonify({
                'success': False,
                'error': 'Invalid post ID'
            }), 400
        
        post = storage.get_post(post_id)
        
        if post is None:
            return jsonify({
                'success': False,
                'error': 'Post not found'
            }), 404
        
        return jsonify({
            'success': True,
            'post': post
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving post: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An error occurred while retrieving the post'
        }), 500


@app.route('/blog/tag/<tag>', methods=['GET'])
def get_posts_by_tag(tag: str):
    """
    Get blog posts filtered by tag.
    
    Args:
        tag: The tag to filter by.
    
    Returns:
        JSON response with filtered blog posts.
    """
    try:
        # Validate tag format (alphanumeric, hyphens, max 50 chars)
        if len(tag) > 50 or not all(c.isalnum() or c == '-' for c in tag):
            return jsonify({
                'success': False,
                'error': 'Invalid tag format'
            }), 400
        
        posts = storage.get_posts_by_tag(tag)
        
        return jsonify({
            'success': True,
            'tag': tag,
            'count': len(posts),
            'posts': posts
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving posts by tag: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An error occurred while retrieving posts'
        }), 500


@app.route('/blog/sentiment/<sentiment_label>', methods=['GET'])
def get_posts_by_sentiment(sentiment_label: str):
    """
    Get blog posts filtered by sentiment.
    
    Args:
        sentiment_label: The sentiment label to filter by.
    
    Returns:
        JSON response with filtered blog posts.
    """
    try:
        # Validate sentiment label
        valid_sentiments = {'bullish', 'bearish', 'neutral'}
        if sentiment_label not in valid_sentiments:
            return jsonify({
                'success': False,
                'error': f'Invalid sentiment. Must be one of: {", ".join(valid_sentiments)}'
            }), 400
        
        posts = storage.get_posts_by_sentiment(sentiment_label)
        
        return jsonify({
            'success': True,
            'sentiment': sentiment_label,
            'count': len(posts),
            'posts': posts
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving posts by sentiment: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An error occurred while retrieving posts'
        }), 500


@app.route('/blog/stats', methods=['GET'])
def get_blog_stats():
    """
    Get statistics about stored blog posts.
    
    Returns:
        JSON response with blog statistics.
    """
    try:
        stats = storage.get_storage_stats()
        
        return jsonify({
            'success': True,
            'stats': stats
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving blog stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': 'An error occurred while retrieving statistics'
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    
    Returns:
        JSON response indicating service health.
    """
    return jsonify({
        'success': True,
        'status': 'healthy',
        'service': 'AI Blog Engine'
    }), 200


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
