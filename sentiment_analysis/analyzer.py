"""
Sentiment Analysis Engine

Uses FinBERT model to analyze sentiment of financial/crypto news headlines.
"""

from transformers import pipeline
from typing import List, Dict, Tuple, Any
import warnings


class SentimentEngine:
    """
    Advanced NLP engine for sentiment analysis using FinBERT.
    
    Classifies text as Positive, Negative, or Neutral and provides
    confidence scores.
    """
    
    def __init__(self, model_name: str = "ProsusAI/finbert"):
        """
        Initialize the sentiment analysis engine.
        
        Args:
            model_name: HuggingFace model to use (default: ProsusAI/finbert)
        """
        print(f"Loading sentiment model: {model_name}...")
        
        try:
            # Suppress only transformers-specific warnings during model loading
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', category=FutureWarning, module='transformers')
                # Initialize the sentiment analysis pipeline
                self.classifier = pipeline(
                    "sentiment-analysis",
                    model=model_name,
                    tokenizer=model_name,
                    max_length=512,
                    truncation=True
                )
            print("Model loaded successfully!")
            
        except Exception as e:
            print(f"Error loading model: {str(e)}")
            raise
    
    def analyze_text(self, text: str) -> Dict[str, Any]:
        """
        Analyze sentiment of a single text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Dictionary with 'label' (positive/negative/neutral) and 'score' (confidence)
        """
        if not text or not text.strip():
            return {'label': 'neutral', 'score': 0.0}
            
        try:
            result = self.classifier(text)[0]
            return {
                'label': result['label'].lower(),
                'score': result['score']
            }
        except Exception as e:
            print(f"Error analyzing text: {str(e)}")
            return {'label': 'neutral', 'score': 0.0}
    
    def analyze_headlines(self, headlines: List[str]) -> Tuple[List[Dict], float]:
        """
        Analyze multiple headlines and calculate aggregate sentiment score.
        
        Args:
            headlines: List of headline strings to analyze
            
        Returns:
            Tuple of (list of individual results, aggregate market sentiment score)
            - Individual results: List of dicts with 'text', 'label', 'score'
            - Market sentiment: Float from -1.0 (very negative) to +1.0 (very positive)
        """
        if not headlines:
            return [], 0.0
            
        results = []
        sentiment_values = []
        
        print(f"\nAnalyzing {len(headlines)} headlines...")
        
        for i, headline in enumerate(headlines, 1):
            if not headline or not headline.strip():
                continue
                
            sentiment = self.analyze_text(headline)
            
            # Convert sentiment to numeric value
            label = sentiment['label']
            score = sentiment['score']
            
            if 'positive' in label:
                numeric_value = score
            elif 'negative' in label:
                numeric_value = -score
            else:  # neutral
                numeric_value = 0.0
            
            sentiment_values.append(numeric_value)
            
            results.append({
                'text': headline[:100] + '...' if len(headline) > 100 else headline,
                'label': label,
                'score': score,
                'numeric_value': numeric_value
            })
            
            # Print progress for long lists
            if i % 10 == 0:
                print(f"  Processed {i}/{len(headlines)} headlines...")
        
        # Calculate aggregate market sentiment
        if sentiment_values and len(sentiment_values) > 0:
            market_sentiment = sum(sentiment_values) / len(sentiment_values)
        else:
            market_sentiment = 0.0
            
        return results, market_sentiment
    
    @staticmethod
    def interpret_market_sentiment(market_sentiment: float) -> Tuple[str, str]:
        """
        Interpret market sentiment score into human-readable text.
        
        Args:
            market_sentiment: Score from -1.0 (very negative) to +1.0 (very positive)
            
        Returns:
            Tuple of (sentiment_text, interpretation)
        """
        if market_sentiment > 0.2:
            return "BULLISH 🚀", "Strong positive sentiment in crypto news"
        elif market_sentiment > 0.05:
            return "SLIGHTLY BULLISH 📈", "Moderately positive sentiment"
        elif market_sentiment < -0.2:
            return "BEARISH 📉", "Strong negative sentiment in crypto news"
        elif market_sentiment < -0.05:
            return "SLIGHTLY BEARISH 📊", "Moderately negative sentiment"
        else:
            return "NEUTRAL ➡️", "Mixed or neutral sentiment"
    
    @staticmethod
    def get_sentiment_emoji(label: str) -> str:
        """
        Get emoji representation for sentiment label.
        
        Args:
            label: Sentiment label (positive, negative, neutral)
            
        Returns:
            Emoji string
        """
        emoji_map = {
            'positive': '📈',
            'negative': '📉',
            'neutral': '➡️'
        }
        return emoji_map.get(label.lower(), '')
    
    def get_sentiment_summary(self, results: List[Dict]) -> Dict[str, int]:
        """
        Get summary statistics of sentiment analysis results.
        
        Args:
            results: List of sentiment analysis results
            
        Returns:
            Dictionary with counts of positive, negative, and neutral sentiments
        """
        summary = {
            'positive': 0,
            'negative': 0,
            'neutral': 0,
            'total': len(results)
        }
        
        for result in results:
            label = result['label']
            if 'positive' in label:
                summary['positive'] += 1
            elif 'negative' in label:
                summary['negative'] += 1
            else:
                summary['neutral'] += 1
                
        return summary
