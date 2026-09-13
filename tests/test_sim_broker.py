"""
Tests for SimBroker - deterministic account-level simulated broker.

Covers:
- happy-path buy/sell round trips with fees and exact cash accounting
- L2 depth handling (full fill, partial fill, insufficient depth, limit caps)
- deterministic fault injection (network error / API timeout / venue rejection)
- latency + quote staleness gates
- full-close-only share accounting (oversell / partial close fail-closed)
- AccountState integration (exposure, consecutive losses, equity identity)
"""

from datetime import UTC, datetime, timedelta

import pytest

from polysignal.execution.account_state import AccountState
from polysignal.execution.sim_broker import (
    FaultSchedule,
    SimBroker,
    SimOrderStatus,
    SimSide,
)
from polysignal.shadow.execution_cost import L2Level

UTC = UTC
T0 = datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)


def asks() -> list[L2Level]:
    """150 USD of visible ask liquidity: 300 shares @ 0.50, then 0.52."""
    return [L2Level(price=0.50, size=300), L2Level(price=0.52, size=300)]


def bids() -> list[L2Level]:
    """165 USD of visible bid liquidity at 0.55."""
    return [L2Level(price=0.55, size=300)]


def make_broker(starting_capital: float = 10000.0, **kwargs) -> SimBroker:
    return SimBroker(AccountState(starting_capital_usd=starting_capital), **kwargs)


class TestBuySellRoundTrip:
    def test_buy_ledgers_cash_exposure_and_shares(self):
        broker = make_broker(fee_bps=100)  # 1% per side

        order = broker.submit_buy(
            market_id="m1",
            strategy_name="s",
            asks=asks(),
            notional_usd=100.0,
            now=T0,
            quote_timestamp=T0,
        )

        assert order.status == SimOrderStatus.FILLED
        assert order.side == SimSide.BUY
        assert order.filled_notional_usd == pytest.approx(100.0)
        assert order.filled_shares == pytest.approx(200.0)
        assert order.fee_usd == pytest.approx(1.0)

        # Cash paid = notional + fee; equity unchanged until close
        assert broker.account_state.cash_usd == pytest.approx(10000.0 - 101.0)
        assert broker.account_state.market_exposure_usd("m1") == pytest.approx(101.0)
        assert broker.equity_usd() == pytest.approx(10000.0)

        position = broker.get_position("m1")
        assert position is not None
        assert position.shares == pytest.approx(200.0)
        assert position.total_net_cost_usd == pytest.approx(101.0)
        assert position.avg_net_entry_price == pytest.approx(101.0 / 200.0)

    def test_full_round_trip_profitable(self):
        broker = make_broker(fee_bps=100)
        broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0, quote_timestamp=T0,
        )
        sell = broker.submit_sell(
            market_id="m1", bids=bids(), shares=200.0, now=T0, quote_timestamp=T0,
        )

        assert sell.status == SimOrderStatus.FILLED
        assert sell.filled_notional_usd == pytest.approx(110.0)  # 200 * 0.55
        assert sell.fee_usd == pytest.approx(1.1)
        assert sell.realized_pnl_usd is not None
        assert sell.realized_pnl_usd == pytest.approx((110.0 - 1.1) - 101.0)

        # Cash identity: initial + realized PnL
        assert broker.account_state.cash_usd == pytest.approx(10000.0 + sell.realized_pnl_usd)
        assert broker.account_state.market_exposure_usd("m1") == 0.0
        assert broker.get_position("m1") is None
        assert broker.account_state.consecutive_losses == 0

    def test_full_round_trip_loss_increments_consecutive_losses(self):
        broker = make_broker(fee_bps=100)
        broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0, quote_timestamp=T0,
        )
        # Exit below entry: bid at 0.40
        sell = broker.submit_sell(
            market_id="m1",
            bids=[L2Level(price=0.40, size=300)],
            shares=200.0,
            now=T0,
            quote_timestamp=T0,
        )

        assert sell.realized_pnl_usd == pytest.approx((80.0 - 0.8) - 101.0)
        assert sell.realized_pnl_usd < 0
        assert broker.account_state.consecutive_losses == 1
        assert broker.account_state.cash_usd == pytest.approx(10000.0 + sell.realized_pnl_usd)


