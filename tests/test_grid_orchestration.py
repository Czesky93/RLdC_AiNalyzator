"""
Tests for grid orchestration (T-155).
"""
from unittest.mock import MagicMock


def test_orchestrate_entry_invalid_plan():
    """Test: orchestrate_grid_entries handles invalid plan gracefully."""
    from backend.trading.grid_orchestration import orchestrate_grid_entries

    db_mock = MagicMock()
    plan = {'symbol': 'BTC', 'buy_levels': [], 'invest_quote': 0}
    placed, reasons = orchestrate_grid_entries(
        db_mock, 'BTC', plan, 50000.0, 10000.0, 1000.0, {}, []
    )
    assert placed == 0
    assert len(reasons) > 0


def test_orchestrate_entry_above_levels():
    """Test: no orders when price above all buy levels."""
    from backend.trading.grid_orchestration import orchestrate_grid_entries

    db_mock = MagicMock()
    plan = {
        'symbol': 'BTC',
        'buy_levels': [40000.0, 45000.0],
        'invest_quote': 100.0,
    }
    placed, reasons = orchestrate_grid_entries(
        db_mock, 'BTC', plan, 60000.0, 10000.0, 1000.0, {}, []
    )
    assert placed == 0


def test_orchestrate_exit_no_position():
    """Test: orchestrate_grid_exits handles no position gracefully."""
    from backend.trading.grid_orchestration import orchestrate_grid_exits

    db_mock = MagicMock()
    plan = {'symbol': 'BTC', 'sell_levels': [55000.0], 'hard_stop': 40000.0}
    exit_triggered, reasons = orchestrate_grid_exits(
        db_mock, 'BTC', plan, 50000.0, None, {}
    )
    assert exit_triggered is False
    assert 'no_position' in reasons


def test_orchestrate_exit_hard_stop():
    """Test: hard stop triggers when price falls below threshold."""
    from backend.trading.grid_orchestration import orchestrate_grid_exits
    from types import SimpleNamespace

    db_mock = MagicMock()
    plan = {'symbol': 'BTC', 'sell_levels': [55000.0], 'hard_stop': 40000.0}
    position = SimpleNamespace(
        symbol='BTC', status='OPEN', planned_tp=None, planned_sl=None
    )
    exit_triggered, reasons = orchestrate_grid_exits(
        db_mock, 'BTC', plan, 39000.0, position, {}
    )
    assert exit_triggered is True
    assert any('hard_stop' in r for r in reasons)
