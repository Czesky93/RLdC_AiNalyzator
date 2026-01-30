"""
System Controls module for managing platform state.
Provides a singleton to track trading and AI system states.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SystemState:
    """
    Singleton class to manage system state (trading status, AI status).
    Persists state to a file so it survives restarts.
    """
    _instance = None
    _state_file = Path(__file__).parent.parent / "system_state.json"
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SystemState, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize state from file or create default state."""
        self._state = {
            "trading_paused": False,
            "ai_status": "running"
        }
        self._load_state()
    
    def _load_state(self):
        """Load state from file if it exists."""
        if self._state_file.exists():
            try:
                with open(self._state_file, 'r') as f:
                    self._state.update(json.load(f))
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse state file: {e}. Using default state.")
            except IOError as e:
                logger.error(f"Failed to read state file: {e}. Using default state.")
    
    def _save_state(self):
        """Save current state to file."""
        try:
            with open(self._state_file, 'w') as f:
                json.dump(self._state, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save state to file: {e}")
    
    @property
    def is_trading_paused(self):
        """Check if trading is paused."""
        return self._state.get("trading_paused", False)
    
    def pause_trading(self):
        """Pause trading operations."""
        self._state["trading_paused"] = True
        self._save_state()
    
    def resume_trading(self):
        """Resume trading operations."""
        self._state["trading_paused"] = False
        self._save_state()
    
    def restart_ai(self):
        """
        Restart AI system.
        
        TODO: This is a placeholder - actual implementation would restart AI processes.
        In a real system, this would signal AI components to restart via IPC or similar.
        """
        self._state["ai_status"] = "restarting"
        self._save_state()
        # Simulate restart completion
        self._state["ai_status"] = "running"
        self._save_state()
    
    def get_status(self):
        """Get current system status."""
        return {
            "trading": "paused" if self.is_trading_paused else "active",
            "ai": self._state.get("ai_status", "running")
        }


# Initialize singleton instance
system_state = SystemState()
