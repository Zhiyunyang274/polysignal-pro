"""
Tests for the wired risk guards (Iteration 006).

- ExposureGuard: hard per-market / per-strategy exposure limits (previously a
  stub; strategy-level exposure was checked nowhere in the system).
- LiquidityGuard: single source of truth for the side-aware spread/depth gates
  (extracted verbatim from RiskGovernor's inline checks).
- Governor integration: new exposure hard rejects fire; existing behaviour for
  zero-exposure contexts is unchanged (the pre-existing risk_governor tests
  must pass untouched).
"""

from datetime import UTC, datetime

import pytest

from polysignal.models.orderbook import OrderBookSide, OrderBookSnapshot, PriceLevel
from polysignal.models.risk import RiskAction, RiskContext
from polysignal.models.signal import Signal, SignalSide
from polysignal.risk.exposure_guard import (
    MARKET_EXPOSURE_LIMIT,
    STRATEGY_EXPOSURE_LIMIT,
    ExposureGuard,
)
from polysignal.risk.liquidity_guard import DEPTH_TOO_THIN, SPREAD_TOO_WIDE, LiquidityGuard
from polysignal.risk.risk_governor import RiskGovernor

UTC = UTC


def book(yes_bid: float, yes_ask: float, yes_depth: float,
         no_bid: float, no_ask: float, no_depth: float) -> OrderBookSnapshot:
    snapshot = OrderBookSnapshot(
        market_id="m1",
        timestamp=datetime.now(UTC),
        yes_bids=OrderBookSide(levels=[PriceLevel(price=yes_bid, size=yes_depth / yes_bid,
                                                  total_usd=yes_depth)]),
        yes_asks=OrderBookSide(levels=[PriceLevel(price=yes_ask, size=yes_depth / yes_ask,
                                                  total_usd=yes_depth)]),
        no_bids=OrderBookSide(levels=[PriceLevel(price=no_bid, size=no_depth / no_bid,
                                                 total_usd=no_depth)]),
        no_asks=OrderBookSide(levels=[PriceLevel(price=no_ask, size=no_depth / no_ask,
                                                 total_usd=no_depth)]),
        source="test",
    )
    snapshot.calculate_metrics()
    return snapshot


class TestExposureGuard:
    def test_below_limits_passes(self):
        guard = ExposureGuard(max_account_capital_usd=1000.0)
        context = RiskContext(current_market_exposure_usd=10.0, current_strategy_exposure_usd=50.0)
        assert guard.check_exposure(context) == []

    def test_at_market_limit_rejects(self):
        guard = ExposureGuard(max_account_capital_usd=1000.0)  # market cap: 30
        context = RiskContext(current_market_exposure_usd=30.0, current_strategy_exposure_usd=0.0)
        assert guard.check_exposure(context) == [MARKET_EXPOSURE_LIMIT]

    def test_at_strategy_limit_rejects(self):
        guard = ExposureGuard(max_account_capital_usd=1000.0)  # strategy cap: 80
        context = RiskContext(current_market_exposure_usd=0.0, current_strategy_exposure_usd=80.0)
        assert guard.check_exposure(context) == [STRATEGY_EXPOSURE_LIMIT]

    def test_both_limits_rejected(self):
        guard = ExposureGuard(max_account_capital_usd=1000.0)
        context = RiskContext(current_market_exposure_usd=50.0, current_strategy_exposure_usd=99.0)
        reasons = guard.check_exposure(context)
        assert MARKET_EXPOSURE_LIMIT in reasons
        assert STRATEGY_EXPOSURE_LIMIT in reasons

    def test_validation(self):
        with pytest.raises(ValueError):
            ExposureGuard(max_account_capital_usd=0)
        with pytest.raises(ValueError):
            ExposureGuard(max_market_exposure_pct=0.0)
        with pytest.raises(ValueError):
            ExposureGuard(max_strategy_exposure_pct=1.5)


