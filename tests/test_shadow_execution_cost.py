"""Tests for the deterministic shadow L2 execution-cost model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from polysignal.shadow.execution_cost import (
    FillStatus,
    L2Level,
    simulate_buy_notional,
    simulate_round_trip,
    simulate_sell_shares,
)


def level(price: float, size: float) -> L2Level:
    return L2Level(price=price, size=size)


def test_buy_walks_asks_in_price_order_and_calculates_vwap() -> None:
    result = simulate_buy_notional(
        [level(0.60, 10), level(0.50, 10), level(0.55, 10)],
        8.0,
    )

    assert result.status is FillStatus.FULL
    assert [fill.price for fill in result.fills] == [0.50, 0.55]
    assert result.fills[0].shares == pytest.approx(10.0)
    assert result.fills[1].notional_usd == pytest.approx(3.0)
    assert result.filled_notional_usd == pytest.approx(8.0)
    assert result.filled_shares == pytest.approx(10.0 + 3.0 / 0.55)
    assert result.average_price == pytest.approx(8.0 / result.filled_shares)
    assert result.best_price == pytest.approx(0.50)
    assert result.worst_price == pytest.approx(0.55)
    assert result.adverse_impact_bps > 0
    assert result.completion_ratio == pytest.approx(1.0)


def test_sell_walks_bids_in_descending_order() -> None:
    result = simulate_sell_shares(
        [level(0.40, 4), level(0.48, 3), level(0.45, 5)],
        6.0,
    )

    assert result.status is FillStatus.FULL
    assert [fill.price for fill in result.fills] == [0.48, 0.45]
    assert [fill.shares for fill in result.fills] == pytest.approx([3.0, 3.0])
    assert result.filled_notional_usd == pytest.approx(2.79)
    assert result.average_price == pytest.approx(0.465)
    assert result.adverse_impact_bps == pytest.approx((0.48 - 0.465) / 0.48 * 10_000)


def test_duplicate_price_levels_are_aggregated() -> None:
    result = simulate_sell_shares(
        [level(0.50, 2), level(0.50, 3)],
        5.0,
    )

    assert result.status is FillStatus.FULL
    assert len(result.fills) == 1
    assert result.fills[0].shares == pytest.approx(5.0)


def test_full_fill_default_rejects_insufficient_visible_depth() -> None:
    result = simulate_buy_notional([level(0.50, 1)], 1.0)

    assert result.status is FillStatus.REJECTED
    assert result.reject_reason == "insufficient_visible_depth"
    assert result.available_notional_usd == pytest.approx(0.50)
    assert result.available_shares == pytest.approx(1.0)
    assert result.filled_notional_usd == 0.0
    assert result.filled_shares == 0.0
    assert result.fills == ()


def test_partial_fill_must_be_explicitly_enabled() -> None:
    result = simulate_buy_notional(
        [level(0.50, 1)],
        1.0,
        allow_partial=True,
    )

    assert result.status is FillStatus.PARTIAL
    assert result.filled_notional_usd == pytest.approx(0.50)
    assert result.filled_shares == pytest.approx(1.0)
    assert result.completion_ratio == pytest.approx(0.50)


def test_buy_limit_excludes_more_expensive_asks() -> None:
    rejected = simulate_buy_notional(
        [level(0.50, 1), level(0.51, 10)],
        1.0,
        limit_price=0.50,
    )
    filled = simulate_buy_notional(
        [level(0.50, 1), level(0.51, 10)],
        1.0,
        limit_price=0.51,
    )

    assert rejected.status is FillStatus.REJECTED
    assert rejected.available_notional_usd == pytest.approx(0.50)
    assert filled.status is FillStatus.FULL
    assert filled.worst_price == pytest.approx(0.51)


def test_sell_limit_excludes_lower_bids() -> None:
    result = simulate_sell_shares(
        [level(0.50, 1), level(0.49, 10)],
        2.0,
        limit_price=0.50,
    )

    assert result.status is FillStatus.REJECTED
    assert result.available_shares == pytest.approx(1.0)


def test_flat_fee_is_explicit_and_applied_to_cash_flow() -> None:
    buy = simulate_buy_notional([level(0.50, 10)], 5.0, fee_bps=100)
    sell = simulate_sell_shares([level(0.50, 10)], 10.0, fee_bps=100)

    assert buy.fee_usd == pytest.approx(0.05)
    assert buy.net_cash_flow_usd == pytest.approx(-5.05)
    assert sell.fee_usd == pytest.approx(0.05)
    assert sell.net_cash_flow_usd == pytest.approx(4.95)


def test_round_trip_exits_exact_entry_shares_and_reports_costed_pnl() -> None:
    result = simulate_round_trip(
        entry_asks=[level(0.50, 10), level(0.60, 10)],
        exit_bids=[level(0.55, 20)],
        entry_notional_usd=8.0,
        entry_fee_bps=100,
        exit_fee_bps=100,
    )

    assert result.status is FillStatus.FULL
    assert result.exit is not None
    assert result.exit.requested_shares == pytest.approx(result.entry.filled_shares)
    assert result.gross_pnl_usd == pytest.approx(
        result.exit.filled_notional_usd - result.entry.filled_notional_usd
    )
    assert result.total_fees_usd == pytest.approx(
        result.entry.fee_usd + result.exit.fee_usd
    )
    assert result.net_pnl_usd == pytest.approx(result.gross_pnl_usd - result.total_fees_usd)


def test_round_trip_rejects_when_exit_cannot_absorb_entry_shares() -> None:
    result = simulate_round_trip(
        entry_asks=[level(0.50, 10)],
        exit_bids=[level(0.49, 9)],
        entry_notional_usd=5.0,
    )

    assert result.status is FillStatus.REJECTED
    assert result.entry.status is FillStatus.FULL
    assert result.exit is not None
    assert result.exit.status is FillStatus.REJECTED
    assert result.reject_reason == "exit_insufficient_visible_depth"
    assert result.net_pnl_usd is None


@pytest.mark.parametrize(
    ("function", "value"),
    [
        (simulate_buy_notional, 0.0),
        (simulate_buy_notional, float("nan")),
        (simulate_sell_shares, -1.0),
        (simulate_sell_shares, float("inf")),
    ],
)
def test_non_positive_or_non_finite_requests_are_rejected(function, value: float) -> None:
    with pytest.raises(ValueError):
        function([level(0.50, 10)], value)


@pytest.mark.parametrize("fee_bps", [-1.0, 10_001.0, float("nan")])
def test_invalid_fee_assumptions_are_rejected(fee_bps: float) -> None:
    with pytest.raises(ValueError):
        simulate_buy_notional([level(0.50, 10)], 1.0, fee_bps=fee_bps)


def test_invalid_book_levels_fail_validation_instead_of_being_silently_dropped() -> None:
    with pytest.raises(ValidationError):
        L2Level(price=0.0, size=10)
    with pytest.raises(ValidationError):
        L2Level(price=0.50, size=0)
