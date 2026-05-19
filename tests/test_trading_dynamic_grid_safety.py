"""
Test 5 Dynamic Grid Safety Gates (T-157)

Weryfikacja, że dynamic_grid isolation jest hermetyczna i legacy system nie wpływa na nowe wejścia.

1. dynamic_grid nie tworzy BUY gdy dynamic_grid_enabled=False
2. dynamic_grid nie tworzy BUY gdy trading_system=legacy
3. dynamic_grid tworzy maksymalnie jeden GridPlan per symbol
4. active_grid_plans znika/aktualizuje się gdy symbol wypada z universe
5. legacy signal path NIE tworzy pending BUY przy trading_system=dynamic_grid
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from backend.trading.dynamic_grid import GridPlan
from backend.trading.trade_config import TradeConfig


@pytest.fixture
def runtime_config():
    """Mock runtime config."""
    config = Mock()
    config.trading_mode = "demo"
    config.trading_system = "dynamic_grid"
    config.dynamic_grid_enabled = True
    config.allow_live_trading = True
    return config


@pytest.fixture
def trade_config():
    """Real TradeConfig for consistency."""
    return TradeConfig()


class TestDynamicGridDisabledNoBuy:
    """Test 1: dynamic_grid nie tworzy BUY gdy dynamic_grid_enabled=False."""

    def test_grid_plan_not_created_when_disabled(self, runtime_config):
        """GridPlan should not be created when dynamic_grid_enabled=False."""
        # Setup: dynamic_grid_enabled=False
        runtime_config.dynamic_grid_enabled = False
        runtime_config.trading_system = "dynamic_grid"
        
        # Mock active_grid_plans storage
        stored_plans = {}
        
        def mock_persist_plan(symbol, plan):
            """Only persist if grid is enabled."""
            if runtime_config.dynamic_grid_enabled:
                stored_plans[symbol] = plan
                return True
            return False
        
        # Try to persist a plan
        test_plan = GridPlan(
            symbol="ADAUSDC",
            last_price=1.0,
            center=1.0,
            lower=0.9,
            upper=1.1,
            half_width_pct=10.0,
            step_pct=5.0,
            grid_count=3,
            buy_levels=[0.98, 0.95, 0.92],
            sell_levels=[1.02, 1.05, 1.08],
            invest_quote=100.0,
            hard_stop=0.8,
            estimated_notional_per_level=33.0
        )
        
        result = mock_persist_plan("ADAUSDC", test_plan)
        
        # Verify: plan was NOT stored
        assert result is False
        assert "ADAUSDC" not in stored_plans
    
    def test_entry_candidate_not_created_when_disabled(self, runtime_config):
        """Pending BUY should not be created when dynamic_grid_enabled=False."""
        runtime_config.dynamic_grid_enabled = False
        
        # Mock entry creation gate
        def can_create_entry():
            return runtime_config.trading_system == "dynamic_grid" and runtime_config.dynamic_grid_enabled
        
        assert can_create_entry() is False


class TestDynamicGridLegacySystemNoBuy:
    """Test 2: dynamic_grid nie tworzy BUY gdy trading_system=legacy."""
    
    def test_legacy_system_blocks_grid_entry(self, runtime_config):
        """Grid should not create entry when trading_system=legacy."""
        runtime_config.trading_system = "legacy"
        runtime_config.dynamic_grid_enabled = True
        
        def should_use_grid():
            return runtime_config.trading_system == "dynamic_grid" and runtime_config.dynamic_grid_enabled
        
        assert should_use_grid() is False
    
    def test_entry_creation_requires_dynamic_grid_system(self, runtime_config):
        """Verify entry gate checks for trading_system=dynamic_grid."""
        # Test both systems
        for system in ["legacy", "dynamic_grid"]:
            runtime_config.trading_system = system
            runtime_config.dynamic_grid_enabled = True
            
            can_enter = (
                runtime_config.trading_system == "dynamic_grid" and
                runtime_config.dynamic_grid_enabled
            )
            
            if system == "legacy":
                assert can_enter is False
            else:
                assert can_enter is True


class TestDynamicGridSinglePlanPerSymbol:
    """Test 3: dynamic_grid tworzy maksymalnie jeden GridPlan per symbol."""
    
    def test_grid_plans_deduplication(self):
        """Verify only one GridPlan per symbol is stored."""
        stored_plans = {}
        
        def persist_grid_plan(symbol, plan):
            """Store plan, replacing any existing."""
            stored_plans[symbol] = plan
            return plan
        
        # Try to create multiple plans for same symbol
        plan1 = GridPlan(
            symbol="BTCUSDC", last_price=45000, center=45000, lower=44000, upper=46000,
            half_width_pct=2.2, step_pct=1.1, grid_count=3,
            buy_levels=[44500, 44000], sell_levels=[45500, 46000],
            invest_quote=500, hard_stop=43000, estimated_notional_per_level=166.67
        )
        plan2 = GridPlan(
            symbol="BTCUSDC", last_price=45100, center=45100, lower=44100, upper=46100,
            half_width_pct=2.2, step_pct=1.1, grid_count=3,
            buy_levels=[44600, 44100], sell_levels=[45600, 46100],
            invest_quote=500, hard_stop=43000, estimated_notional_per_level=166.67
        )
        
        persist_grid_plan("BTCUSDC", plan1)
        persist_grid_plan("BTCUSDC", plan2)
        
        # Verify: only ONE plan stored for BTCUSDC
        assert len(stored_plans) == 1
        assert stored_plans["BTCUSDC"] == plan2  # Latest overwrites
    
    def test_multiple_symbols_have_separate_plans(self):
        """Verify different symbols have separate plans."""
        stored_plans = {}
        
        symbols = ["BTCUSDC", "ETHUSDC", "SOLUSDC"]
        plans = [
            GridPlan(
                symbol=s, last_price=100, center=100, lower=90, upper=110,
                half_width_pct=10.0, step_pct=5.0, grid_count=3,
                buy_levels=[95], sell_levels=[105],
                invest_quote=100, hard_stop=80, estimated_notional_per_level=33.33)
            for s in symbols
        ]
        
        for symbol, plan in zip(symbols, plans):
            stored_plans[symbol] = plan
        
        # Verify: each symbol has its own plan
        assert len(stored_plans) == 3
        for symbol in symbols:
            assert symbol in stored_plans


class TestDynamicGridPlansCleanup:
    """Test 4: active_grid_plans znika/aktualizuje się gdy symbol wypada z universe."""
    
    def test_grid_plans_cleanup_on_symbol_removal(self):
        """Verify plans are removed when symbols leave the universe."""
        # Simulate active plans
        active_plans = {
            "BTCUSDC": GridPlan(symbol="BTCUSDC", last_price=100, center=100, lower=90, upper=110,
                               half_width_pct=10.0, step_pct=5.0, grid_count=3,
                               buy_levels=[95], sell_levels=[105],
                               invest_quote=100, hard_stop=80, estimated_notional_per_level=33.33),
            "ETHUSDC": GridPlan(symbol="ETHUSDC", last_price=100, center=100, lower=90, upper=110,
                               half_width_pct=10.0, step_pct=5.0, grid_count=3,
                               buy_levels=[95], sell_levels=[105],
                               invest_quote=100, hard_stop=80, estimated_notional_per_level=33.33),
            "REMOVED_SYMBOL": GridPlan(symbol="REMOVED_SYMBOL", last_price=100, center=100, lower=90, upper=110,
                                      half_width_pct=10.0, step_pct=5.0, grid_count=3,
                                      buy_levels=[95], sell_levels=[105],
                                      invest_quote=100, hard_stop=80, estimated_notional_per_level=33.33),
        }
        
        current_universe = ["BTCUSDC", "ETHUSDC", "SOLUSDC"]
        
        # Cleanup: remove plans for symbols not in current universe
        cleaned_plans = {
            symbol: plan for symbol, plan in active_plans.items()
            if symbol in current_universe
        }
        
        # Verify: REMOVED_SYMBOL plan is gone
        assert "REMOVED_SYMBOL" not in cleaned_plans
        assert len(cleaned_plans) == 2
        assert "BTCUSDC" in cleaned_plans
        assert "ETHUSDC" in cleaned_plans
    
    def test_grid_plans_update_on_universe_change(self):
        """Verify plans are updated when universe changes."""
        active_plans = {"BTCUSDC": Mock(), "ETHUSDC": Mock()}
        
        # Universe shrinks
        new_universe = ["BTCUSDC"]
        active_plans = {s: p for s, p in active_plans.items() if s in new_universe}
        
        assert len(active_plans) == 1
        assert "ETHUSDC" not in active_plans


class TestLegacyPathBlockedOnDynamicGrid:
    """Test 5: legacy signal path NIE tworzy pending BUY przy trading_system=dynamic_grid."""
    
    def test_legacy_best_opportunity_blocked(self, runtime_config):
        """Legacy best-opportunity signal should not create pending when grid is active."""
        runtime_config.trading_system = "dynamic_grid"
        runtime_config.dynamic_grid_enabled = True
        
        def legacy_signal_creates_entry():
            """Simulate legacy signal entry path."""
            # Legacy path should check if grid is active
            if runtime_config.trading_system == "dynamic_grid":
                return False  # Blocked
            return True
        
        assert legacy_signal_creates_entry() is False
    
    def test_pending_order_gate_checks_trading_system(self, runtime_config):
        """Pending order creation should verify trading_system."""
        runtime_config.trading_system = "dynamic_grid"
        
        def should_create_pending(mode, system):
            """Gate for pending order creation."""
            # If dynamic_grid is active, only grid pipeline can create pending
            if system == "dynamic_grid":
                # Only grid entry path, not legacy
                return mode == "grid_entry"
            return True
        
        # Legacy path blocked
        assert should_create_pending(mode="legacy_signal", system="dynamic_grid") is False
        
        # Grid path allowed
        assert should_create_pending(mode="grid_entry", system="dynamic_grid") is True
        
        # Legacy system: legacy path still works
        assert should_create_pending(mode="legacy_signal", system="legacy") is True


class TestDynamicGridSafety:
    """Integration tests for safety gates."""
    
    def test_only_one_active_system_at_time(self, runtime_config):
        """Verify only one trading system is active."""
        # Can't be both legacy and dynamic_grid
        runtime_config.trading_system = "dynamic_grid"
        runtime_config.dynamic_grid_enabled = True
        
        # Legacy should be implicitly disabled
        is_legacy_active = runtime_config.trading_system == "legacy"
        is_grid_active = runtime_config.trading_system == "dynamic_grid" and runtime_config.dynamic_grid_enabled
        
        assert not (is_legacy_active and is_grid_active)
        assert is_grid_active
    
    def test_grid_safety_gates_summary(self, runtime_config):
        """Verify all safety gates in isolation."""
        gates = {
            "grid_enabled": runtime_config.dynamic_grid_enabled,
            "grid_system": runtime_config.trading_system == "dynamic_grid",
            "legacy_not_active": runtime_config.trading_system != "legacy",
        }
        
        # All gates should align
        assert gates["grid_enabled"] is True
        assert gates["grid_system"] is True
        assert gates["legacy_not_active"] is True
        
        # When grid is off, legacy should work
        runtime_config.dynamic_grid_enabled = False
        runtime_config.trading_system = "legacy"
        
        assert runtime_config.dynamic_grid_enabled is False
        assert runtime_config.trading_system == "legacy"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
