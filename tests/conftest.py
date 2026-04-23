"""
conftest.py — konfiguracja globalna pytest dla RLdC AiNalyzator.

Cel: Ustawienie DATABASE_URL PRZED importem jakiegokolwiek modułu backend,
tak aby backend.database tworzył engine na jednym, izolowanym pliku DB.

Bez tego każdy plik testowy ustawia DATABASE_URL w module-level code, ale
engine jest tworzony tylko raz (przy pierwszym imporcie backend.database).
Pierwszy plik który importuje backend wygrywa — reszta korzysta z jego DB.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Upewnij się, że root projektu jest w sys.path
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Ustaw DATABASE_URL PRZED pierwszym importem backend.database
# (conftest.py jest przetwarzany przez pytest przed zebraniem testów)
# ZAWSZE tworzymy nową izolowaną bazę testową — ignorujemy prod DATABASE_URL z env.
_shared_db = tempfile.NamedTemporaryFile(
    prefix="rldc_pytest_shared_", suffix=".db", delete=False
)
_shared_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_shared_db.name}"

# Podstawowe env dla testów — wymuszamy nadpisanie wartości z env shell
os.environ["DISABLE_COLLECTOR"] = "true"
os.environ["ADMIN_TOKEN"] = ""
os.environ.setdefault("DEMO_INITIAL_BALANCE", "10000")
os.environ["TRADING_MODE"] = "demo"
os.environ["ALLOW_LIVE_TRADING"] = "false"
