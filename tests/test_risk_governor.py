"""
Tests for Risk Governor
"""

import pytest

from polysignal.models.market import MarketCategory
from polysignal.models.risk import RiskAction, RiskContext
from polysignal.models.signal import ComponentScores, Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor
from tests.fixtures.markets import create_mock_market
from tests.fixtures.orderbooks import (
    create_mispricing_orderbook,
    create_thin_depth_orderbook,
    create_wide_spread_orderbook,
)


class TestRiskGovernor:
    """Test Risk Governor"""

    @pytest.fixture
    def governor(self) -> RiskGovernor:
        """Create a Risk Governor with default settings"""
        return RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

    @pytest.fixture
    def good_signal(self) -> Signal:
        """Create a good signal with high enough scores to reach paper trade threshold"""
        return Signal(
            market_id="test_market_001",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.975,
            component_scores=ComponentScores(
                microstructure_score=90,
                liquidity_score=85,
                event_score=85,
                wallet_score=80,
                lifecycle_score=85,
            ),
            raw_score=85,
        )

    @pytest.fixture
    def good_context(self) -> RiskContext:
        """Create a good risk context"""
        return RiskContext(
            live_trading_enabled=False,
            allow_auto_execution=False,
            api_healthy=True,
            websocket_healthy=True,
            market_tradable=True,
            market_ambiguous=False,
            market_forbidden=False,
            price_stale=False,
        )

    def test_default_settings(self, governor: RiskGovernor):
        """Test default settings are safe"""
        assert governor.live_trading_enabled is False
        assert governor.allow_auto_execution is False
        assert governor.paper_trading_enabled is True

    def test_evaluate_good_signal(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test evaluating a good signal"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)
        market = create_mock_market()

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            orderbook=orderbook,
            market=market,
        )

        # Should not be hard rejected
        assert not decision.is_hard_rejected()

        # Should have a score
        assert decision.trade_score > 0

        # Should allow paper trade
        assert decision.allows_paper_trade()

    def test_hard_reject_api_unhealthy(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when API is unhealthy"""
        good_context.api_healthy = False

        decision = governor.evaluate(signal=good_signal, context=good_context)

        assert decision.is_hard_rejected()
        assert "api_unhealthy" in decision.hard_reject_reasons

    def test_hard_reject_websocket_unhealthy(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when WebSocket is unhealthy"""
        good_context.websocket_healthy = False

        decision = governor.evaluate(signal=good_signal, context=good_context)

        assert decision.is_hard_rejected()
        assert "websocket_unhealthy" in decision.hard_reject_reasons

    def test_hard_reject_stale_price(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when price is stale"""
        good_context.price_stale = True

        decision = governor.evaluate(signal=good_signal, context=good_context)

        assert decision.is_hard_rejected()
        assert "price_stale" in decision.hard_reject_reasons

    def test_hard_reject_ambiguous_market(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when market is ambiguous"""
        market = create_mock_market(is_ambiguous=True)

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        assert decision.is_hard_rejected()
        assert "market_ambiguous" in decision.hard_reject_reasons

    def test_hard_reject_forbidden_category(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject for forbidden category"""
        market = create_mock_market(
            category=MarketCategory.POLITICS,
            is_forbidden_auto=True,
        )

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        assert decision.is_hard_rejected()
        assert "forbidden_category" in decision.hard_reject_reasons

    def test_hard_reject_wide_spread(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject for wide spread"""
        orderbook = create_wide_spread_orderbook(spread_pct=0.10)

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            orderbook=orderbook,
        )

        assert decision.is_hard_rejected()
        assert "spread_too_wide" in decision.hard_reject_reasons

    def test_hard_reject_thin_depth(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject for thin depth"""
        orderbook = create_thin_depth_orderbook(depth_usd=5)

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            orderbook=orderbook,
        )

        assert decision.is_hard_rejected()
        assert "depth_too_thin" in decision.hard_reject_reasons

    def test_hard_reject_daily_loss_limit(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when daily loss limit breached"""
        good_context.daily_pnl_usd = -5.0  # Exceeds 3% of $100

        decision = governor.evaluate(signal=good_signal, context=good_context)

        assert decision.is_hard_rejected()
        assert "daily_loss_limit_breached" in decision.hard_reject_reasons

    def test_hard_reject_weekly_loss_limit(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when weekly loss limit breached"""
        good_context.weekly_pnl_usd = -10.0  # Exceeds 8% of $100

        decision = governor.evaluate(signal=good_signal, context=good_context)

        assert decision.is_hard_rejected()
        assert "weekly_loss_limit_breached" in decision.hard_reject_reasons

    def test_hard_reject_consecutive_losses(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when consecutive loss limit breached"""
        good_context.consecutive_losses = 3

        decision = governor.evaluate(signal=good_signal, context=good_context)

        assert decision.is_hard_rejected()
        assert "consecutive_loss_limit_breached" in decision.hard_reject_reasons

    def test_score_calculation(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test trade score calculation"""
        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
        )

        # Score should be weighted average of component scores
        expected = (
            0.30 * 90 +  # microstructure
            0.20 * 85 +  # liquidity
            0.20 * 85 +  # event
            0.15 * 80 +  # wallet
            0.15 * 85    # lifecycle
        )

        assert abs(decision.trade_score - expected) < 1.0

    def test_decision_threshold_ignore(
        self,
        governor: RiskGovernor,
        good_context: RiskContext,
    ):
        """Test ignore threshold"""
        signal = Signal(
            market_id="test",
            market_title="Test",
            market_category="crypto",
            strategy_name="test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=50,
                liquidity_score=50,
                event_score=50,
                wallet_score=50,
                lifecycle_score=50,
            ),
            raw_score=50,
        )

        decision = governor.evaluate(signal=signal, context=good_context)

        assert decision.action == RiskAction.IGNORE
        assert decision.trade_score < 70

    def test_decision_threshold_log_only(
        self,
        governor: RiskGovernor,
        good_context: RiskContext,
    ):
        """Test log_only threshold"""
        signal = Signal(
            market_id="test",
            market_title="Test",
            market_category="crypto",
            strategy_name="test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=75,
                liquidity_score=75,
                event_score=75,
                wallet_score=75,
                lifecycle_score=75,
            ),
            raw_score=75,
        )

        decision = governor.evaluate(signal=signal, context=good_context)

        assert decision.action == RiskAction.LOG_ONLY
        assert 70 <= decision.trade_score < 80

    def test_no_live_execution_by_default(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test that live execution is not allowed by default"""
        # Even with a very high score
        good_signal.component_scores = ComponentScores(
            microstructure_score=100,
            liquidity_score=100,
            event_score=100,
            wallet_score=100,
            lifecycle_score=100,
        )

        decision = governor.evaluate(signal=good_signal, context=good_context)

        # Should not allow live execution
        assert not decision.allows_live_execute()
