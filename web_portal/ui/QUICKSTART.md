# Quick Start Guide

## Prerequisites
- Node.js 16 or higher
- npm 7 or higher

## Installation & Running

1. Navigate to the UI directory:
```bash
cd web_portal/ui
```

2. Install dependencies:
```bash
npm install
```

3. Start the development server:
```bash
npm run dev
```

4. Open your browser and navigate to:
```
http://localhost:3000
```

## Available Pages

- **Home** (`/`): Welcome page
- **AI Blog** (`/blog`): AI Market Narrative blog posts

## API Configuration

The application expects a FastAPI backend on `http://localhost:8000` with the endpoint:
- `GET /blog/latest` - Returns array of blog posts

### Expected Response Format:
```json
[
  {
    "id": 1,
    "title": "Post Title",
    "content": "Full post content...",
    "sentiment": "Bullish",
    "created_at": "2024-01-30T10:00:00Z"
  }
]
```

**Note:** If the backend is not running, the app will automatically display mock data for demonstration purposes.

## Building for Production

```bash
npm run build
```

The production-ready files will be in the `dist/` directory.

## Features

- ✨ Dark mode UI with Material Design
- 📱 Responsive layout
- 🔄 Real-time data fetching
- 💾 Automatic fallback to mock data
- 🎨 Sentiment-based color coding (Green=Bullish, Red=Bearish)
