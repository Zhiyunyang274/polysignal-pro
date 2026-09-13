"""
Integration Tests - Risk Governor + Wallet Intelligence Engine

Tests the integration between Risk Governor and Wallet Intelligence Engine,
particularly the dual safeguard for wallet_signal_only detection.
"""

from datetime import datetime, timedelta

import pytest

from polysignal.engines.wallet_intelligence import WalletIntelligenceEngine
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.risk import RiskAction, RiskContext
from polysignal.models.signal import ComponentScores, Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor
from tests.fixtures.wallets import (
    create_consensus_activities_yes,
    create_mock_watchlist,
    create_profiles_dict,
    create_wallet_market,
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


class TestRiskGovernorWalletIntegration:
    """Test Risk Governor + Wallet Intelligence integration"""

    @pytest.fixture
    def governor(self) -> RiskGovernor:
        """Create Risk Governor with default settings"""
        return RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

    @pytest.fixture
    def wallet_engine(self) -> WalletIntelligenceEngine:
        """Create Wallet Intelligence Engine"""
        watchlist = create_mock_watchlist()
        profiles = create_profiles_dict()
        return WalletIntelligenceEngine(watchlist=watchlist, profiles=profiles)

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
    # Wallet Score in Trade Score Tests
    # =========================================================================

    def test_wallet_score_included_in_trade_score(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test wallet_score is included in trade_score calculation"""
        signal = create_test_signal(wallet_score=80.0)

        decision = governor.evaluate(signal, context)

        # trade_score should include wallet_score * 0.15
        # Expected: 70*0.30 + 70*0.20 + 70*0.20 + 80*0.15 + 70*0.15 = 71.5
        assert decision.trade_score > 0
        assert decision.component_scores["wallet"] == 80.0

    def test_wallet_score_weight_in_trade_score(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test wallet_score has 15% weight in trade_score"""
        # Create two signals with different wallet scores
        signal1 = create_test_signal(signal_id="test_001", wallet_score=70.0)
        signal2 = create_test_signal(signal_id="test_002", wallet_score=80.0)

        decision1 = governor.evaluate(signal1, context)
        decision2 = governor.evaluate(signal2, context)

        # Difference should be 10 * 0.15 = 1.5
        score_diff = decision2.trade_score - decision1.trade_score
        assert abs(score_diff - 1.5) < 0.1

    # =========================================================================
    # Copy Risk Penalty Tests
    # =========================================================================

    def test_copy_risk_penalty_applied(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test copy_risk_penalty is applied to trade_score"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["copy_risk_high"],
        )

        decision = governor.evaluate(signal, context)

        # Should have copy_risk_penalty
        assert decision.copy_risk_penalty == 15.0
        assert decision.trade_score < 80.0  # Penalized

    def test_copy_risk_medium_penalty(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test medium copy risk penalty"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["copy_risk_medium"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.copy_risk_penalty == 8.0

    def test_copy_risk_low_penalty(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test low copy risk penalty"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["copy_risk_low"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.copy_risk_penalty == 3.0

    # =========================================================================
    # Chase Risk Penalty Tests
    # =========================================================================

    def test_chase_risk_penalty_applied(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test chase_risk_penalty is applied"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["chase_risk_high"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.chase_risk_penalty == 10.0

    # =========================================================================
    # Timing Risk Penalty Tests
    # =========================================================================

    def test_timing_risk_penalty_applied(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test timing_risk_penalty is applied"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["timing_risk_high"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.timing_risk_penalty == 5.0

    # =========================================================================
    # Wallet Signal Only - Dual Safeguard Tests
    # =========================================================================

    def test_wallet_signal_only_hard_reject_from_flags(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test wallet_signal_only hard reject from signal.risk_flags"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["wallet_signal_only"],
        )

        decision = governor.evaluate(signal, context)

        assert decision.action == RiskAction.HARD_REJECT
        assert "wallet_signal_only_reason" in decision.hard_reject_reasons

    def test_wallet_signal_only_hard_reject_direct_check(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test wallet_signal_only hard reject from direct component_scores check"""
        # wallet_score >= 80, other scores < 60
        signal = create_test_signal(
            microstructure_score=50.0,  # < 60
            liquidity_score=55.0,  # < 60
            event_score=45.0,  # < 60
            wallet_score=85.0,  # >= 80
            lifecycle_score=70.0,
            risk_flags=[],
        )

        decision = governor.evaluate(signal, context)

        # Should be hard rejected due to direct check
        assert decision.action == RiskAction.HARD_REJECT
        assert "wallet_signal_only_reason" in decision.hard_reject_reasons

    def test_wallet_signal_not_rejected_with_strong_microstructure(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test not rejected when microstructure is strong"""
        # wallet_score >= 80, but microstructure >= 60
        signal = create_test_signal(
            microstructure_score=65.0,  # >= 60
            liquidity_score=55.0,
            event_score=45.0,
            wallet_score=85.0,
            lifecycle_score=70.0,
            risk_flags=[],
        )

        decision = governor.evaluate(signal, context)

        # Should NOT be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        assert "wallet_signal_only_reason" not in decision.hard_reject_reasons

    def test_wallet_signal_not_rejected_with_weak_wallet(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test not rejected when wallet score is weak"""
        # wallet_score < 80
        signal = create_test_signal(
            microstructure_score=50.0,
            liquidity_score=55.0,
            event_score=45.0,
            wallet_score=75.0,  # < 80
            lifecycle_score=70.0,
            risk_flags=[],
        )

        decision = governor.evaluate(signal, context)

        # Should NOT be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        assert "wallet_signal_only_reason" not in decision.hard_reject_reasons

    def test_dual_safeguard_both_trigger(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test dual safeguard - both flag and direct check trigger"""
        # Both signal.risk_flags has wallet_signal_only AND component_scores match
        signal = create_test_signal(
            microstructure_score=50.0,
            liquidity_score=55.0,
            event_score=45.0,
            wallet_score=85.0,
            lifecycle_score=70.0,
            risk_flags=["wallet_signal_only"],
        )

        decision = governor.evaluate(signal, context)

        # Should have exactly one wallet_signal_only_reason (not duplicated)
        assert decision.action == RiskAction.HARD_REJECT
        assert decision.hard_reject_reasons.count("wallet_signal_only_reason") == 1

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
    # Wallet Consensus Boost Tests
    # =========================================================================

    def test_wallet_consensus_in_assessment(
        self,
        wallet_engine: WalletIntelligenceEngine,
    ):
        """Test wallet consensus is calculated"""
        market = create_wallet_market()
        activities = create_consensus_activities_yes()

        assessment = wallet_engine.assess(market, recent_activities=activities)

        # Should have consensus
        assert assessment.consensus is not None
        assert assessment.consensus.direction == "yes"
        assert assessment.wallet_consensus_score > 0

    def test_wallet_consensus_boosts_signal(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test wallet consensus can boost overall signal"""
        # Signal with high wallet score
        signal = create_test_signal(wallet_score=90.0)

        decision = governor.evaluate(signal, context)

        # Should have positive trade_score
        assert decision.trade_score > 70.0

    # =========================================================================
    # Integration with Market Tests
    # =========================================================================

    def test_market_not_open_hard_reject(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test market not open results in hard reject"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
        )

        # Create closed market
        market = Market(
            market_id="market_001",
            title="Test Market",
            description="Test",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.CLOSED,
            total_volume_usd=500000,
            volume_24h_usd=200000,
            close_time=datetime.utcnow() + timedelta(days=30),
        )

        decision = governor.evaluate(signal, context, market=market)

        assert decision.action == RiskAction.HARD_REJECT
        assert "market_not_open" in decision.hard_reject_reasons

    def test_market_ambiguous_hard_reject(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test ambiguous market results in hard reject"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
        )

        # Create ambiguous market
        market = Market(
            market_id="market_001",
            title="Test Market",
            description="Test",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.OPEN,
            total_volume_usd=500000,
            volume_24h_usd=200000,
            close_time=datetime.utcnow() + timedelta(days=30),
            is_ambiguous=True,
        )

        decision = governor.evaluate(signal, context, market=market)

        assert decision.action == RiskAction.HARD_REJECT
        assert "market_ambiguous" in decision.hard_reject_reasons

    # =========================================================================
    # Full Integration Tests
    # =========================================================================

    def test_full_integration_wallet_engine_to_risk_governor(
        self,
        wallet_engine: WalletIntelligenceEngine,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test full integration from wallet engine to risk governor"""
        # Step 1: Get wallet assessment
        market = create_wallet_market()
        activities = create_consensus_activities_yes()
        assessment = wallet_engine.assess(market, recent_activities=activities)

        # Step 2: Create signal with wallet scores
        signal = create_test_signal(
            signal_id="test_001",
            market_id=market.market_id,
            market_title=market.title,
            market_category="crypto",
            strategy_name="wallet_consensus",
            wallet_score=assessment.wallet_score,
            risk_flags=assessment.risk_flags,
        )

        # Step 3: Evaluate through risk governor
        decision = governor.evaluate(signal, context, market=market)

        # Should not be hard rejected
        assert decision.action != RiskAction.HARD_REJECT
        assert decision.trade_score > 0

    def test_full_integration_with_copy_risk(
        self,
        governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test full integration with copy risk"""
        signal = create_test_signal(
            microstructure_score=80.0,
            liquidity_score=80.0,
            event_score=80.0,
            wallet_score=80.0,
            lifecycle_score=80.0,
            risk_flags=["copy_risk_high", "chase_risk_high"],
        )

        decision = governor.evaluate(signal, context)

        # Should have multiple penalties
        assert decision.copy_risk_penalty == 15.0
        assert decision.chase_risk_penalty == 10.0
        # Total penalty: 25
        assert decision.trade_score < 80.0 - 20.0
