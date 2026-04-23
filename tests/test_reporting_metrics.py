from backend.reporting import (
    _compute_gross_to_net_retention,
    _compute_overtrading_score,
)


def test_overtrading_score_zero_when_no_activity_blocks():
    assert _compute_overtrading_score(0, 10) == 0.0


def test_overtrading_score_scales_with_activity_blocks():
    # 2 blokady na 10 zamkniętych transakcji = 0.2
    assert _compute_overtrading_score(2, 10) == 0.2


def test_overtrading_score_is_capped_to_one():
    assert _compute_overtrading_score(20, 5) == 1.0


def test_gross_to_net_retention_for_positive_pnl():
    # 80 netto z 100 brutto => retencja 0.8
    assert _compute_gross_to_net_retention(100.0, 80.0) == 0.8


def test_gross_to_net_retention_clamped_to_zero_one():
    assert _compute_gross_to_net_retention(100.0, -10.0) == 0.0
    assert _compute_gross_to_net_retention(100.0, 120.0) == 1.0


def test_gross_to_net_retention_zero_for_non_positive_gross():
    assert _compute_gross_to_net_retention(0.0, 0.0) == 0.0
    assert _compute_gross_to_net_retention(-5.0, -6.0) == 0.0