class TestLiquidityGuard:
    def test_clean_book_passes(self):
        guard = LiquidityGuard(min_depth_usd=20.0, max_spread_pct=0.05)
        snapshot = book(0.48, 0.50, 200.0, 0.50, 0.52, 200.0)  # 4% spread, deep
        assert guard.check_liquidity(snapshot, SignalSide.YES) == []

    def test_wide_spread_rejected(self):
        guard = LiquidityGuard(min_depth_usd=20.0, max_spread_pct=0.05)
        snapshot = book(0.40, 0.50, 200.0, 0.50, 0.60, 200.0)  # ~22% spread
        assert guard.check_liquidity(snapshot, SignalSide.YES) == [SPREAD_TOO_WIDE]

    def test_thin_yes_depth_rejected_for_yes_signal(self):
        guard = LiquidityGuard(min_depth_usd=20.0, max_spread_pct=0.05)
        snapshot = book(0.48, 0.50, 10.0, 0.50, 0.52, 200.0)
        reasons = guard.check_liquidity(snapshot, SignalSide.YES)
        assert reasons == [DEPTH_TOO_THIN]

    def test_thin_no_depth_ignored_for_yes_signal(self):
        guard = LiquidityGuard(min_depth_usd=20.0, max_spread_pct=0.05)
        snapshot = book(0.48, 0.50, 200.0, 0.50, 0.52, 10.0)
        assert guard.check_liquidity(snapshot, SignalSide.YES) == []

    def test_both_side_requires_both_sides(self):
        guard = LiquidityGuard(min_depth_usd=20.0, max_spread_pct=0.05)
        thin_no = book(0.48, 0.50, 200.0, 0.50, 0.52, 5.0)
        assert guard.check_liquidity(thin_no, SignalSide.BOTH) == [DEPTH_TOO_THIN]

        thin_yes = book(0.48, 0.50, 5.0, 0.50, 0.52, 200.0)
        assert guard.check_liquidity(thin_yes, SignalSide.BOTH) == [DEPTH_TOO_THIN]

    def test_validation(self):
        with pytest.raises(ValueError):
            LiquidityGuard(min_depth_usd=0)
        with pytest.raises(ValueError):
            LiquidityGuard(max_spread_pct=0)


class TestGovernorIntegration:
    """The guards must be reachable through Risk Governor's normal evaluate()."""

    @staticmethod
    def _signal() -> Signal:
        return Signal(
            market_id="m1",
            market_title="Test market",
            market_category="crypto",
            strategy_name="s",
            side=SignalSide.YES,
            price=0.50,
        )

    def _governor(self) -> RiskGovernor:
        return RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
            max_account_capital_usd=1000.0,
        )

    def test_market_exposure_cap_hard_rejects(self):
        governor = self._governor()
        context = RiskContext(current_market_exposure_usd=31.0)  # cap: 30
        decision = governor.evaluate(self._signal(), context)
        assert decision.action == RiskAction.HARD_REJECT
        assert MARKET_EXPOSURE_LIMIT in decision.hard_reject_reasons

    def test_strategy_exposure_cap_hard_rejects(self):
        governor = self._governor()
        context = RiskContext(current_strategy_exposure_usd=81.0)  # cap: 80
        decision = governor.evaluate(self._signal(), context)
        assert decision.action == RiskAction.HARD_REJECT
        assert STRATEGY_EXPOSURE_LIMIT in decision.hard_reject_reasons

    def test_zero_exposure_unchanged(self):
        governor = self._governor()
        context = RiskContext()
        decision = governor.evaluate(self._signal(), context)
        reasons = set(decision.hard_reject_reasons)
        assert MARKET_EXPOSURE_LIMIT not in reasons
        assert STRATEGY_EXPOSURE_LIMIT not in reasons

    def test_liquidity_delegation_identical(self):
        """Side-aware depth behaviour preserved through the delegated guard."""
        governor = self._governor()
        thin_yes = book(0.48, 0.50, 5.0, 0.50, 0.52, 200.0)
        decision = governor.evaluate(self._signal(), RiskContext(), thin_yes)
        assert DEPTH_TOO_THIN in decision.hard_reject_reasons

        clean = book(0.48, 0.50, 200.0, 0.50, 0.52, 200.0)
        decision = governor.evaluate(self._signal(), RiskContext(), clean)
        assert DEPTH_TOO_THIN not in decision.hard_reject_reasons
        assert SPREAD_TOO_WIDE not in decision.hard_reject_reasons
