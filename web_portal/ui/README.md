# AI Market Narrative - Web Portal

React-based web portal for visualizing AI-generated market narratives and blog posts.

## Features

- **BlogCard Component**: Material UI card displaying AI-generated posts with:
  - Title and publication date
  - Sentiment badge (Green for Bullish, Red for Bearish)
  - Content snippet
  - Dark mode styling

- **AI Blog Page**: Displays latest market narratives
  - Fetches data from FastAPI backend (`GET /blog/latest`)
  - Falls back to mock data if backend unavailable
  - Responsive Material UI design

- **Navigation**: Sidebar with links to Home and Narrative pages

## Setup

1. Install dependencies:
```bash
cd web_portal/ui
npm install
```

2. Start development server:
```bash
npm run dev
```

The application will run on `http://localhost:3000`

## API Integration

The app expects a FastAPI backend running on `http://localhost:8000` with the following endpoint:

- `GET /blog/latest` - Returns array of blog posts with:
  - `id`: Unique identifier
  - `title`: Post title
  - `content`: Full content
  - `sentiment`: "Bullish" or "Bearish"
  - `created_at`: ISO timestamp

If the backend is not available, the app will display mock data for demonstration.

## Build for Production

```bash
npm run build
```

The built files will be in the `dist/` directory.

## Technology Stack

- React 18
- Material UI 5
- React Router 6
- Axios
- Vite
