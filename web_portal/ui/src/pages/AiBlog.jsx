import React, { useState, useEffect } from 'react';
import {
  Container,
  Typography,
  Box,
  CircularProgress,
  Alert,
} from '@mui/material';
import axios from 'axios';
import BlogCard from '../components/BlogCard';

function AiBlog() {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchPosts = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // Try to fetch from backend API
        // If backend is not available, use mock data
        try {
          const response = await axios.get('/blog/latest');
          setPosts(response.data);
        } catch (apiError) {
          console.warn('Backend API not available, using mock data:', apiError.message);
          
          // Mock data for demonstration
          const mockPosts = [
            {
              id: 1,
              title: 'Strong Bullish Momentum in Tech Sector',
              content: 'The technology sector is showing remarkable strength today, with major indices pushing to new highs. Investor sentiment remains overwhelmingly positive as earnings reports continue to exceed expectations. The AI revolution is driving unprecedented growth across multiple verticals, from cloud computing to semiconductor manufacturing.',
              sentiment: 'Bullish',
              created_at: new Date().toISOString(),
            },
            {
              id: 2,
              title: 'Market Correction Signals Growing Concerns',
              content: 'Recent market volatility suggests investors are becoming increasingly cautious about current valuations. Rising interest rates and inflation concerns are putting pressure on growth stocks. Technical indicators are showing overbought conditions across major indices, potentially signaling a near-term pullback.',
              sentiment: 'Bearish',
              created_at: new Date(Date.now() - 3600000).toISOString(),
            },
            {
              id: 3,
              title: 'Energy Sector Sees Renewed Interest',
              content: 'Energy stocks are attracting significant capital flows as oil prices stabilize above key support levels. The sector is benefiting from improved fundamentals and attractive valuations relative to the broader market. Analysts are upgrading their price targets across major energy producers.',
              sentiment: 'Bullish',
              created_at: new Date(Date.now() - 7200000).toISOString(),
            },
          ];
          setPosts(mockPosts);
        }
      } catch (err) {
        console.error('Error fetching posts:', err);
        setError('Failed to load blog posts. Please try again later.');
      } finally {
        setLoading(false);
      }
    };

    fetchPosts();
  }, []);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Container maxWidth="md" sx={{ mt: 4 }}>
        <Alert severity="error">{error}</Alert>
      </Container>
    );
  }

  return (
    <Container maxWidth="md">
      <Box sx={{ my: 4 }}>
        <Typography variant="h3" component="h1" gutterBottom>
          AI Market Narrative
        </Typography>
        <Typography variant="subtitle1" color="text.secondary" paragraph>
          AI-generated insights on market sentiment and trends
        </Typography>
        
        <Box sx={{ mt: 3 }}>
          {posts.length === 0 ? (
            <Alert severity="info">No posts available yet.</Alert>
          ) : (
            posts.map((post) => (
              <BlogCard key={post.id} post={post} />
            ))
          )}
        </Box>
      </Box>
    </Container>
  );
}

export default AiBlog;
