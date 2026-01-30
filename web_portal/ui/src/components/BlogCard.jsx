import React from 'react';
import {
  Card,
  CardContent,
  Typography,
  Chip,
  Box,
} from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';

function BlogCard({ post }) {
  const isBullish = post.sentiment === 'Bullish';
  
  // Format date
  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Get content snippet (first 200 characters)
  const getSnippet = (content) => {
    if (!content) return '';
    return content.length > 200 ? content.substring(0, 200) + '...' : content;
  };

  return (
    <Card
      sx={{
        mb: 2,
        backgroundColor: 'background.paper',
        '&:hover': {
          boxShadow: 6,
        },
      }}
    >
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
          <Typography variant="h5" component="div" sx={{ flex: 1 }}>
            {post.title}
          </Typography>
          <Chip
            icon={isBullish ? <TrendingUpIcon /> : <TrendingDownIcon />}
            label={post.sentiment}
            color={isBullish ? 'success' : 'error'}
            sx={{ ml: 2 }}
          />
        </Box>
        
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {formatDate(post.created_at)}
        </Typography>
        
        <Typography variant="body1" color="text.primary">
          {getSnippet(post.content)}
        </Typography>
      </CardContent>
    </Card>
  );
}

export default BlogCard;
