"""
RLdC learning_hub — event-driven feedback loop (stub)
Odpowiada za odbiór eventów tradingowych, synchronizację reward, uczenie i ewaluację strategii.
"""
from typing import Any, Dict
from backend.system_logger import log_to_db

class LearningHub:
    """
    Szkielet event-driven feedback loop:
    - odbiór eventów (trade, reward, sync)
    - miejsce na logikę uczenia (RL, supervised, heurystyka)
    - miejsce na ewaluację strategii
    """
    def __init__(self):
        self.last_event = None
        self.last_reward = None
        self.memory = []  # historia eventów

    def on_event(self, event: Dict[str, Any]):
        """Odbiera event tradingowy (np. zamknięcie pozycji, reward, sync)."""
        self.last_event = event
        self.memory.append(event)
        log_to_db("INFO", "learning_hub", f"Odebrano event: {event}")
        # TODO: logika uczenia/reward/ewaluacji

    def on_reward(self, reward: float, meta: Dict[str, Any] = None):
        """Odbiera reward (zysk/strata, PnL, metryki)."""
        self.last_reward = reward
        log_to_db("INFO", "learning_hub", f"Reward: {reward}, meta: {meta}")
        # TODO: logika aktualizacji modelu/strategii

    def get_state(self) -> Dict[str, Any]:
        """Zwraca aktualny stan learning_hub (stub)."""
        return {
            "last_event": self.last_event,
            "last_reward": self.last_reward,
            "memory_len": len(self.memory),
        }

# Instancja singleton do integracji z backendem
learning_hub = LearningHub()
