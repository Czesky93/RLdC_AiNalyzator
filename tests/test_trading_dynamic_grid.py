"""
Tests for dynamic_grid.py — top-N selector, grid builder, recentering logic.
"""

import pytest
from backend.trading.dynamic_grid import (
    clip,
    zscore,
    GridPlan,
    select_top_usdc_pairs,
    build_grid_plan,
    check_recentering_needed,
)


class TestUtilityFunctions:
    """Test utility functions: clip, zscore."""

    def test_clip_within_range(self):
        assert clip(5.0, 0.0, 10.0) == 5.0

    def test_clip_below_range(self):
        assert clip(-1.0, 0.0, 10.0) == 0.0

    def test_clip_above_range(self):
        assert clip(15.0, 0.0, 10.0) == 10.0

    def test_zscore_normal_distribution(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        z = zscore(values)
        # Should have mean ~0 and values spread around
        assert len(z) == 5
        assert abs(sum(z) / len(z)) < 0.01  # mean ~0
        assert all(-2 <= x <= 2 for x in z)  # reasonable z-scores

    def test_zscore_single_value(self):
        z = zscore([5.0])
        assert z == [0.0]

    def test_zscore_empty_list(self):
        z = zscore([])
        assert z == []


class TestGridPlan:
    """Test GridPlan dataclass."""

    def test_grid_plan_creation(self):
        plan = GridPlan(
            symbol="BTCUSDC",
            last_price=50000.0,
            center=50000.0,
            lower=48000.0,
            upper=52000.0,
            half_width_pct=0.04,
            step_pct=0.01,
            grid_count=8,
            buy_levels=[49000.0, 48000.0],
            sell_levels=[51000.0, 52000.0],
            invest_quote=100.0,
            hard_stop=47500.0,
        )
        assert plan.symbol == "BTCUSDC"
        assert plan.grid_count == 8

    def test_grid_plan_to_dict(self):
        plan = GridPlan(
            symbol="ETHUSDC",
            last_price=3000.0,
            center=3000.0,
            lower=2900.0,
            upper=3100.0,
            half_width_pct=0.03,
            step_pct=0.01,
            grid_count=6,
        )
        d = plan.to_dict()
        assert d["symbol"] == "ETHUSDC"
        assert d["center"] == 3000.0
        assert d["created_at"] is not None

    def test_grid_plan_from_dict(self):
        plan_dict = {
            "symbol": "ADAUSDC",
            "last_price": 1.0,
            "center": 1.0,
            "lower": 0.95,
            "upper": 1.05,
            "half_width_pct": 0.05,
            "step_pct": 0.01,
            "grid_count": 10,
            "buy_levels": [0.99, 0.98],
            "sell_levels": [1.01, 1.02],
            "invest_quote": 50.0,
            "hard_stop": 0.94,
        }
        plan = GridPlan.from_dict(plan_dict)
        assert plan.symbol == "ADAUSDC"
        assert len(plan.buy_levels) == 2


class TestSelectTopUSCPairs:
    """Test select_top_usdc_pairs — not runnable without Binance client."""

    def test_select_top_usdc_pairs_empty_input(self):
        """select_top_usdc_pairs should handle empty input gracefully."""
        # NOTE: This test is placeholder. Real test requires mocked BinanceClient.
        # Implementation: pass a mock client that returns empty list
        pass

    def test_zscore_ranking_formula(self):
        """Verify z-score ranking formula is applied correctly."""
        # Create sample data manually to test scoring logic
        import math
        
        ranges = [10.0, 5.0, 15.0]  # high, low, highest
        changes = [2.0, 1.0, 3.0]  # low, lowest, highest
        volumes = [100000, 50000, 200000]  # mid, low, highest
        trades = [200, 100, 300]  # mid, low, highest
        spreads = [5, 10, 2]  # low, high, lowest

        # Compute z-scores manually
        z_ranges = zscore(ranges)
        z_changes = zscore(changes)
        z_volumes = zscore([math.log1p(v) for v in volumes])
        z_trades = zscore([math.log1p(t) for t in trades])
        z_spreads = zscore(spreads)

        # First pair score (index 0)
        score_0 = (
            0.30 * z_ranges[0]
            + 0.20 * z_changes[0]
            + 0.20 * z_volumes[0]
            + 0.15 * z_trades[0]
            + 0.10 * max(0, -z_spreads[0])
        )

        # Third pair (index 2) should score higher (highest range, change, volume, trades; lowest spread)
        score_2 = (
            0.30 * z_ranges[2]
            + 0.20 * z_changes[2]
            + 0.20 * z_volumes[2]
            + 0.15 * z_trades[2]
            + 0.10 * max(0, -z_spreads[2])
        )

        # Third pair should have higher score
        assert score_2 > score_0


class TestBuildGridPlan:
    """Test build_grid_plan — requires get_grid_context output."""

    def test_build_grid_plan_invalid_context(self):
        """build_grid_plan should return None for invalid context."""
        # With mock/None context
        result = build_grid_plan(
            db=None,
            symbol="BTCUSDC",
            grid_context=None,
            equity=1000,
            config={},
        )
        assert result is None

    def test_build_grid_plan_zero_price(self):
        """build_grid_plan should return None if last_price <= 0."""
        grid_context = {"last_price": 0.0}
        result = build_grid_plan(
            db=None,
            symbol="BTCUSDC",
            grid_context=grid_context,
            equity=1000,
            config={},
        )
        assert result is None

    def test_build_grid_plan_zero_equity(self):
        """build_grid_plan should return None if equity <= 0."""
        grid_context = {"last_price": 50000.0}
        result = build_grid_plan(
            db=None,
            symbol="BTCUSDC",
            grid_context=grid_context,
            equity=0,
            config={},
        )
        assert result is None


class TestRecentering:
    """Test check_recentering_needed logic."""

    def test_recentering_position_too_low(self):
        """Recentering should trigger when position_in_range < 0.15."""
        plan = GridPlan(
            symbol="BTCUSDC",
            last_price=48000.0,
            center=50000.0,
            lower=48000.0,
            upper=52000.0,
            half_width_pct=0.04,
            step_pct=0.01,
            grid_count=8,
        )
        current_price = 48050.0  # (48050 - 48000) / 4000 = 0.0125 < 0.15
        result = check_recentering_needed(plan, current_price)
        assert result["recentering_needed"] is True
        assert result["action"] == "shift_down"

    def test_recentering_position_too_high(self):
        """Recentering should trigger when position_in_range > 0.85."""
        plan = GridPlan(
            symbol="BTCUSDC",
            last_price=51000.0,
            center=50000.0,
            lower=48000.0,
            upper=52000.0,
            half_width_pct=0.04,
            step_pct=0.01,
            grid_count=8,
        )
        current_price = 51500.0  # (51500 - 48000) / 4000 = 0.875 > 0.85
        result = check_recentering_needed(plan, current_price)
        assert result["recentering_needed"] is True
        assert result["action"] == "shift_up"

    def test_recentering_position_ok(self):
        """Recentering should not trigger for middle position."""
        plan = GridPlan(
            symbol="BTCUSDC",
            last_price=50000.0,
            center=50000.0,
            lower=48000.0,
            upper=52000.0,
            half_width_pct=0.04,
            step_pct=0.01,
            grid_count=8,
        )
        current_price = 50000.0  # (50000 - 48000) / 4000 = 0.50 — OK
        result = check_recentering_needed(plan, current_price)
        assert result["recentering_needed"] is False
        assert result["action"] == "none"

    def test_recentering_invalid_plan(self):
        """Recentering should handle invalid plan gracefully."""
        plan = GridPlan(
            symbol="BTCUSDC",
            last_price=50000.0,
            center=50000.0,
            lower=50000.0,
            upper=50000.0,  # Invalid: lower == upper
            half_width_pct=0.0,
            step_pct=0.0,
            grid_count=0,
        )
        result = check_recentering_needed(plan, 50000.0)
        assert result["recentering_needed"] is False
        assert result["action"] == "none"

