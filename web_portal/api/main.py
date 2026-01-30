"""
FastAPI Main Application
Serves as the bridge between core Python modules and the Frontend.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .endpoints import router

app = FastAPI(
    title="RLdC AI Analyzer API",
    description="Trading Dashboard API for AI-powered trading analysis",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API endpoints
app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "RLdC AI Analyzer API",
        "version": "1.0.0",
        "status": "online"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
