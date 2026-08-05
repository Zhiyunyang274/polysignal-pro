"""
Integration Tests - Risk Governor + Event Intelligence Engine

Tests the integration between Risk Governor and Event Intelligence Engine,
particularly the dual safeguard for event_signal_only detection.
"""

import pytest

from datetime import datetime, timedelta

from polysignal.models.event import SuggestedMode
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.signal import Signal, SignalSide, ComponentScores
from polysignal.models.risk import RiskContext, RiskAction
from polysignal.risk.risk_governor import RiskGovernor
from polysignal.engines.event_intelligence import EventIntelligenceEngine
from polysignal.llm.mock_provider import MockScenario
from tests.fixtures.events import (
    create_event_market,
    create_high_event_score_assessment,
    create_low_event_score_assessment,
    create_high_ambiguity_assessment,
    create_llm_error_assessment,
    create_forbidden_category_assessment,
)


def create_test_signal(
    signal_id: str = "test_001",
    market_id: str = "market_001",
    market_title: str = "Test Market",
    market_category: str = "crypto",
    strategy_name: str = "test_strategy",
    side: SignalSide = SignalSide.YES,
    price: float = 0.5,
    microstructure_score: float = 70.0,
    liquidity_score: float = 70.0,
    event_score: float = 70.0,
    wallet_score: float = 70.0,
    lifecycle_score: float = 70.0,
    risk_flags: list[str] = None,
) -> Signal:
    """Helper to create test signals with required fields"""
    if risk_flags is None:
        risk_flags = []
    return Signal(
        signal_id=signal_id,
        market_id=market_id,
        market_title=market_title,
        market_category=market_category,
        strategy_name=strategy_name,
        side=side,
        price=price,
        component_scores=ComponentScores(
            microstructure_score=microstructure_score,
            liquidity_score=liquidity_score,
            event_score=event_score,
            wallet_score=wallet_score,
            lifecycle_score=lifecycle_score,
        ),
        risk_flags=risk_flags,
    )