class TestRejections:
    def test_insufficient_cash_rejected(self):
        broker = make_broker(starting_capital=50.0)
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
        )
        assert order.status == SimOrderStatus.REJECTED
        assert order.reject_reason == "insufficient_cash"

    def test_invalid_notional_rejected(self):
        broker = make_broker()
        for bad in (0.0, -1.0, float("nan")):
            order = broker.submit_buy(
                market_id="m1", strategy_name="s", asks=asks(),
                notional_usd=bad, now=T0,
            )
            assert order.reject_reason == "invalid_notional"

    def test_insufficient_depth_rejected_fail_closed(self):
        broker = make_broker()  # allow_partial_fills=False by default
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=1000.0, now=T0,
        )
        assert order.status == SimOrderStatus.REJECTED
        assert order.reject_reason == "l2_insufficient_visible_depth"

    def test_partial_fill_when_allowed(self):
        broker = make_broker(allow_partial_fills=True)
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=1000.0, now=T0,
        )
        assert order.status == SimOrderStatus.PARTIAL
        assert order.filled_notional_usd == pytest.approx(306.0)  # 150 + 156 visible
        position = broker.get_position("m1")
        assert position is not None
        assert position.shares == pytest.approx(600.0)

    def test_limit_price_caps_consumed_levels(self):
        broker = make_broker()
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=250.0, limit_price=0.51, now=T0,
        )
        # Only the 0.50 level (150 USD) is within the limit -> insufficient
        assert order.status == SimOrderStatus.REJECTED
        assert order.reject_reason == "l2_insufficient_visible_depth"

    def test_crossed_book_rejected(self):
        broker = make_broker()
        crossed = [L2Level(price=0.60, size=300)]
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=crossed,
            notional_usd=100.0, limit_price=0.55, now=T0,
        )
        # Nothing under the limit -> no executable levels
        assert order.status == SimOrderStatus.REJECTED

    def test_sell_without_position_rejected(self):
        broker = make_broker()
        order = broker.submit_sell(
            market_id="m1", bids=bids(), shares=100.0, now=T0,
        )
        assert order.reject_reason == "no_open_position"

    def test_oversell_and_partial_close_rejected(self):
        broker = make_broker(fee_bps=100)
        broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
        )

        oversell = broker.submit_sell(
            market_id="m1", bids=bids(), shares=300.0, now=T0,
        )
        assert oversell.reject_reason == "oversell_blocked"

        partial = broker.submit_sell(
            market_id="m1", bids=bids(), shares=100.0, now=T0,
        )
        assert partial.reject_reason == "full_close_only"

        # Position must be untouched after failed sells
        assert broker.get_position("m1") is not None
        assert broker.account_state.market_exposure_usd("m1") == pytest.approx(101.0)


class TestFaultInjection:
    def test_injected_network_error(self):
        broker = make_broker(fault_schedule=FaultSchedule(network_errors={0}))
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
        )
        assert order.status == SimOrderStatus.REJECTED
        assert order.reject_reason == "injected_network_error"
        assert broker.account_state.cash_usd == pytest.approx(10000.0)
        # Sequence advanced: the next order is NOT faulted
        second = broker.submit_buy(
            market_id="m2", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
        )
        assert second.status == SimOrderStatus.FILLED

    def test_injected_api_timeout_and_rejection(self):
        broker = make_broker(
            fault_schedule=FaultSchedule(api_timeouts={0}, rejections={1})
        )
        first = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
        )
        second = broker.submit_buy(
            market_id="m2", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
        )
        assert first.reject_reason == "injected_api_timeout"
        assert second.reject_reason == "injected_venue_rejection"

    def test_schedule_is_deterministic(self):
        schedule = FaultSchedule(rejections={1})
        outcomes = []
        for _ in range(2):
            broker = make_broker(fault_schedule=schedule)
            first = broker.submit_buy(
                market_id="m1", strategy_name="s", asks=asks(),
                notional_usd=100.0, now=T0,
            )
            second = broker.submit_buy(
                market_id="m2", strategy_name="s", asks=asks(),
                notional_usd=100.0, now=T0,
            )
            outcomes.append((first.status, second.status, second.reject_reason))
        assert outcomes[0] == outcomes[1]


class TestLatencyAndStaleness:
    def test_fill_time_reflects_latency(self):
        broker = make_broker(submission_latency_seconds=7.5)
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0, quote_timestamp=T0,
        )
        assert order.decision_time == T0
        assert order.fill_time == T0 + timedelta(seconds=7.5)

    def test_stale_quote_at_fill_rejected(self):
        broker = make_broker(submission_latency_seconds=10.0, max_quote_age_seconds=60.0)
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
            quote_timestamp=T0 - timedelta(seconds=55),  # age 65s at fill
        )
        assert order.reject_reason == "quote_too_stale_at_fill"
        assert broker.account_state.cash_usd == pytest.approx(10000.0)

    def test_fresh_quote_within_age_allowed(self):
        broker = make_broker(submission_latency_seconds=10.0, max_quote_age_seconds=60.0)
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
            quote_timestamp=T0 - timedelta(seconds=5),  # age 15s at fill
        )
        assert order.status == SimOrderStatus.FILLED

    def test_future_quote_rejected(self):
        broker = make_broker()
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
            quote_timestamp=T0 + timedelta(seconds=30),
        )
        assert order.reject_reason == "quote_from_future"

    def test_naive_quote_timestamp_treated_as_utc(self):
        broker = make_broker()
        order = broker.submit_buy(
            market_id="m1", strategy_name="s", asks=asks(),
            notional_usd=100.0, now=T0,
            quote_timestamp=datetime(2026, 9, 11, 12, 0, 0),
        )
        assert order.status == SimOrderStatus.FILLED


class TestValidation:
    def test_invalid_constructor_args(self):
        account = AccountState(starting_capital_usd=1000.0)
        with pytest.raises(ValueError):
            SimBroker(account, fee_bps=20000.0)
        with pytest.raises(ValueError):
            SimBroker(account, fee_bps=float("nan"))
        with pytest.raises(ValueError):
            SimBroker(account, submission_latency_seconds=-1.0)
        with pytest.raises(ValueError):
            SimBroker(account, max_quote_age_seconds=-1.0)

    def test_orders_are_recorded_in_sequence(self):
        broker = make_broker(fault_schedule=FaultSchedule(rejections={0}))
        broker.submit_buy(market_id="m1", strategy_name="s", asks=asks(),
                          notional_usd=100.0, now=T0)
        broker.submit_buy(market_id="m2", strategy_name="s", asks=asks(),
                          notional_usd=100.0, now=T0)
        assert [order.sequence for order in broker.orders] == [0, 1]
        assert broker.orders[0].status == SimOrderStatus.REJECTED
        assert broker.orders[1].status == SimOrderStatus.FILLED
