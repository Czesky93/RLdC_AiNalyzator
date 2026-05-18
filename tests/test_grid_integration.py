"""
Test integracyjny dla dynamic grid — weryfikacja flow: selector → builder → recentering → persistence
"""
import os
import sys
from datetime import datetime, timedelta

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base, RuntimeSetting, Kline, MarketData
from backend.trading.dynamic_grid import (
    build_grid_plan,
    GridPlan,
    load_grid_plan,
    persist_grid_plan,
    check_recentering_needed,
)
from backend.analysis import get_grid_context


class TestGridIntegration:
    """Testy integracyjne full grid pipeline"""

    @pytest.fixture
    def test_db(self):
        """Utwórz in-memory DB dla testów"""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        return Session()

    def test_build_and_persist_grid_plan(self, test_db):
        """Test: Zbuduj plan i utrwal w DB"""
        symbol = "BTCUSDC"
        
        # Mock grid context (symuluj dane z get_grid_context)
        grid_context = {
                "last_price": 42000.0,
            "15m": {
                "ema_20": 42000,
                "ema_50": 41500,
                "rsi_14": 55,
                "atr_14": 150,
                "adx_14": 28,
                "volume_ratio": 1.2,
                "trend": "up",
            },
            "1h": {
                "ema_20": 41800,
                "ema_50": 41200,
                "rsi_14": 58,
                "atr_14": 200,
                "adx_14": 35,
                "volume_ratio": 1.1,
                "vwap_24": 41600,
                "trend": "up",
            },
            "4h": {
                "ema_20": 41500,
                "ema_50": 40800,
                "rsi_14": 60,
                "atr_14": 300,
                "adx_14": 40,
                "volume_ratio": 1.0,
                "trend": "up",
            },
        }
        
        # Mock current price
        current_price = 42000.0
        equity = 10000.0
        config = {
            "dynamic_grid_invest_pct": 0.1,
            "dynamic_grid_hardstop_pad_pct": 0.03,
        }
        
        # Zbuduj plan
        plan = build_grid_plan(
            db=test_db,
            symbol=symbol,
            grid_context=grid_context,
            equity=equity,
            config=config,
        )
        
        # Weryfikuj plan
        assert plan is not None
        assert plan.symbol == symbol
        assert plan.center > 0
        assert plan.lower < plan.center < plan.upper
        assert len(plan.buy_levels) > 0
        assert len(plan.sell_levels) > 0
        assert plan.grid_count >= 3
        assert plan.grid_count <= 30
        assert plan.invest_quote > 0
        
        # Utrwal w DB
        persist_grid_plan(test_db, symbol, plan)
        
        # Załaduj z DB i weryfikuj
        loaded_plan = load_grid_plan(test_db, symbol)
        assert loaded_plan is not None
        assert loaded_plan.symbol == symbol
        assert loaded_plan.center == plan.center
        assert len(loaded_plan.buy_levels) == len(plan.buy_levels)
        assert len(loaded_plan.sell_levels) == len(plan.sell_levels)

    def test_recentering_detection(self, test_db):
        """Test: Detekcja potrzeby recentering"""
        grid_plan = GridPlan(
            symbol="ETHUSDC",
               last_price=2500.0,
            center=2500.0,
            lower=2300.0,
            upper=2700.0,
            half_width_pct=4.0,
            step_pct=1.5,
            grid_count=10,
            buy_levels=[2300.0, 2350.0, 2400.0, 2450.0, 2500.0],
            sell_levels=[2550.0, 2600.0, 2650.0, 2700.0],
            invest_quote=100.0,
            hard_stop=2200.0,
            reason_codes=[],
        )
        
        # Test 1: Cena za nisko (< 15% zakresu) → shift_up
        result = check_recentering_needed(grid_plan, current_price=2310.0, current_position=0)
        assert result["recentering_needed"] is True
        assert result["action"] == "shift_down"
        
        # Test 2: Cena za wysoko (> 85% zakresu) → shift_down
        result = check_recentering_needed(grid_plan, current_price=2680.0, current_position=0)
        assert result["recentering_needed"] is True
        assert result["action"] == "shift_up"
        
        # Test 3: Cena OK (15-85% zakresu) → no_action
        result = check_recentering_needed(grid_plan, current_price=2500.0, current_position=0)
        assert result["recentering_needed"] is False
        assert result["action"] == "none"

    def test_grid_plan_persistence_lifecycle(self, test_db):
        """Test: Full lifecycle — create → persist → load → update → verify"""
        symbol = "ADAUSDC"
        
        # Plan 1
        plan1 = GridPlan(
            symbol=symbol,
            last_price=1.0,
            center=1.0,
            lower=0.9,
            upper=1.1,
            half_width_pct=10.0,
            step_pct=2.0,
            grid_count=5,
            buy_levels=[0.90, 0.95, 1.00],
            sell_levels=[1.05, 1.10],
            invest_quote=50.0,
            hard_stop=0.85,
            reason_codes=["initial_build"],
        )
        
        persist_grid_plan(test_db, symbol, plan1)
        loaded = load_grid_plan(test_db, symbol)
        assert loaded.center == 1.0
        assert loaded.invest_quote == 50.0
        
        # Plan 2 (update)
        plan2 = GridPlan(
            symbol=symbol,
            last_price=1.05,
            center=1.05,
            lower=0.95,
            upper=1.15,
            half_width_pct=10.0,
            step_pct=2.0,
            grid_count=5,
            buy_levels=[0.95, 1.00, 1.05],
            sell_levels=[1.10, 1.15],
            invest_quote=55.0,
            hard_stop=0.90,
            reason_codes=["recenter", "shift_up"],
        )
        
        persist_grid_plan(test_db, symbol, plan2)
        loaded = load_grid_plan(test_db, symbol)
        assert loaded.center == 1.05
        assert loaded.invest_quote == 55.0
        assert "shift_up" in loaded.reason_codes

    def test_multiple_grids_per_watchlist(self, test_db):
        """Test: Zarządzaj wieloma planami gridu dla różnych symboli"""
        symbols = ["BTCUSDC", "ETHUSDC", "ADAUSDC"]
        
        for i, symbol in enumerate(symbols):
            plan = GridPlan(
                symbol=symbol,
                last_price=1000.0 + i * 100,
                center=1000.0 + i * 100,
                lower=900.0 + i * 100,
                upper=1100.0 + i * 100,
                half_width_pct=10.0,
                step_pct=2.0,
                grid_count=5,
                buy_levels=[900.0 + i * 100, 950.0 + i * 100],
                sell_levels=[1050.0 + i * 100, 1100.0 + i * 100],
                invest_quote=100.0 + i * 10,
                hard_stop=800.0 + i * 100,
                reason_codes=[f"symbol_{i}"],
            )
            persist_grid_plan(test_db, symbol, plan)
        
        # Weryfikuj każdy plan
        for i, symbol in enumerate(symbols):
            loaded = load_grid_plan(test_db, symbol)
            assert loaded is not None
            assert loaded.symbol == symbol
            assert loaded.center == 1000.0 + i * 100
            assert f"symbol_{i}" in loaded.reason_codes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