class TestRiskGovernorEventIntegration:
    """Test Risk Governor + Event Intelligence integration"""

    @pytest.fixture
    def governor(self) -> RiskGovernor:
        """Create Risk Governor with default settings"""
        return RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

    @pytest.fixture
    def event_engine(self) -> EventIntelligenceEngine:
        """Create Event Intelligence Engine"""
        return EventIntelligenceEngine(scenario=MockScenario.SUCCESS)

    @pytest.fixture
    def context(self) -> RiskContext:
        """Create default risk context"""
        return RiskContext(
            live_trading_enabled=False,
            api_healthy=True,
            websocket_healthy=True,
            price_stale=False,
            daily_pnl_usd=0.0,
            weekly_pnl_usd=0.0,
            consecutive_losses=0,
            current_market_exposure_usd=0.0,
        )

    # =========================================================================
    # Event Score in Trade Score Tests
    # =========================================================================

    def test_event_score_included_in_trade_score(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test event_score is included in trade_score calculation"""
        signal = create_test_signal(event_score=80.0)

        decision = governor.evaluate(signal, context)

        # trade_score should include event_score * 0.20
        assert decision.trade_score > 0
        assert decision.component_scores["event"] == 80.0

    def test_event_score_weight_in_trade_score(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test event_score has 20% weight in trade_score"""
        signal1 = create_test_signal(signal_id="test_001", event_score=70.0)
        signal2 = create_test_signal(signal_id="test_002", event_score=80.0)

        decision1 = governor.evaluate(signal1, context)
        decision2 = governor.evaluate(signal2, context)

        # Difference should be 10 * 0.20 = 2.0
        score_diff = decision2.trade_score - decision1.trade_score
        assert abs(score_diff - 2.0) < 0.1

    # =========================================================================
    # Event Signal Only - Dual Safeguard Tests
    # =========================================================================

    def test_event_signal_only_hard_reject_from_flags(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test event_signal_only hard reject from signal.risk_flags"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["event_signal_only"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.action == RiskAction.HARD_REJECT
        assert "event_signal_only_reason" in decision.hard_reject_reasons

    def test_event_signal_only_hard_reject_direct_check(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test event_signal_only hard reject from direct component_scores check"""
        # event_score >= 80, other scores < 60
        signal = create_test_signal(
            microstructure_score=50.0,  # < 60
            liquidity_score=55.0,  # < 60
            event_score=85.0,  # >= 80
            wallet_score=45.0,  # < 60
            lifecycle_score=70.0,
            risk_flags=[],
        )

        decision = governor.evaluate(signal, context)

        # Should be hard rejected due to direct check
        assert decision.action == RiskAction.HARD_REJECT
        assert "event_signal_only_reason" in decision.hard_reject_reasons

    def test_event_signal_not_rejected_with_strong_microstructure(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test not rejected when microstructure is strong"""
        # event_score >= 80, but microstructure >= 60
        signal = create_test_signal(
            microstructure_score=65.0,  # >= 60
            liquidity_score=55.0,
            event_score=85.0,
            wallet_score=45.0,
            lifecycle_score=70.0,
            risk_flags=[],
        )

        decision = governor.evaluate(signal, context)

        # Should NOT be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        assert "event_signal_only_reason" not in decision.hard_reject_reasons

    def test_event_signal_not_rejected_with_strong_wallet(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test not rejected when wallet score is strong"""
        # event_score >= 80, but wallet >= 60
        signal = create_test_signal(
            microstructure_score=50.0,
            liquidity_score=55.0,
            event_score=85.0,
            wallet_score=65.0,  # >= 60
            lifecycle_score=70.0,
            risk_flags=[],
        )

        decision = governor.evaluate(signal, context)

        # Should NOT be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        assert "event_signal_only_reason" not in decision.hard_reject_reasons

    def test_event_signal_not_rejected_with_weak_event(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test not rejected when event score is weak"""
        # event_score < 80
        signal = create_test_signal(
            microstructure_score=50.0,
            liquidity_score=55.0,
            event_score=75.0,  # < 80
            wallet_score=45.0,
            lifecycle_score=70.0,
            risk_flags=[],
        )

        decision = governor.evaluate(signal, context)

        # Should NOT be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        assert "event_signal_only_reason" not in decision.hard_reject_reasons

    def test_dual_safeguard_both_trigger(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test dual safeguard - both flag and direct check trigger"""
        # Both signal.risk_flags has event_signal_only AND component_scores match
        signal = create_test_signal(
            microstructure_score=50.0,
            liquidity_score=55.0,
            event_score=85.0,
            wallet_score=45.0,
            lifecycle_score=70.0,
            risk_flags=["event_signal_only"],
        )

        decision = governor.evaluate(signal, context)

        # Should have exactly one event_signal_only_reason (not duplicated)
        assert decision.action == RiskAction.HARD_REJECT
        assert decision.hard_reject_reasons.count("event_signal_only_reason") == 1

    # =========================================================================
    # Event Forbidden Category Tests
    # =========================================================================

    def test_event_forbidden_category_hard_reject(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test event_forbidden_category triggers hard reject"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["event_forbidden_category"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.action == RiskAction.HARD_REJECT
        assert "forbidden_category" in decision.hard_reject_reasons

    # =========================================================================
    # Event Penalties Tests
    # =========================================================================

    def test_event_high_ambiguity_penalty(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test event_high_ambiguity penalty is applied"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["event_high_ambiguity"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.event_ambiguity_penalty == 10.0

    def test_event_weak_evidence_penalty(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test event_weak_evidence penalty is applied"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["event_weak_evidence"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.event_weak_evidence_penalty == 5.0

    def test_llm_failure_penalty(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test LLM failure penalty is applied"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["llm_error"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.llm_failure_penalty == 5.0

    def test_llm_low_confidence_penalty(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test LLM low confidence penalty is applied"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["llm_low_confidence"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.llm_failure_penalty == 3.0

    # =========================================================================
    # LLM Error Not Hard Reject Tests
    # =========================================================================

    def test_llm_error_not_hard_reject(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test LLM error does not trigger hard reject"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=50.0,  # Default score from LLM error
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["llm_error"],
        )

        decision = governor.evaluate(signal, context)

        # Should NOT be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        # But should have penalty
        assert decision.llm_failure_penalty == 5.0

    # =========================================================================
    # Live Trading Disabled Tests
    # =========================================================================

    def test_live_trading_disabled_by_default(self):
        """Test live trading is disabled by default"""
        governor = RiskGovernor()

        assert governor.live_trading_enabled is False
        assert governor.allow_auto_execution is False

    def test_paper_trading_enabled_by_default(self):
        """Test paper trading is enabled by default"""
        governor = RiskGovernor()

        assert governor.paper_trading_enabled is True

    def test_high_score_paper_trade_not_live(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test high score results in PAPER_TRADE, not LIVE_EXECUTE"""
        signal = create_test_signal(
            microstructure_score=95.0,
            liquidity_score=95.0,
            event_score=95.0,
            wallet_score=95.0,
            lifecycle_score=95.0,
        )

        decision = governor.evaluate(signal, context)

        # High score but should be PAPER_TRADE, not LIVE_EXECUTE
        assert decision.action == RiskAction.PAPER_TRADE
        assert RiskAction.LIVE_EXECUTE not in decision.allowed_actions

    # =========================================================================
    # Full Integration Tests
    # =========================================================================

    def test_full_integration_event_engine_to_risk_governor(
        self,
        event_engine: EventIntelligenceEngine,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test full integration from event engine to risk governor"""
        # Step 1: Get event assessment
        market = create_event_market()
        assessment = event_engine.assess(market)

        # Step 2: Create signal with event scores
        signal = create_test_signal(
            signal_id="test_001",
            market_id=market.market_id,
            market_title=market.title,
            market_category="crypto",
            strategy_name="event_test",
            event_score=assessment.event_score,
            risk_flags=assessment.risk_flags,
        )

        # Step 3: Evaluate through risk governor
        decision = governor.evaluate(signal, context, market=market)

        # Should not be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        assert decision.trade_score > 0

    def test_full_integration_with_llm_error(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test full integration with LLM error"""
        # Simulate LLM error assessment
        assessment = create_llm_error_assessment(
            market_id="test_market",
            error_flag="llm_error",
        )

        signal = create_test_signal(
            market_id="test_market",
            event_score=assessment.event_score,  # 50
            risk_flags=assessment.risk_flags,  # ["llm_error"]
        )

        decision = governor.evaluate(signal, context)

        # Should not be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        # But should have penalty
        assert decision.llm_failure_penalty == 5.0

    # =========================================================================
    # Suggested Mode Tests
    # =========================================================================

    def test_suggested_mode_no_trade(self):
        """Test that suggested_mode cannot be 'trade'"""
        valid_modes = ["ignore", "research", "alert_only", "manual_review", "avoid"]
        for mode in SuggestedMode:
            assert mode.value in valid_modes
            assert mode.value != "trade"
