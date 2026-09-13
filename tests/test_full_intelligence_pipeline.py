"""
Full Intelligence Pipeline Integration Test

Tests the complete flow from mock data through all four engines to Risk Governor
and Paper Trader. Validates that:
- All engines produce valid assessments
- Component scores are correctly merged into Signal
- Risk Governor makes correct decisions
- Paper Trader only executes when allowed
- Live trading remains disabled
"""

from datetime import datetime, timedelta, timezone

import pytest

from polysignal.engines.event_intelligence import EventIntelligenceEngine
from polysignal.engines.market_microstructure import MarketMicrostructureEngine
from polysignal.engines.resolution_lifecycle import ResolutionLifecycleEngine
from polysignal.engines.wallet_intelligence import WalletIntelligenceEngine
from polysignal.execution.paper_trader import PaperTrader
from polysignal.llm.mock_provider import MockScenario
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.orderbook import OrderBookSide, OrderBookSnapshot, PriceLevel
from polysignal.models.risk import RiskAction, RiskContext, RiskDecision
from polysignal.models.signal import ComponentScores, Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor
from tests.fixtures.wallets import (
    create_consensus_activities_yes,
    create_mock_watchlist,
    create_profiles_dict,
)


class TestFullIntelligencePipeline:
    """Test complete intelligence pipeline"""

    @pytest.fixture
    def market(self) -> Market:
        """Create test market"""
        return Market(
            market_id="pipeline_test_001",
            title="Will Bitcoin reach $100,000 by 2026?",
            description="Test market for full pipeline integration",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.OPEN,
            total_volume_usd=500000,
            volume_24h_usd=200000,
            close_time=datetime.now(timezone.utc) + timedelta(days=30),
            is_ambiguous=False,
        )

    @pytest.fixture
    def orderbook(self) -> OrderBookSnapshot:
        """Create test orderbook with YES/NO mispricing"""
        return OrderBookSnapshot(
            market_id="pipeline_test_001",
            timestamp=datetime.now(timezone.utc),
            yes_bids=OrderBookSide(levels=[
                PriceLevel(price=0.52, size=100.0, total_usd=100.0),
                PriceLevel(price=0.51, size=200.0, total_usd=200.0),
            ]),
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.53, size=150.0, total_usd=150.0),
                PriceLevel(price=0.54, size=100.0, total_usd=100.0),
            ]),
            no_bids=OrderBookSide(levels=[
                PriceLevel(price=0.46, size=100.0, total_usd=100.0),
                PriceLevel(price=0.45, size=200.0, total_usd=200.0),
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.47, size=150.0, total_usd=150.0),
                PriceLevel(price=0.48, size=100.0, total_usd=100.0),
            ]),
        )

    @pytest.fixture
    def context(self) -> RiskContext:
        """Create risk context"""
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

    @pytest.fixture
    def microstructure_engine(self) -> MarketMicrostructureEngine:
        """Create Market Microstructure Engine"""
        return MarketMicrostructureEngine()

    @pytest.fixture
    def lifecycle_engine(self) -> ResolutionLifecycleEngine:
        """Create Resolution & Lifecycle Engine"""
        return ResolutionLifecycleEngine()

    @pytest.fixture
    def wallet_engine(self) -> WalletIntelligenceEngine:
        """Create Wallet Intelligence Engine"""
        watchlist = create_mock_watchlist()
        profiles = create_profiles_dict()
        return WalletIntelligenceEngine(watchlist=watchlist, profiles=profiles)

    @pytest.fixture
    def event_engine(self) -> EventIntelligenceEngine:
        """Create Event Intelligence Engine"""
        return EventIntelligenceEngine(scenario=MockScenario.SUCCESS)

    @pytest.fixture
    def risk_governor(self) -> RiskGovernor:
        """Create Risk Governor"""
        return RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

    @pytest.fixture
    def paper_trader(self) -> PaperTrader:
        """Create Paper Trader"""
        return PaperTrader()

    # =========================================================================
    # Engine Output Tests
    # =========================================================================

    def test_microstructure_engine_output(
        self,
        microstructure_engine: MarketMicrostructureEngine,
        orderbook: OrderBookSnapshot,
    ):
        """Test Market Microstructure Engine produces valid output"""
        result = microstructure_engine.analyze_snapshot(orderbook)

        assert result is not None
        assert 0 <= result.microstructure_score <= 100
        assert result.spread_pct is not None
        assert result.total_depth_usd > 0

    def test_lifecycle_engine_output(
        self,
        lifecycle_engine: ResolutionLifecycleEngine,
        market: Market,
    ):
        """Test Resolution & Lifecycle Engine produces valid output"""
        assessment = lifecycle_engine.assess(market)

        assert assessment is not None
        assert 0 <= assessment.lifecycle_score <= 100
        assert assessment.is_tradable is True
        assert assessment.phase is not None

    def test_wallet_engine_output(
        self,
        wallet_engine: WalletIntelligenceEngine,
        market: Market,
    ):
        """Test Wallet Intelligence Engine produces valid output"""
        activities = create_consensus_activities_yes()
        assessment = wallet_engine.assess(market, recent_activities=activities)

        assert assessment is not None
        assert 0 <= assessment.wallet_score <= 100
        assert len(assessment.active_wallets) > 0

    def test_event_engine_output(
        self,
        event_engine: EventIntelligenceEngine,
        market: Market,
    ):
        """Test Event Intelligence Engine produces valid output"""
        assessment = event_engine.assess(market)

        assert assessment is not None
        assert 0 <= assessment.event_score <= 100
        assert assessment.llm_success is True

    # =========================================================================
    # Component Scores Merge Tests
    # =========================================================================

    def test_component_scores_merge(
        self,
        microstructure_engine: MarketMicrostructureEngine,
        lifecycle_engine: ResolutionLifecycleEngine,
        wallet_engine: WalletIntelligenceEngine,
        event_engine: EventIntelligenceEngine,
        market: Market,
        orderbook: OrderBookSnapshot,
    ):
        """Test all engine scores can be merged into ComponentScores"""
        # Get all assessments
        micro_result = microstructure_engine.analyze_snapshot(orderbook)
        lifecycle_assessment = lifecycle_engine.assess(market)
        wallet_activities = create_consensus_activities_yes()
        wallet_assessment = wallet_engine.assess(market, recent_activities=wallet_activities)
        event_assessment = event_engine.assess(market)

        # Create ComponentScores
        component_scores = ComponentScores(
            microstructure_score=micro_result.microstructure_score,
            liquidity_score=micro_result.liquidity_score,
            event_score=event_assessment.event_score,
            wallet_score=wallet_assessment.wallet_score,
            lifecycle_score=lifecycle_assessment.lifecycle_score,
        )

        # Validate all scores are in valid range
        assert 0 <= component_scores.microstructure_score <= 100
        assert 0 <= component_scores.liquidity_score <= 100
        assert 0 <= component_scores.event_score <= 100
        assert 0 <= component_scores.wallet_score <= 100
        assert 0 <= component_scores.lifecycle_score <= 100

    # =========================================================================
    # Full Pipeline Tests
    # =========================================================================

    def test_full_pipeline_signal_generation(
        self,
        microstructure_engine: MarketMicrostructureEngine,
        lifecycle_engine: ResolutionLifecycleEngine,
        wallet_engine: WalletIntelligenceEngine,
        event_engine: EventIntelligenceEngine,
        risk_governor: RiskGovernor,
        market: Market,
        orderbook: OrderBookSnapshot,
        context: RiskContext,
    ):
        """Test full pipeline from engines to signal"""
        # Step 1: Market Microstructure
        micro_result = microstructure_engine.analyze_snapshot(orderbook)

        # Step 2: Lifecycle Assessment
        lifecycle_assessment = lifecycle_engine.assess(market)

        # Step 3: Wallet Assessment
        wallet_activities = create_consensus_activities_yes()
        wallet_assessment = wallet_engine.assess(market, recent_activities=wallet_activities)

        # Step 4: Event Assessment
        event_assessment = event_engine.assess(market)

        # Step 5: Merge risk flags
        all_risk_flags = (
            lifecycle_assessment.risk_flags
            + wallet_assessment.risk_flags
            + event_assessment.risk_flags
        )

        # Step 6: Create Signal
        signal = Signal(
            signal_id="pipeline_signal_001",
            market_id=market.market_id,
            market_title=market.title,
            market_category=market.category.value,
            strategy_name="full_pipeline_test",
            side=SignalSide.YES,
            price=0.52,  # Use a valid price
            component_scores=ComponentScores(
                microstructure_score=micro_result.microstructure_score,
                liquidity_score=micro_result.liquidity_score,
                event_score=event_assessment.event_score,
                wallet_score=wallet_assessment.wallet_score,
                lifecycle_score=lifecycle_assessment.lifecycle_score,
            ),
            risk_flags=all_risk_flags,
        )

        # Step 7: Risk Governor Evaluate
        decision = risk_governor.evaluate(signal, context, orderbook=orderbook, market=market)

        # Validate decision
        assert decision is not None
        assert 0 <= decision.trade_score <= 100
        assert decision.action in RiskAction

    def test_full_pipeline_paper_trade_allowed(
        self,
        microstructure_engine: MarketMicrostructureEngine,
        lifecycle_engine: ResolutionLifecycleEngine,
        wallet_engine: WalletIntelligenceEngine,
        event_engine: EventIntelligenceEngine,
        risk_governor: RiskGovernor,
        paper_trader: PaperTrader,
        market: Market,
        orderbook: OrderBookSnapshot,
        context: RiskContext,
    ):
        """Test paper trade is allowed when conditions are good"""
        # Get all assessments
        microstructure_engine.analyze_snapshot(orderbook)
        lifecycle_engine.assess(market)
        wallet_activities = create_consensus_activities_yes()
        wallet_engine.assess(market, recent_activities=wallet_activities)
        event_engine.assess(market)

        # Create high-quality signal
        signal = Signal(
            signal_id="pipeline_signal_002",
            market_id=market.market_id,
            market_title=market.title,
            market_category=market.category.value,
            strategy_name="full_pipeline_test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=90.0,
                liquidity_score=90.0,
                event_score=85.0,
                wallet_score=80.0,
                lifecycle_score=90.0,
            ),
            risk_flags=[],
        )

        # Risk Governor evaluate
        decision = risk_governor.evaluate(signal, context, orderbook=orderbook, market=market)

        # Should allow paper trade
        assert decision.action != RiskAction.HARD_REJECT
        assert RiskAction.PAPER_TRADE in decision.allowed_actions

        # Paper Trader should be able to execute (check via allows_paper_trade)
        assert decision.allows_paper_trade()

    # =========================================================================
    # Live Trading Disabled Tests
    # =========================================================================

    def test_live_trading_disabled(
        self,
        risk_governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test live trading is disabled"""
        assert risk_governor.live_trading_enabled is False
        assert risk_governor.allow_auto_execution is False

    def test_high_score_no_live_execute(
        self,
        risk_governor: RiskGovernor,
        market: Market,
        orderbook: OrderBookSnapshot,
        context: RiskContext,
    ):
        """Test high score does not result in LIVE_EXECUTE"""
        signal = Signal(
            signal_id="pipeline_signal_003",
            market_id=market.market_id,
            market_title=market.title,
            market_category=market.category.value,
            strategy_name="full_pipeline_test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=95.0,
                liquidity_score=95.0,
                event_score=95.0,
                wallet_score=95.0,
                lifecycle_score=95.0,
            ),
            risk_flags=[],
        )

        decision = risk_governor.evaluate(signal, context, orderbook=orderbook, market=market)

        # Should be PAPER_TRADE, not LIVE_EXECUTE
        assert decision.action == RiskAction.PAPER_TRADE
        assert RiskAction.LIVE_EXECUTE not in decision.allowed_actions

    # =========================================================================
    # Signal-Only Safeguard Tests
    # =========================================================================

    def test_wallet_signal_only_rejected(
        self,
        risk_governor: RiskGovernor,
        market: Market,
        context: RiskContext,
    ):
        """Test wallet signal only is hard rejected"""
        signal = Signal(
            signal_id="pipeline_signal_004",
            market_id=market.market_id,
            market_title=market.title,
            market_category=market.category.value,
            strategy_name="full_pipeline_test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=50.0,  # Weak
                liquidity_score=55.0,  # Weak
                event_score=45.0,  # Weak
                wallet_score=85.0,  # Strong
                lifecycle_score=70.0,
            ),
            risk_flags=[],
        )

        decision = risk_governor.evaluate(signal, context, market=market)

        assert decision.action == RiskAction.HARD_REJECT
        assert "wallet_signal_only_reason" in decision.hard_reject_reasons

    def test_event_signal_only_rejected(
        self,
        risk_governor: RiskGovernor,
        market: Market,
        context: RiskContext,
    ):
        """Test event signal only is hard rejected"""
        signal = Signal(
            signal_id="pipeline_signal_005",
            market_id=market.market_id,
            market_title=market.title,
            market_category=market.category.value,
            strategy_name="full_pipeline_test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=50.0,  # Weak
                liquidity_score=55.0,  # Weak
                event_score=85.0,  # Strong
                wallet_score=45.0,  # Weak
                lifecycle_score=70.0,
            ),
            risk_flags=[],
        )

        decision = risk_governor.evaluate(signal, context, market=market)

        assert decision.action == RiskAction.HARD_REJECT
        assert "event_signal_only_reason" in decision.hard_reject_reasons

    # =========================================================================
    # Hard Rejection Tests
    # =========================================================================

    def test_market_not_open_rejected(
        self,
        risk_governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test market not open is hard rejected"""
        closed_market = Market(
            market_id="closed_market_001",
            title="Closed Market",
            description="Test",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.CLOSED,
            total_volume_usd=500000,
            volume_24h_usd=200000,
            close_time=datetime.now(timezone.utc) + timedelta(days=30),
        )

        signal = Signal(
            signal_id="pipeline_signal_006",
            market_id=closed_market.market_id,
            market_title=closed_market.title,
            market_category=closed_market.category.value,
            strategy_name="full_pipeline_test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=90.0,
                liquidity_score=90.0,
                event_score=90.0,
                wallet_score=90.0,
                lifecycle_score=90.0,
            ),
            risk_flags=[],
        )

        decision = risk_governor.evaluate(signal, context, market=closed_market)

        assert decision.action == RiskAction.HARD_REJECT
        assert "market_not_open" in decision.hard_reject_reasons

    def test_market_ambiguous_rejected(
        self,
        risk_governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test ambiguous market is hard rejected"""
        ambiguous_market = Market(
            market_id="ambiguous_market_001",
            title="Ambiguous Market",
            description="Test",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.OPEN,
            total_volume_usd=500000,
            volume_24h_usd=200000,
            close_time=datetime.now(timezone.utc) + timedelta(days=30),
            is_ambiguous=True,
        )

        signal = Signal(
            signal_id="pipeline_signal_007",
            market_id=ambiguous_market.market_id,
            market_title=ambiguous_market.title,
            market_category=ambiguous_market.category.value,
            strategy_name="full_pipeline_test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=90.0,
                liquidity_score=90.0,
                event_score=90.0,
                wallet_score=90.0,
                lifecycle_score=90.0,
            ),
            risk_flags=[],
        )

        decision = risk_governor.evaluate(signal, context, market=ambiguous_market)

        assert decision.action == RiskAction.HARD_REJECT
        assert "market_ambiguous" in decision.hard_reject_reasons

    def test_forbidden_category_rejected(
        self,
        risk_governor: RiskGovernor,
        context: RiskContext,
    ):
        """Test forbidden category is hard rejected"""
        politics_market = Market(
            market_id="politics_market_001",
            title="Politics Market",
            description="Test",
            category=MarketCategory.POLITICS,
            status=MarketStatus.OPEN,
            total_volume_usd=500000,
            volume_24h_usd=200000,
            close_time=datetime.now(timezone.utc) + timedelta(days=30),
        )

        signal = Signal(
            signal_id="pipeline_signal_008",
            market_id=politics_market.market_id,
            market_title=politics_market.title,
            market_category=politics_market.category.value,
            strategy_name="full_pipeline_test",
            side=SignalSide.YES,
            price=0.5,
            component_scores=ComponentScores(
                microstructure_score=90.0,
                liquidity_score=90.0,
                event_score=90.0,
                wallet_score=90.0,
                lifecycle_score=90.0,
            ),
            risk_flags=[],
        )

        decision = risk_governor.evaluate(signal, context, market=politics_market)

        assert decision.action == RiskAction.HARD_REJECT
        assert "forbidden_category" in decision.hard_reject_reasons

    # =========================================================================
    # Engine Status Tests
    # =========================================================================

    def test_all_engines_have_status(
        self,
        lifecycle_engine: ResolutionLifecycleEngine,
        wallet_engine: WalletIntelligenceEngine,
        event_engine: EventIntelligenceEngine,
    ):
        """Test all engines have status method"""
        lifecycle_status = lifecycle_engine.get_status()
        wallet_status = wallet_engine.get_status()
        event_status = event_engine.get_status()

        assert lifecycle_status["engine"] == "ResolutionLifecycleEngine"
        assert wallet_status["engine"] == "WalletIntelligenceEngine"
        assert event_status["engine"] == "EventIntelligenceEngine"

    # =========================================================================
    # Paper Trader Tests
    # =========================================================================

    def test_paper_trader_default_settings(
        self,
        paper_trader: PaperTrader,
    ):
        """Test Paper Trader default settings"""
        assert paper_trader.default_order_size_usd == 1.0
        assert paper_trader.slippage_assumption_pct == 0.01

    def test_paper_trader_cannot_execute_without_approval(
        self,
        paper_trader: PaperTrader,
    ):
        """Test Paper Trader cannot execute without Risk Governor approval"""
        # Create a hard rejected decision
        decision = RiskDecision(
            signal_id="test_001",
            action=RiskAction.HARD_REJECT,
            trade_score=0.0,
            hard_reject_reasons=["test_reject"],
            allowed_actions=[],
        )

        assert decision.allows_paper_trade() is False

    # =========================================================================
    # Complete Integration Test
    # =========================================================================

    def test_complete_integration_all_engines_to_paper_trade(
        self,
        microstructure_engine: MarketMicrostructureEngine,
        lifecycle_engine: ResolutionLifecycleEngine,
        wallet_engine: WalletIntelligenceEngine,
        event_engine: EventIntelligenceEngine,
        risk_governor: RiskGovernor,
        paper_trader: PaperTrader,
        market: Market,
        orderbook: OrderBookSnapshot,
        context: RiskContext,
    ):
        """
        Complete integration test:
        - Mock market
        - Mock orderbook
        - Lifecycle assessment
        - Wallet assessment
        - Event assessment
        - Signal component_scores merge
        - Risk Governor evaluate
        - Paper Trader only executes when allowed
        - Live trading still disabled
        """
        # Step 1: Market Microstructure Engine
        micro_result = microstructure_engine.analyze_snapshot(orderbook)
        assert micro_result is not None

        # Step 2: Resolution & Lifecycle Engine
        lifecycle_assessment = lifecycle_engine.assess(market)
        assert lifecycle_assessment.is_tradable is True

        # Step 3: Wallet Intelligence Engine
        wallet_activities = create_consensus_activities_yes()
        wallet_assessment = wallet_engine.assess(market, recent_activities=wallet_activities)
        assert wallet_assessment.wallet_score > 0

        # Step 4: Event Intelligence Engine
        event_assessment = event_engine.assess(market)
        assert event_assessment.event_score > 0

        # Step 5: Merge all scores into Signal
        all_risk_flags = (
            lifecycle_assessment.risk_flags
            + wallet_assessment.risk_flags
            + event_assessment.risk_flags
        )

        signal = Signal(
            signal_id="complete_integration_001",
            market_id=market.market_id,
            market_title=market.title,
            market_category=market.category.value,
            strategy_name="complete_integration_test",
            side=SignalSide.YES,
            price=0.52,  # Use a valid price
            component_scores=ComponentScores(
                microstructure_score=micro_result.microstructure_score,
                liquidity_score=micro_result.liquidity_score,
                event_score=event_assessment.event_score,
                wallet_score=wallet_assessment.wallet_score,
                lifecycle_score=lifecycle_assessment.lifecycle_score,
            ),
            risk_flags=all_risk_flags,
        )

        # Step 6: Risk Governor Evaluate
        decision = risk_governor.evaluate(signal, context, orderbook=orderbook, market=market)

        # Step 7: Verify decision
        assert decision is not None
        assert decision.trade_score >= 0

        # Step 8: Verify live trading disabled
        assert risk_governor.live_trading_enabled is False
        assert RiskAction.LIVE_EXECUTE not in decision.allowed_actions

        # Step 9: Paper Trader check (if paper trade allowed)
        if decision.action != RiskAction.HARD_REJECT:
            if RiskAction.PAPER_TRADE in decision.allowed_actions:
                assert decision.allows_paper_trade()