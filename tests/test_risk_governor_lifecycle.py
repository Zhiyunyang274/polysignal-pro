"""
Tests for Risk Governor + Lifecycle Integration
"""

import pytest

from polysignal.engines.resolution_lifecycle import ResolutionLifecycleEngine
from polysignal.models.risk import RiskContext
from polysignal.models.signal import ComponentScores, Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor
from tests.fixtures.lifecycle import (
    create_ambiguous_market,
    create_closed_market,
    create_forbidden_category_market,
    create_mid_phase_market,
    create_resolved_market,
)
from tests.fixtures.orderbooks import create_mock_orderbook


class TestRiskGovernorLifecycleIntegration:
    """Test Risk Governor integration with Lifecycle Engine"""

    @pytest.fixture
    def governor(self) -> RiskGovernor:
        """Create Risk Governor with default settings"""
        return RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

    @pytest.fixture
    def lifecycle_engine(self) -> ResolutionLifecycleEngine:
        """Create Lifecycle Engine"""
        return ResolutionLifecycleEngine()

    @pytest.fixture
    def good_signal(self) -> Signal:
        """Create a good signal"""
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
                lifecycle_score=90,  # Will be updated by lifecycle engine
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

    # =========================================================================
    # Hard Rejection Tests - Market Status
    # =========================================================================

    def test_hard_reject_closed_market(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when market is CLOSED"""
        market = create_closed_market()
        assessment = lifecycle_engine.assess(market)

        # Update signal with lifecycle assessment
        good_signal.component_scores.lifecycle_score = assessment.lifecycle_score
        for flag in assessment.risk_flags:
            good_signal.add_risk_flag(flag)

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        assert decision.is_hard_rejected()
        assert "market_not_open" in decision.hard_reject_reasons

    def test_hard_reject_resolved_market(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when market is RESOLVED"""
        market = create_resolved_market()
        assessment = lifecycle_engine.assess(market)

        good_signal.component_scores.lifecycle_score = assessment.lifecycle_score
        for flag in assessment.risk_flags:
            good_signal.add_risk_flag(flag)

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        assert decision.is_hard_rejected()
        assert "market_not_open" in decision.hard_reject_reasons

    # =========================================================================
    # Hard Rejection Tests - Ambiguity
    # =========================================================================

    def test_hard_reject_ambiguous_market(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when market is ambiguous"""
        market = create_ambiguous_market()
        assessment = lifecycle_engine.assess(market)

        good_signal.component_scores.lifecycle_score = assessment.lifecycle_score
        for flag in assessment.risk_flags:
            good_signal.add_risk_flag(flag)

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        assert decision.is_hard_rejected()
        assert "market_ambiguous" in decision.hard_reject_reasons

    def test_hard_reject_ambiguous_from_signal_flags(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when ambiguity is in signal.risk_flags (supplementary)"""
        # Even without market object, signal.risk_flags should trigger rejection
        good_signal.add_risk_flag("market_ambiguous")

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=None,
        )

        assert decision.is_hard_rejected()
        assert "market_ambiguous" in decision.hard_reject_reasons

    # =========================================================================
    # Hard Rejection Tests - Forbidden Category
    # =========================================================================

    def test_hard_reject_forbidden_category_direct(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject for forbidden category (direct check)"""
        market = create_forbidden_category_market()

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        assert decision.is_hard_rejected()
        assert "forbidden_category" in decision.hard_reject_reasons

    def test_hard_reject_forbidden_category_from_signal_flags(
        self,
        governor: RiskGovernor,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test hard reject when forbidden_category is in signal.risk_flags (supplementary)"""
        good_signal.add_risk_flag("forbidden_category")

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=None,
        )

        assert decision.is_hard_rejected()
        assert "forbidden_category" in decision.hard_reject_reasons

    def test_hard_reject_forbidden_category_dual_safeguard(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test that both direct check and signal flags work as dual safeguard"""
        market = create_forbidden_category_market()
        assessment = lifecycle_engine.assess(market)

        # Signal flags are set
        good_signal.component_scores.lifecycle_score = assessment.lifecycle_score
        for flag in assessment.risk_flags:
            good_signal.add_risk_flag(flag)

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        assert decision.is_hard_rejected()
        # Should only appear once in reasons
        assert decision.hard_reject_reasons.count("forbidden_category") == 1

    # =========================================================================
    # Lifecycle Score Integration Tests
    # =========================================================================

    def test_lifecycle_score_in_trade_score(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test that lifecycle_score is used in trade_score calculation"""
        market = create_mid_phase_market()
        assessment = lifecycle_engine.assess(market)

        # Update signal with lifecycle score
        good_signal.component_scores.lifecycle_score = assessment.lifecycle_score

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        # Expected score with lifecycle_score = 90
        # 0.30 * 90 + 0.20 * 85 + 0.20 * 85 + 0.15 * 80 + 0.15 * 90 = 86.5
        expected = (
            0.30 * 90 +  # microstructure
            0.20 * 85 +  # liquidity
            0.20 * 85 +  # event
            0.15 * 80 +  # wallet
            0.15 * 90    # lifecycle
        )

        assert abs(decision.trade_score - expected) < 1.0

    def test_lifecycle_score_penalty_reduces_trade_score(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test that lower lifecycle_score reduces trade_score"""
        # Test with high lifecycle score
        market_high = create_mid_phase_market()
        assessment_high = lifecycle_engine.assess(market_high)

        good_signal.component_scores.lifecycle_score = assessment_high.lifecycle_score
        decision_high = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market_high,
        )

        # Test with lower lifecycle score (late phase)
        from tests.fixtures.lifecycle import create_late_phase_market
        market_low = create_late_phase_market()
        assessment_low = lifecycle_engine.assess(market_low)

        good_signal.component_scores.lifecycle_score = assessment_low.lifecycle_score
        decision_low = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market_low,
        )

        # Lower lifecycle_score should result in lower trade_score
        assert decision_low.trade_score < decision_high.trade_score

    def test_lifecycle_score_zero_for_closed_market(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test that closed market has lifecycle_score = 0"""
        market = create_closed_market()
        assessment = lifecycle_engine.assess(market)

        assert assessment.lifecycle_score == 0.0

    # =========================================================================
    # Integration Flow Tests
    # =========================================================================

    def test_full_integration_flow(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test full integration flow: Lifecycle Engine -> Signal -> Risk Governor"""
        market = create_mid_phase_market()

        # Step 1: Lifecycle Engine assesses market
        assessment = lifecycle_engine.assess(market)

        # Step 2: Update signal with lifecycle assessment
        good_signal.component_scores.lifecycle_score = assessment.lifecycle_score
        for flag in assessment.risk_flags:
            good_signal.add_risk_flag(flag)

        # Step 3: Risk Governor evaluates
        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            market=market,
        )

        # Step 4: Verify decision
        assert not decision.is_hard_rejected()
        assert decision.trade_score > 0
        assert decision.allows_paper_trade()

    def test_integration_with_orderbook(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_signal: Signal,
        good_context: RiskContext,
    ):
        """Test integration with orderbook"""
        market = create_mid_phase_market()
        orderbook = create_mock_orderbook()

        assessment = lifecycle_engine.assess(market)
        good_signal.component_scores.lifecycle_score = assessment.lifecycle_score

        decision = governor.evaluate(
            signal=good_signal,
            context=good_context,
            orderbook=orderbook,
            market=market,
        )

        assert not decision.is_hard_rejected()

    # =========================================================================
    # Safety Verification Tests
    # =========================================================================

    def test_live_trading_still_disabled(
        self,
        governor: RiskGovernor,
    ):
        """Verify live trading is still disabled"""
        assert governor.live_trading_enabled is False
        assert governor.allow_auto_execution is False
        assert governor.paper_trading_enabled is True

    def test_no_live_execution_even_with_high_lifecycle_score(
        self,
        governor: RiskGovernor,
        lifecycle_engine: ResolutionLifecycleEngine,
        good_context: RiskContext,
    ):
        """Test that high lifecycle_score doesn't enable live execution"""
        market = create_mid_phase_market()
        lifecycle_engine.assess(market)

        signal = Signal(
            market_id="test",
            market_title="Test",
            market_category="crypto",
            strategy_name="test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=100,
                liquidity_score=100,
                event_score=100,
                wallet_score=100,
                lifecycle_score=100,  # Perfect lifecycle score
            ),
            raw_score=100,
        )

        decision = governor.evaluate(
            signal=signal,
            context=good_context,
            market=market,
        )

        # Should not allow live execution
        assert not decision.allows_live_execute()
