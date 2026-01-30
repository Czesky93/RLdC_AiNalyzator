"""FastAPI application for the Web Portal."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="RLdC AI Analyzer API",
    description="Backend API for the RLdC Trading Bot",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "RLdC AI Analyzer API", "status": "online"}


@app.get("/status")
async def get_status():
    """Get system status."""
    return {
        "system": "operational",
        "components": {
            "api": "running",
            "trading_bot": "active"
        }
    }
