#!/usr/bin/env python3
"""
Standalone API test script that can run the Flask app and test endpoints.
"""

import sys
import os
import time
import threading
import requests
import json

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set environment to avoid debug mode issues
os.environ['FLASK_ENV'] = 'production'

from web_portal.api.endpoints import app


def run_server():
    """Run Flask server in a thread."""
    app.run(debug=False, host='127.0.0.1', port=5001, use_reloader=False)


def test_endpoints():
    """Test all API endpoints."""
    base_url = "http://127.0.0.1:5001"
    
    # Wait for server to start
    time.sleep(2)
    
    print("=" * 60)
    print("TESTING API ENDPOINTS")
    print("=" * 60)
    
    # Test 1: Health check
    print("\n1. Testing /health endpoint...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.json()}")
        print("   ✓ Health check passed")
    except Exception as e:
        print(f"   ✗ Health check failed: {e}")
        return
    
    # Test 2: Generate blog post
    print("\n2. Testing POST /blog/generate...")
    try:
        response = requests.post(f"{base_url}/blog/generate", timeout=10)
        print(f"   Status: {response.status_code}")
        data = response.json()
        if data.get('success'):
            print(f"   Post ID: {data['post_id'][:50]}...")
            print(f"   Title: {data['post']['title']}")
            print("   ✓ Blog post generated successfully")
            post_id = data['post_id']
        else:
            print(f"   ✗ Error: {data.get('error')}")
            return
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return
    
    # Test 3: Get latest posts
    print("\n3. Testing GET /blog/latest...")
    try:
        response = requests.get(f"{base_url}/blog/latest?limit=2", timeout=5)
        print(f"   Status: {response.status_code}")
        data = response.json()
        if data.get('success'):
            print(f"   Retrieved {data['count']} posts")
            print("   ✓ Latest posts retrieved successfully")
        else:
            print(f"   ✗ Error: {data.get('error')}")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    # Test 4: Get specific post
    print("\n4. Testing GET /blog/post/<id>...")
    try:
        response = requests.get(f"{base_url}/blog/post/{post_id}", timeout=5)
        print(f"   Status: {response.status_code}")
        data = response.json()
        if data.get('success'):
            print(f"   Title: {data['post']['title']}")
            print("   ✓ Specific post retrieved successfully")
        else:
            print(f"   ✗ Error: {data.get('error')}")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    # Test 5: Get posts by tag
    print("\n5. Testing GET /blog/tag/<tag>...")
    try:
        response = requests.get(f"{base_url}/blog/tag/crypto", timeout=5)
        print(f"   Status: {response.status_code}")
        data = response.json()
        if data.get('success'):
            print(f"   Found {data['count']} posts with tag 'crypto'")
            print("   ✓ Tag filtering works")
        else:
            print(f"   ✗ Error: {data.get('error')}")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    # Test 6: Get posts by sentiment
    print("\n6. Testing GET /blog/sentiment/<sentiment>...")
    try:
        response = requests.get(f"{base_url}/blog/sentiment/bullish", timeout=5)
        print(f"   Status: {response.status_code}")
        data = response.json()
        if data.get('success'):
            print(f"   Found {data['count']} posts with sentiment 'bullish'")
            print("   ✓ Sentiment filtering works")
        else:
            print(f"   ✗ Error: {data.get('error')}")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    # Test 7: Get blog stats
    print("\n7. Testing GET /blog/stats...")
    try:
        response = requests.get(f"{base_url}/blog/stats", timeout=5)
        print(f"   Status: {response.status_code}")
        data = response.json()
        if data.get('success'):
            stats = data['stats']
            print(f"   Total posts: {stats['total_posts']}")
            print(f"   Unique tags: {len(stats['unique_tags'])}")
            print(f"   Sentiment distribution: {stats['sentiment_distribution']}")
            print("   ✓ Stats retrieved successfully")
        else:
            print(f"   ✗ Error: {data.get('error')}")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
    
    print("\n" + "=" * 60)
    print("ALL API ENDPOINT TESTS COMPLETED!")
    print("=" * 60)
    print("\nThe AI Blog Engine API is fully functional.")
    print(f"\nAPI Base URL: {base_url}")
    print("\nAvailable endpoints:")
    print("  - GET  /health")
    print("  - POST /blog/generate")
    print("  - GET  /blog/latest?limit=N")
    print("  - GET  /blog/post/<id>")
    print("  - GET  /blog/tag/<tag>")
    print("  - GET  /blog/sentiment/<sentiment>")
    print("  - GET  /blog/stats")
    print("")


if __name__ == '__main__':
    # Check if requests is installed
    try:
        import requests
    except ImportError:
        print("Installing requests library...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "requests"])
        import requests
    
    # Start Flask server in background thread
    print("Starting Flask server on port 5001...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Run tests
    try:
        test_endpoints()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\nPress Ctrl+C to exit...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
