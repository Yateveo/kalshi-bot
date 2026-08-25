import pytest

import risk_guard


def test_kelly_fraction_scales_with_confidence():
    # f* = 2p - 1 for an even-money bet
    assert risk_guard.kelly_fraction(confidence=0.7, cap_pct=100.0) == pytest.approx(0.4)


def test_kelly_fraction_floors_at_zero_below_50_percent_confidence():
    assert risk_guard.kelly_fraction(confidence=0.4, cap_pct=100.0) == 0.0


def test_kelly_fraction_respects_cap():
    assert risk_guard.kelly_fraction(confidence=0.99, cap_pct=6.0) == pytest.approx(0.06)


def test_kelly_fraction_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        risk_guard.kelly_fraction(confidence=1.5, cap_pct=6.0)


def test_kelly_fraction_rejects_zero_cap_pct():
    with pytest.raises(ValueError):
        risk_guard.kelly_fraction(confidence=0.8, cap_pct=0.0)


def test_kelly_fraction_rejects_negative_cap_pct():
    with pytest.raises(ValueError):
        risk_guard.kelly_fraction(confidence=0.8, cap_pct=-6.0)


def test_kelly_fraction_rejects_cap_pct_above_100():
    with pytest.raises(ValueError):
        risk_guard.kelly_fraction(confidence=0.8, cap_pct=101.0)


def test_size_position_before_floor_reached_uses_full_kelly_size():
    result = risk_guard.size_position(
        equity_usd=50.0, confidence=0.8, kelly_cap_pct=6.0,
        floor_usd=50.0, floor_reached=False,
    )
    assert result.size_usd == pytest.approx(3.0)  # 50 * 0.06
    assert result.blocked_reason is None


def test_size_position_after_floor_reached_caps_at_headroom():
    # equity is only $2 above the floor; even a full Kelly-cap size ($3.12)
    # must be trimmed down to the $2 of headroom above the floor.
    result = risk_guard.size_position(
        equity_usd=52.0, confidence=0.8, kelly_cap_pct=6.0,
        floor_usd=50.0, floor_reached=True,
    )
    assert result.size_usd == pytest.approx(2.0)
    assert result.blocked_reason is None


def test_size_position_at_floor_blocks_new_risk():
    result = risk_guard.size_position(
        equity_usd=50.0, confidence=0.8, kelly_cap_pct=6.0,
        floor_usd=50.0, floor_reached=True,
    )
    assert result.size_usd == 0.0
    assert result.blocked_reason == "at_or_below_floor"


def test_size_position_zero_confidence_edge_blocks():
    result = risk_guard.size_position(
        equity_usd=50.0, confidence=0.5, kelly_cap_pct=6.0,
        floor_usd=50.0, floor_reached=False,
    )
    assert result.size_usd == 0.0
    assert result.blocked_reason == "zero_size"


def test_apply_ceiling_below_ceiling_is_a_no_op():
    equity, reserved = risk_guard.apply_ceiling(
        equity_usd=70.0, reserved_usd=0.0, ceiling_usd=75.0, floor_usd=50.0,
    )
    assert equity == 70.0
    assert reserved == 0.0


def test_apply_ceiling_at_or_above_ceiling_sweeps_profit_above_floor():
    equity, reserved = risk_guard.apply_ceiling(
        equity_usd=80.0, reserved_usd=0.0, ceiling_usd=75.0, floor_usd=50.0,
    )
    assert equity == 50.0
    assert reserved == 30.0


def test_apply_ceiling_accumulates_reserved_across_calls():
    equity, reserved = risk_guard.apply_ceiling(
        equity_usd=76.0, reserved_usd=30.0, ceiling_usd=75.0, floor_usd=50.0,
    )
    assert equity == 50.0
    assert reserved == 56.0


def test_apply_ceiling_misconfigured_floor_above_ceiling_does_not_fabricate_money():
    # floor_usd > ceiling_usd is a misconfiguration; the sweep must never go
    # negative (which would inflate tradable equity above actual equity).
    equity, reserved = risk_guard.apply_ceiling(
        equity_usd=80.0, reserved_usd=0.0, ceiling_usd=75.0, floor_usd=100.0,
    )
    assert equity == 100.0
    assert reserved == 0.0


def test_should_stop_loss_triggers_past_threshold():
    assert risk_guard.should_stop_loss(entry_price=0.40, current_price=0.29, stop_loss_pct=25.0) is True


def test_should_stop_loss_does_not_trigger_within_threshold():
    assert risk_guard.should_stop_loss(entry_price=0.40, current_price=0.35, stop_loss_pct=25.0) is False


def test_should_stop_loss_rejects_nonpositive_entry_price():
    with pytest.raises(ValueError):
        risk_guard.should_stop_loss(entry_price=0.0, current_price=0.1, stop_loss_pct=25.0)


def test_should_reverse_exit_true_when_confidence_flips_sides():
    assert risk_guard.should_reverse_exit(original_confidence=0.8, new_confidence=0.3) is True


def test_should_reverse_exit_false_when_confidence_stays_on_same_side():
    assert risk_guard.should_reverse_exit(original_confidence=0.8, new_confidence=0.6) is False
