"""
Content Generator Module

Generates blog posts using AI/LLM based on aggregated context data.
"""

import os
from typing import Dict, Any, Optional
from datetime import datetime
import json


class BlogAuthor:
    """
    AI-powered blog post generator.
    
    Generates trading analysis blog posts using LLM (OpenAI GPT) based on
    aggregated context from sentiment, market, and portfolio data.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the BlogAuthor.
        
        Args:
            api_key: OpenAI API key. If not provided, will try to load from
                    environment variable OPENAI_API_KEY.
        """
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.use_mock = not self.api_key
        
        if not self.use_mock:
            try:
                import openai
                self.client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                print("Warning: openai package not installed. Using mock mode.")
                self.use_mock = True
    
    def _construct_prompt(self, context: Dict[str, Any]) -> str:
        """
        Construct the prompt for the LLM based on context data.
        
        Args:
            context: Aggregated context data from ContextAggregator.
            
        Returns:
            Formatted prompt string.
        """
        sentiment = context.get('sentiment', {})
        market = context.get('market', {})
        portfolio = context.get('portfolio', {})
        
        prompt = f"""You are a professional cryptocurrency trading analyst writing a blog post.

Based on the following data, write an engaging and informative blog post about current market conditions:

SENTIMENT ANALYSIS:
- Overall sentiment: {sentiment.get('sentiment_label', 'neutral')} ({sentiment.get('sentiment_score', 0)})
- Key topics: {', '.join(sentiment.get('key_topics', []))}
- Sources analyzed: {sentiment.get('source_count', 0)}

MARKET DATA:
- Bitcoin (BTC): ${market.get('BTC', {}).get('price', 0):,.2f} ({market.get('BTC', {}).get('change_24h', 0):+.2f}% 24h)
- Ethereum (ETH): ${market.get('ETH', {}).get('price', 0):,.2f} ({market.get('ETH', {}).get('change_24h', 0):+.2f}% 24h)

PORTFOLIO ACTIVITY:
- Recent trades: {len(portfolio.get('recent_trades', []))}
- Portfolio value: ${portfolio.get('portfolio_value', 0):,.2f}
- 24h P&L: ${portfolio.get('total_pnl_24h', 0):+,.2f}

Write a blog post with:
1. A catchy title
2. An introduction summarizing the current market state
3. Analysis of key trends and movements
4. Brief mention of portfolio performance
5. A conclusion with outlook

Keep it professional, informative, and around 300-400 words."""
        
        return prompt
    
    def _call_llm(self, prompt: str) -> str:
        """
        Call the LLM API to generate content.
        
        Args:
            prompt: The prompt to send to the LLM.
            
        Returns:
            Generated content string.
        """
        if self.use_mock:
            return self._generate_mock_content()
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a professional cryptocurrency trading analyst and blogger."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=800
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            print("Falling back to mock content.")
            return self._generate_mock_content()
    
    def _generate_mock_content(self) -> str:
        """
        Generate mock blog content when LLM is not available.
        
        Returns:
            Mock blog content string.
        """
        return """Title: Market Rally Continues as Bitcoin Breaks Key Resistance

The cryptocurrency market is showing strong bullish momentum today, with Bitcoin leading the charge above the $45,000 mark. This represents a significant 2.5% gain over the past 24 hours, signaling renewed investor confidence in the digital asset space.

Bitcoin's recent performance can be attributed to several factors, including improved market sentiment and positive developments in the broader crypto ecosystem. The Ethereum upgrade has also contributed to the positive atmosphere, though ETH itself has seen a slight pullback of 1.2% in the last day.

Our trading portfolio has been actively positioned to capture this momentum, with strategic BTC acquisitions near the $44,800 level. The portfolio currently shows a healthy 24-hour profit of $1,250, reflecting the effectiveness of our trend-following approach.

Market sentiment analysis indicates a bullish outlook, with over 150 sources showing positive sentiment. Key topics dominating the discussion include Bitcoin's rally, the Ethereum upgrade, and broader market recovery narratives.

Looking ahead, we anticipate continued volatility but remain optimistic about the medium-term trajectory. Traders should watch for potential resistance at the $46,000 level for Bitcoin, while support appears solid around $43,500."""
    
    def _parse_generated_content(self, content: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the generated content and extract structured data.
        
        Args:
            content: Raw content from LLM.
            context: Original context data.
            
        Returns:
            Structured blog post dictionary.
        """
        # Extract title if present
        lines = content.strip().split('\n')
        title = "Crypto Market Analysis"
        post_content = content
        
        # Check if first line looks like a title
        if lines and (lines[0].startswith('Title:') or lines[0].startswith('#')):
            title = lines[0].replace('Title:', '').replace('#', '').strip()
            post_content = '\n'.join(lines[1:]).strip()
        
        # Extract tags from context
        tags = ['crypto', 'trading', 'analysis']
        sentiment = context.get('sentiment', {})
        if sentiment.get('key_topics'):
            tags.extend([topic.lower().replace(' ', '-') for topic in sentiment.get('key_topics', [])[:3]])
        
        return {
            'title': title,
            'content': post_content,
            'timestamp': datetime.now().isoformat(),
            'tags': list(set(tags)),  # Remove duplicates
            'sentiment_label': sentiment.get('sentiment_label', 'neutral'),
            'context_summary': {
                'btc_price': context.get('market', {}).get('BTC', {}).get('price'),
                'eth_price': context.get('market', {}).get('ETH', {}).get('price'),
                'sentiment_score': sentiment.get('sentiment_score')
            }
        }
    
    def generate_post(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a complete blog post from context data.
        
        Args:
            context: Aggregated context data from ContextAggregator.
            
        Returns:
            Structured blog post dictionary with:
            - title: Post title
            - content: Post content
            - timestamp: Creation timestamp
            - tags: List of relevant tags
            - sentiment_label: Market sentiment
            - context_summary: Key metrics snapshot
        """
        prompt = self._construct_prompt(context)
        raw_content = self._call_llm(prompt)
        post = self._parse_generated_content(raw_content, context)
        
        return post
