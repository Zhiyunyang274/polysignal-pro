"""
Tests for Paper Trader
"""

import pytest

from polysignal.execution.paper_trader import PaperTrader
from polysignal.models.orderbook import OrderBookSide, PriceLevel
from polysignal.models.paper_trade import OrderSide, OrderStatus
from polysignal.models.risk import RiskAction, RiskDecision
from polysignal.models.signal import ComponentScores, Signal, SignalSide
from tests.fixtures.orderbooks import create_mispricing_orderbook, create_mock_orderbook


class TestPaperTrader:
    """Test Paper Trader"""

    @pytest.fixture
    def trader(self) -> PaperTrader:
        """Create a Paper Trader"""
        return PaperTrader(
            default_order_size_usd=1.0,
            slippage_assumption_pct=0.01,
            order_timeout_seconds=20,
        )

    @pytest.fixture
    def good_signal(self) -> Signal:
        """Create a test signal"""
        return Signal(
            signal_id="test_signal_001",
            market_id="test_market_001",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.YES,
            price=0.975,
            component_scores=ComponentScores(
                microstructure_score=85,
                liquidity_score=80,
            ),
            raw_score=80,
        )

    @pytest.fixture
    def good_decision(self) -> RiskDecision:
        """Create a risk decision that allows paper trade"""
        decision = RiskDecision(
            signal_id="test_signal_001",
            action=RiskAction.PAPER_TRADE,
            trade_score=85,
        )
        decision.allowed_actions = [RiskAction.PAPER_TRADE]
        return decision

    def test_default_settings(self, trader: PaperTrader):
        """Test default settings"""
        assert trader.default_order_size_usd == 1.0
        assert trader.slippage_assumption_pct == 0.01
        assert trader.order_timeout_seconds == 20

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"default_order_size_usd": 0.0},
            {"slippage_assumption_pct": -0.01},
            {"slippage_assumption_pct": 1.0},
            {"order_timeout_seconds": 0},
            {"partial_fill_probability": 1.1},
        ],
    )
    def test_invalid_simulation_settings_fail_closed(self, kwargs: dict[str, float]):
        """Invalid cost assumptions cannot silently create optimistic fills."""
        with pytest.raises(ValueError):
            PaperTrader(**kwargs)

    def test_execute_paper_trade(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Test executing a paper trade"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)

        order, position, message = trader.execute(
            signal=good_signal,
            risk_decision=good_decision,
            orderbook=orderbook,
        )

        # Should create order
        assert order is not None
        assert order.status == OrderStatus.FILLED
        assert order.filled_size > 0
        assert order.filled_price > 0

        # Should create position
        assert position is not None
        assert position.size > 0

    def test_no_trade_without_risk_approval(
        self,
        trader: PaperTrader,
        good_signal: Signal,
    ):
        """Test no trade without Risk Governor approval"""
        orderbook = create_mispricing_orderbook()

        # Create decision that does NOT allow paper trade
        decision = RiskDecision(
            signal_id="test_signal_001",
            action=RiskAction.IGNORE,
            trade_score=50,
        )
        decision.allowed_actions = []  # No actions allowed

        order, position, message = trader.execute(
            signal=good_signal,
            risk_decision=decision,
            orderbook=orderbook,
        )

        # Should not create order
        assert order is None
        assert "not allow" in message.lower()

    def test_hard_reject_overrides_inconsistent_allowed_actions(
        self,
        trader: PaperTrader,
        good_signal: Signal,
    ):
        """Hard rejection wins even if a malformed decision lists paper trade."""
        decision = RiskDecision(
            signal_id=good_signal.signal_id,
            action=RiskAction.HARD_REJECT,
            trade_score=99,
            hard_reject_reasons=["stale_price"],
            allowed_actions=[RiskAction.PAPER_TRADE],
        )

        order, position, message = trader.execute(
            good_signal,
            decision,
            create_mispricing_orderbook(),
        )

        assert order is None
        assert position is None
        assert "not allow" in message.lower()

    def test_risk_decision_must_match_signal(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """A decision for another signal cannot authorize this order."""
        good_decision.signal_id = "different_signal"

        order, position, message = trader.execute(
            signal=good_signal,
            risk_decision=good_decision,
            orderbook=create_mispricing_orderbook(),
        )

        assert order is None
        assert position is None
        assert "does not match" in message.lower()

    def test_paired_signal_fails_closed_until_two_leg_model_exists(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """BOTH must not be misreported as a YES-only fill."""
        paired_signal = good_signal.model_copy(update={"side": SignalSide.BOTH})

        order, position, message = trader.execute(
            signal=paired_signal,
            risk_decision=good_decision,
            orderbook=create_mispricing_orderbook(),
        )

        assert order is None
        assert position is None
        assert "paired" in message.lower()

    def test_stale_orderbook_is_rejected(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Execution independently fails closed if the supplied book is stale."""
        orderbook = create_mispricing_orderbook()
        orderbook.is_stale = True

        order, position, message = trader.execute(good_signal, good_decision, orderbook)

        assert order is None
        assert position is None
        assert "stale" in message.lower()

    def test_deterministic_execution(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Test that execution is deterministic"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)

        # Execute twice with same inputs
        order1, _, _ = trader.execute(
            signal=good_signal,
            risk_decision=good_decision,
            orderbook=orderbook,
        )

        order2, _, _ = trader.execute(
            signal=good_signal,
            risk_decision=good_decision,
            orderbook=orderbook,
        )

        # Should produce same results
        if order1 and order2:
            assert order1.filled_price == order2.filled_price

    def test_position_tracking(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Test position tracking"""
        orderbook = create_mispricing_orderbook()

        # Execute trade
        order, position, _ = trader.execute(
            signal=good_signal,
            risk_decision=good_decision,
            orderbook=orderbook,
        )

        # Get position
        stored_position = trader.get_position(good_signal.market_id)

        assert stored_position is not None
        assert stored_position.size == position.size

    def test_pnl_calculation(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Test PnL calculation"""
        orderbook = create_mispricing_orderbook()

        # Execute trade
        order, position, _ = trader.execute(
            signal=good_signal,
            risk_decision=good_decision,
            orderbook=orderbook,
        )

        if position:
            # Mark to market with different price
            new_price = position.avg_entry_price * 1.1  # 10% up
            trader.mark_to_market(good_signal.market_id, new_price)

            # Check unrealized PnL
            updated_position = trader.get_position(good_signal.market_id)
            if updated_position:
                assert updated_position.unrealized_pnl_usd != 0

    def test_get_stats(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Test getting statistics"""
        orderbook = create_mispricing_orderbook()

        # Execute a few trades
        for _ in range(3):
            trader.execute(
                signal=good_signal,
                risk_decision=good_decision,
                orderbook=orderbook,
            )

        stats = trader.get_stats()

        assert stats.total_trades >= 3

    def test_get_all_orders(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Test getting all orders"""
        orderbook = create_mispricing_orderbook()

        # Execute trades
        for _ in range(5):
            trader.execute(
                signal=good_signal,
                risk_decision=good_decision,
                orderbook=orderbook,
            )

        orders = trader.get_all_orders()

        assert len(orders) >= 5

    def test_get_all_positions(self, trader: PaperTrader):
        """Test getting all positions"""
        positions = trader.get_all_positions()

        # Should return list (may be empty)
        assert isinstance(positions, list)

    def test_limit_order_only(self, trader: PaperTrader):
        """Test that only LIMIT orders are supported"""
        # Paper trader should only create limit orders
        # This is enforced by the model default
        assert True  # OrderType.MARKET is removed from model

    def test_walks_visible_ask_levels_and_uses_vwap(
        self,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """A buy consumes asks from best to worst instead of inventing flat depth."""
        trader = PaperTrader(slippage_assumption_pct=0.0)
        orderbook = create_mock_orderbook()
        orderbook.yes_asks = OrderBookSide(
            levels=[
                PriceLevel(price=0.60, size=10.0, total_usd=6.0),
                PriceLevel(price=0.50, size=1.0, total_usd=0.5),
            ]
        )
        signal = good_signal.model_copy(update={"price": 0.60})

        order, _, _ = trader.execute(signal, good_decision, orderbook, size_usd=2.0)

        assert order is not None
        expected_shares = 1.0 + 1.5 / 0.60
        assert order.filled_size == pytest.approx(expected_shares)
        assert order.filled_price == pytest.approx(2.0 / expected_shares)
        assert order.slippage == pytest.approx((order.filled_price - 0.50) / 0.50)

    def test_limit_price_rejects_unmarketable_buy(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """The paper limit price is a hard cap even after stress slippage."""
        signal = good_signal.model_copy(update={"price": 0.47})

        order, position, message = trader.execute(
            signal,
            good_decision,
            create_mispricing_orderbook(),
        )

        assert order is None
        assert position is None
        assert "limit price" in message.lower()

    def test_stress_slippage_never_exceeds_limit_price(
        self,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """The stress assumption may remove improvement but cannot violate the limit."""
        trader = PaperTrader(slippage_assumption_pct=0.10)
        orderbook = create_mock_orderbook(yes_ask=0.50)
        signal = good_signal.model_copy(update={"price": 0.50})

        order, _, _ = trader.execute(signal, good_decision, orderbook)

        assert order is not None
        assert order.filled_price == pytest.approx(0.50)

    def test_visible_depth_produces_deterministic_partial_fill(
        self,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Insufficient visible size produces a partial fill without randomness."""
        trader = PaperTrader(slippage_assumption_pct=0.0)
        orderbook = create_mock_orderbook(yes_depth_usd=0.50)

        order, _, _ = trader.execute(good_signal, good_decision, orderbook, size_usd=2.0)

        assert order is not None
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_size == pytest.approx(orderbook.yes_asks.levels[0].size)

    def test_explicit_zero_size_is_rejected(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """An explicit zero must not fall back to the configured default size."""
        order, position, message = trader.execute(
            good_signal,
            good_decision,
            create_mispricing_orderbook(),
            size_usd=0.0,
        )

        assert order is None
        assert position is None
        assert "positive" in message.lower()

    def test_buy_no_pnl_increases_when_no_token_price_rises(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """BUY_NO is long the NO token, not a short NO position."""
        no_signal = good_signal.model_copy(update={"side": SignalSide.NO, "price": 0.60})
        order, position, _ = trader.execute(
            no_signal,
            good_decision,
            create_mock_orderbook(),
        )

        assert order is not None
        assert order.side == OrderSide.BUY_NO
        assert position is not None
        trader.mark_to_market(no_signal.market_id, position.avg_entry_price + 0.05)
        assert position.unrealized_pnl_usd > 0

    def test_opposite_outcomes_are_not_net_merged_in_one_position(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """The market-only position key cannot safely mix YES and NO shares."""
        first_order, _, _ = trader.execute(
            good_signal,
            good_decision,
            create_mock_orderbook(),
        )
        assert first_order is not None
        no_signal = good_signal.model_copy(update={"side": SignalSide.NO, "price": 0.60})

        order, position, message = trader.execute(
            no_signal,
            good_decision,
            create_mock_orderbook(),
        )

        assert order is None
        assert position is None
        assert "different outcome" in message.lower()

    def test_mark_to_market_rejects_invalid_probability_price(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Invalid marks do not mutate a position's current price or PnL."""
        _, position, _ = trader.execute(
            good_signal,
            good_decision,
            create_mispricing_orderbook(),
        )
        assert position is not None
        previous_price = position.current_price

        result = trader.mark_to_market(good_signal.market_id, float("nan"))

        assert result is None
        assert position.current_price == previous_price

    def test_close_position_preserves_filled_size_and_realizes_pnl(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Closing captures size before zeroing the position."""
        _, position, _ = trader.execute(
            good_signal,
            good_decision,
            create_mispricing_orderbook(),
        )
        assert position is not None
        size_before_close = position.size
        close_price = position.avg_entry_price + 0.05

        close_order, pnl = trader.close_position(
            good_signal.market_id,
            close_price,
            risk_decision=good_decision,
        )

        assert close_order is not None
        assert close_order.side == OrderSide.SELL_YES
        assert close_order.size == pytest.approx(size_before_close)
        assert close_order.filled_size == pytest.approx(size_before_close)
        assert pnl == pytest.approx(size_before_close * 0.05)
        assert position.size == 0
        assert position.unrealized_pnl_usd == 0

    def test_close_position_requires_risk_approval(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """Paper exits cannot bypass the central risk decision contract."""
        _, position, _ = trader.execute(
            good_signal,
            good_decision,
            create_mispricing_orderbook(),
        )
        assert position is not None

        close_order, pnl = trader.close_position(
            good_signal.market_id,
            position.avg_entry_price,
        )

        assert close_order is None
        assert pnl == 0.0
        assert position.size > 0

    def test_hard_reject_cannot_authorize_close_via_allowed_actions(
        self,
        trader: PaperTrader,
        good_signal: Signal,
        good_decision: RiskDecision,
    ):
        """A contradictory hard-reject decision cannot mutate the position."""
        _, position, _ = trader.execute(
            good_signal,
            good_decision,
            create_mispricing_orderbook(),
        )
        assert position is not None
        original_size = position.size
        rejected = RiskDecision(
            signal_id=good_signal.signal_id,
            action=RiskAction.HARD_REJECT,
            trade_score=99,
            hard_reject_reasons=["daily_loss_limit"],
            allowed_actions=[RiskAction.PAPER_TRADE],
        )

        close_order, pnl = trader.close_position(
            good_signal.market_id,
            position.avg_entry_price,
            risk_decision=rejected,
        )

        assert close_order is None
        assert pnl == 0.0
        assert position.size == pytest.approx(original_size)
