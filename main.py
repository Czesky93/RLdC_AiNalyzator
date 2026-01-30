"""
Unified entry point for the RLdC AI Analyzer system.

This module orchestrates all system components asynchronously:
- FastAPI web portal (Backend API)
- Trading bot kernel (Decision Engine)
- Optional Telegram bot (if available)

Usage:
    python main.py
"""
import asyncio
import logging
import signal
import sys
from typing import Optional

import uvicorn
from uvicorn import Config, Server

# Import application components
from web_portal.api.main import app
from decision_engine.core import BotKernel


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class ApplicationOrchestrator:
    """Orchestrates all application components with graceful shutdown."""
    
    def __init__(self):
        """Initialize the orchestrator."""
        self.shutdown_event = asyncio.Event()
        self.bot_kernel: Optional[BotKernel] = None
        self.api_server: Optional[Server] = None
    
    async def start_api(self):
        """
        Start the FastAPI application using uvicorn programmatically.
        
        This runs the web portal API server asynchronously.
        """
        logger.info("Starting FastAPI server...")
        
        config = Config(
            app=app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=True
        )
        
        self.api_server = Server(config)
        
        try:
            await self.api_server.serve()
        except Exception as e:
            logger.error("Error in API server: %s", e, exc_info=True)
            raise
    
    async def start_trading_bot(self):
        """
        Start the trading bot kernel.
        
        This initializes the BotKernel and runs it asynchronously.
        The BotKernel orchestrates the trading decision logic.
        """
        logger.info("Starting trading bot kernel...")
        
        # Initialize the bot kernel with default settings
        self.bot_kernel = BotKernel(poll_interval=60.0)
        
        try:
            await self.bot_kernel.run()
        except Exception as e:
            logger.error("Error in trading bot: %s", e, exc_info=True)
            raise
    
    async def start_telegram_bot(self):
        """
        Start the Telegram bot (if available).
        
        This is a placeholder for future Telegram bot integration.
        """
        logger.info("Telegram bot integration not yet implemented")
        # Wait for shutdown signal
        await self.shutdown_event.wait()
    
    def setup_signal_handlers(self):
        """
        Setup signal handlers for graceful shutdown.
        
        Handles Ctrl+C (SIGINT) and SIGTERM to trigger graceful shutdown.
        """
        def signal_handler(sig, frame):
            logger.info("Received shutdown signal (%s). Initiating graceful shutdown...", sig)
            self.trigger_shutdown()
        
        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def trigger_shutdown(self):
        """Trigger graceful shutdown of all components."""
        logger.info("Triggering shutdown...")
        
        # Stop the bot kernel if it exists
        if self.bot_kernel:
            self.bot_kernel.stop()
        
        # Stop the API server if it exists
        if self.api_server:
            self.api_server.should_exit = True
        
        # Signal other components to shutdown
        self.shutdown_event.set()
    
    async def main(self):
        """
        Main orchestration function.
        
        Uses asyncio.gather() to run all components concurrently.
        Handles graceful shutdown on Ctrl+C or SIGTERM.
        """
        logger.info("=== RLdC AI Analyzer Starting ===")
        logger.info("Components: FastAPI Backend + Trading Bot + Notifications")
        
        # Setup signal handlers for graceful shutdown
        self.setup_signal_handlers()
        
        try:
            # Run all components concurrently using asyncio.gather
            # If any component fails, gather will raise an exception
            await asyncio.gather(
                self.start_api(),
                self.start_trading_bot(),
                # Uncomment when Telegram bot is implemented:
                # self.start_telegram_bot(),
                return_exceptions=False
            )
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt")
        except Exception as e:
            logger.error("Fatal error in main orchestration: %s", e, exc_info=True)
        finally:
            logger.info("=== RLdC AI Analyzer Shutdown Complete ===")


def run():
    """Entry point function to run the application."""
    orchestrator = ApplicationOrchestrator()
    
    try:
        asyncio.run(orchestrator.main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error("Application failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
