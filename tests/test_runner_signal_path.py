"""
Tests for Runner Signal Path Hardening - Phase 5B.6

Coverage:
- _process_signal does not await RiskGovernor.evaluate
- _process_signal correctly constructs RiskContext
- RiskGovernor.evaluate receives real orderbook, not None
- RiskAction enum branches correctly tracked
- PAPER_TRADE action increments signals_paper_trade
- HARD_REJECT action increments signals_hard_reject
- ALERT action increments signals_alert
- IGNORE action increments signals_ignored
- YesNoMispricingStrategy is called in runner
- Combined mispricing signal side is BOTH
- DataConverter.clob_orderbook_to_update correctly uses max bid / min ask
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polysignal.ingestion.api_types import CLOBOrderbook, CLOBPriceLevel
from polysignal.ingestion.data_converter import DataConverter
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.orderbook import OrderBookSide, OrderBookSnapshot, PriceLevel
from polysignal.models.risk import RiskAction, RiskDecision
from polysignal.models.signal import ComponentScores, Signal, SignalSide
from polysignal.risk.risk_governor import RiskGovernor
from polysignal.strategies.base import StrategyContext
from polysignal.strategies.yes_no_mispricing import YesNoMispricingStrategy
from scripts.run_paper import (
    PaperTradingRunner,
    RunConfig,
    RunStatistics,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_config():
    """Create mock config with safe defaults"""
    config = MagicMock()
    config.env = MagicMock()
    config.env.live_trading_enabled = False
    config.env.allow_auto_execution = False
    config.env.paper_trading_enabled = True
    return config


@pytest.fixture
def run_config():
    """Create run config"""
    return RunConfig(
        duration_minutes=5,
        data_mode="real_readonly",
        use_websocket=False,
    )


@pytest.fixture
def mock_market():
    """Create a mock market"""
    return Market(
        market_id="test_market_1",
        title="Test Market",
        description="Test market",
        category=MarketCategory.CRYPTO,
        status=MarketStatus.OPEN,
        yes_token_address="yes_token_123",
        no_token_address="no_token_456",
        total_volume_usd=100000.0,
        volume_24h_usd=1000.0,
        created_at=datetime.utcnow(),
        close_time=datetime.utcnow() + timedelta(days=7),
        is_ambiguous=False,
        is_forbidden_auto=False,
        fetched_at=datetime.utcnow(),
    )


@pytest.fixture
def mock_orderbook():
    """Create a mock orderbook with mispricing"""
    return OrderBookSnapshot(
        snapshot_id="test_snapshot",
        market_id="test_market_1",
        timestamp=datetime.utcnow(),
        yes_bids=OrderBookSide(levels=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)]),
        yes_asks=OrderBookSide(levels=[PriceLevel(price=0.49, size=100.0, total_usd=49.0)]),
        no_bids=OrderBookSide(levels=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)]),
        no_asks=OrderBookSide(levels=[PriceLevel(price=0.49, size=100.0, total_usd=49.0)]),
        source="clob",
        is_stale=False,
    )


# =============================================================================
# Test _process_signal Does Not Await RiskGovernor.evaluate
# =============================================================================

class TestProcessSignalNoAwait:
    """Test that _process_signal does not await RiskGovernor.evaluate"""

    def test_risk_governor_evaluate_is_sync(self, mock_config, run_config):
        """Test that RiskGovernor.evaluate is a synchronous method"""
        from polysignal.risk.risk_governor import RiskGovernor

        governor = RiskGovernor()
        # Check that evaluate is not a coroutine function
        import inspect
        assert not inspect.iscoroutinefunction(governor.evaluate)
        assert callable(governor.evaluate)

    def test_process_signal_calls_evaluate_sync(self, mock_config, run_config, mock_market, mock_orderbook):
        """Test that _process_signal calls evaluate synchronously (no await)"""
        runner = PaperTradingRunner(mock_config, run_config)

        # Setup runner state
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
        )
        runner._ws_connected = True
        runner.db = MagicMock()
        runner.db.save_signal = AsyncMock()
        runner.db.save_risk_decision = AsyncMock()

        # Initialize risk_governor (normally done in _initialize_components)
        runner.risk_governor = RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

        # Create a signal
        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=85.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        # Mock _execute_paper_trade to avoid its complexity
        runner._execute_paper_trade = AsyncMock()

        # Run _process_signal
        asyncio.run(runner._process_signal(signal, mock_market, mock_orderbook))

        # Verify signal was saved (indicates evaluate was called synchronously)
        runner.db.save_signal.assert_called_once()


# =============================================================================
# Test RiskContext Construction
# =============================================================================

class TestRiskContextConstruction:
    """Test that _process_signal correctly constructs RiskContext"""

    def test_risk_context_has_correct_fields(self, mock_config, run_config, mock_market, mock_orderbook):
        """Test RiskContext is constructed with correct fields"""
        runner = PaperTradingRunner(mock_config, run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
        )
        runner._ws_connected = True
        runner.db = MagicMock()
        runner.db.save_signal = AsyncMock()
        runner.db.save_risk_decision = AsyncMock()

        # Initialize risk_governor (normally done in _initialize_components)
        runner.risk_governor = RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=85.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        # Patch RiskGovernor.evaluate to capture context
        captured_context = None

        def capture_evaluate(signal, context, orderbook=None, market=None):
            nonlocal captured_context
            captured_context = context
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.IGNORE,
                trade_score=50.0,
            )

        runner.risk_governor.evaluate = capture_evaluate

        asyncio.run(runner._process_signal(signal, mock_market, mock_orderbook))

        # Verify context was constructed correctly
        assert captured_context is not None
        assert not captured_context.live_trading_enabled
        assert not captured_context.allow_auto_execution
        assert captured_context.api_healthy
        assert captured_context.websocket_healthy
        assert not captured_context.price_stale  # orderbook.is_stale = False
        assert captured_context.market_tradable
        assert not captured_context.market_ambiguous
        assert not captured_context.market_forbidden

    def test_risk_context_with_stale_orderbook(self, mock_config, run_config, mock_market):
        """Test RiskContext correctly indicates stale price"""
        runner = PaperTradingRunner(mock_config, run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
        )
        runner._ws_connected = True
        runner.db = MagicMock()
        runner.db.save_signal = AsyncMock()
        runner.db.save_risk_decision = AsyncMock()

        # Initialize risk_governor (normally done in _initialize_components)
        runner.risk_governor = RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

        # Create stale orderbook
        stale_orderbook = OrderBookSnapshot(
            snapshot_id="stale_snapshot",
            market_id="test_market_1",
            timestamp=datetime.utcnow(),
            is_stale=True,
        )

        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=85.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        captured_context = None

        def capture_evaluate(signal, context, orderbook=None, market=None):
            nonlocal captured_context
            captured_context = context
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.IGNORE,
                trade_score=50.0,
            )

        runner.risk_governor.evaluate = capture_evaluate

        asyncio.run(runner._process_signal(signal, mock_market, stale_orderbook))

        assert captured_context.price_stale


# =============================================================================
# Test RiskGovernor Receives Real Orderbook
# =============================================================================

class TestRiskGovernorReceivesOrderbook:
    """Test that RiskGovernor.evaluate receives real orderbook"""

    def test_evaluate_receives_orderbook(self, mock_config, run_config, mock_market, mock_orderbook):
        """Test RiskGovernor.evaluate receives the orderbook parameter"""
        runner = PaperTradingRunner(mock_config, run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
        )
        runner._ws_connected = True
        runner.db = MagicMock()
        runner.db.save_signal = AsyncMock()
        runner.db.save_risk_decision = AsyncMock()

        # Initialize risk_governor (normally done in _initialize_components)
        runner.risk_governor = RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=85.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        captured_orderbook = None

        def capture_evaluate(signal, context, orderbook=None, market=None):
            nonlocal captured_orderbook
            captured_orderbook = orderbook
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.IGNORE,
                trade_score=50.0,
            )

        runner.risk_governor.evaluate = capture_evaluate

        asyncio.run(runner._process_signal(signal, mock_market, mock_orderbook))

        # Verify orderbook was passed
        assert captured_orderbook is not None
        assert captured_orderbook.market_id == "test_market_1"


# =============================================================================
# Test RiskAction Enum Branches
# =============================================================================

class TestRiskActionEnumBranches:
    """Test that RiskAction enum branches are correctly tracked"""

    def _create_runner_with_mock(self, mock_config, run_config):
        runner = PaperTradingRunner(mock_config, run_config)
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
        )
        runner._ws_connected = True
        runner.db = MagicMock()
        runner.db.save_signal = AsyncMock()
        runner.db.save_risk_decision = AsyncMock()
        runner._execute_paper_trade = AsyncMock()

        # Initialize risk_governor (normally done in _initialize_components)
        runner.risk_governor = RiskGovernor(
            live_trading_enabled=False,
            allow_auto_execution=False,
            paper_trading_enabled=True,
        )

        return runner

    def test_ignore_action_increments_signals_ignored(self, mock_config, run_config, mock_market, mock_orderbook):
        """Test IGNORE action increments signals_ignored"""
        runner = self._create_runner_with_mock(mock_config, run_config)

        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=50.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        def mock_evaluate(signal, context, orderbook=None, market=None):
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.IGNORE,
                trade_score=50.0,
            )

        runner.risk_governor.evaluate = mock_evaluate

        asyncio.run(runner._process_signal(signal, mock_market, mock_orderbook))

        assert runner.stats.signals_ignored == 1

    def test_log_only_action_increments_signals_log_only(self, mock_config, run_config, mock_market, mock_orderbook):
        """Test LOG_ONLY action increments signals_log_only"""
        runner = self._create_runner_with_mock(mock_config, run_config)

        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=75.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        def mock_evaluate(signal, context, orderbook=None, market=None):
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.LOG_ONLY,
                trade_score=75.0,
            )

        runner.risk_governor.evaluate = mock_evaluate

        asyncio.run(runner._process_signal(signal, mock_market, mock_orderbook))

        assert runner.stats.signals_log_only == 1

    def test_alert_action_increments_signals_alert(self, mock_config, run_config, mock_market, mock_orderbook):
        """Test ALERT action increments signals_alert"""
        runner = self._create_runner_with_mock(mock_config, run_config)

        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=85.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        def mock_evaluate(signal, context, orderbook=None, market=None):
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.ALERT,
                trade_score=85.0,
            )

        runner.risk_governor.evaluate = mock_evaluate

        asyncio.run(runner._process_signal(signal, mock_market, mock_orderbook))

        assert runner.stats.signals_alert == 1

    def test_paper_trade_action_increments_signals_paper_trade(self, mock_config, run_config, mock_market, mock_orderbook):
        """Test PAPER_TRADE action increments signals_paper_trade"""
        runner = self._create_runner_with_mock(mock_config, run_config)

        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=92.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        def mock_evaluate(signal, context, orderbook=None, market=None):
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.PAPER_TRADE,
                trade_score=92.0,
            )

        runner.risk_governor.evaluate = mock_evaluate

        asyncio.run(runner._process_signal(signal, mock_market, mock_orderbook))

        assert runner.stats.signals_paper_trade == 1
        runner._execute_paper_trade.assert_called_once()

    def test_hard_reject_action_increments_signals_hard_reject(self, mock_config, run_config, mock_market, mock_orderbook):
        """Test HARD_REJECT action increments signals_hard_reject"""
        runner = self._create_runner_with_mock(mock_config, run_config)

        signal = Signal(
            signal_id="sig_test",
            timestamp=datetime.utcnow(),
            market_id="test_market_1",
            market_title="Test Market",
            market_category="crypto",
            strategy_name="yes_no_mispricing",
            side=SignalSide.BOTH,
            price=0.98,
            raw_score=95.0,
            component_scores=ComponentScores(),
            risk_flags=[],
            reason="Test signal",
            path_type="ultra_fast",
            data_source="clob",
        )

        def mock_evaluate(signal, context, orderbook=None, market=None):
            return RiskDecision(
                signal_id=signal.signal_id,
                action=RiskAction.HARD_REJECT,
                trade_score=0.0,
                hard_reject_reasons=["live_trading_disabled"],
            )

        runner.risk_governor.evaluate = mock_evaluate

        asyncio.run(runner._process_signal(signal, mock_market, mock_orderbook))

        assert runner.stats.signals_hard_reject == 1
        assert "live_trading_disabled" in runner.stats.hard_reject_reasons


# =============================================================================
# Test YesNoMispricingStrategy Usage
# =============================================================================

class TestYesNoMispricingStrategyUsage:
    """Test that YesNoMispricingStrategy is used in runner"""

    def test_strategy_produces_both_side_for_mispricing(self, mock_market):
        """Test YesNoMispricingStrategy produces SignalSide.BOTH for mispricing"""
        strategy = YesNoMispricingStrategy(
            combined_ask_threshold=0.985,
        )

        # Create orderbook with mispricing (combined_ask < 0.985)
        orderbook = OrderBookSnapshot(
            snapshot_id="test_snapshot",
            market_id="test_market_1",
            timestamp=datetime.utcnow(),
            yes_bids=OrderBookSide(levels=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)]),
            yes_asks=OrderBookSide(levels=[PriceLevel(price=0.48, size=100.0, total_usd=48.0)]),
            no_bids=OrderBookSide(levels=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)]),
            no_asks=OrderBookSide(levels=[PriceLevel(price=0.48, size=100.0, total_usd=48.0)]),
            source="clob",
        )
        orderbook.calculate_metrics()

        context = StrategyContext(
            market=mock_market,
            orderbook=orderbook,
            component_scores=ComponentScores(),
        )

        signal = strategy.compute_signal(context)

        # Signal should be produced with BOTH side
        assert signal is not None
        assert signal.side == SignalSide.BOTH
        assert signal.strategy_name == "yes_no_mispricing"

    def test_strategy_returns_none_for_no_mispricing(self, mock_market):
        """Test YesNoMispricingStrategy returns None when no mispricing"""
        strategy = YesNoMispricingStrategy()

        # Create orderbook without mispricing (combined_ask ~ 1.0)
        orderbook = OrderBookSnapshot(
            snapshot_id="test_snapshot",
            market_id="test_market_1",
            timestamp=datetime.utcnow(),
            yes_bids=OrderBookSide(levels=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)]),
            yes_asks=OrderBookSide(levels=[PriceLevel(price=0.51, size=100.0, total_usd=51.0)]),
            no_bids=OrderBookSide(levels=[PriceLevel(price=0.49, size=100.0, total_usd=49.0)]),
            no_asks=OrderBookSide(levels=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)]),
            source="clob",
        )
        orderbook.calculate_metrics()

        context = StrategyContext(
            market=mock_market,
            orderbook=orderbook,
            component_scores=ComponentScores(),
        )

        signal = strategy.compute_signal(context)

        # No signal should be produced
        assert signal is None


# =============================================================================
# Test DataConverter.clob_orderbook_to_update
# =============================================================================

class TestDataConverterBestPrice:
    """Test DataConverter.clob_orderbook_to_update uses max bid / min ask"""

    def test_best_bid_is_max_price(self):
        """Test best bid is highest price regardless of order"""
        # Bids in descending order (highest first)
        clob_orderbook = CLOBOrderbook(
            bids=[
                CLOBPriceLevel(price="0.55", size="100"),
                CLOBPriceLevel(price="0.50", size="200"),
                CLOBPriceLevel(price="0.45", size="300"),
            ],
            asks=[
                CLOBPriceLevel(price="0.60", size="100"),
            ],
        )

        update = DataConverter.clob_orderbook_to_update(clob_orderbook, "market_1", is_yes=True)

        # Best bid should be 0.55 (highest)
        assert update.yes_best_bid == 0.55

    def test_best_bid_is_max_price_ascending(self):
        """Test best bid is highest price in ascending order"""
        # Bids in ascending order (lowest first)
        clob_orderbook = CLOBOrderbook(
            bids=[
                CLOBPriceLevel(price="0.45", size="300"),
                CLOBPriceLevel(price="0.50", size="200"),
                CLOBPriceLevel(price="0.55", size="100"),
            ],
            asks=[
                CLOBPriceLevel(price="0.60", size="100"),
            ],
        )

        update = DataConverter.clob_orderbook_to_update(clob_orderbook, "market_1", is_yes=True)

        # Best bid should be 0.55 (highest)
        assert update.yes_best_bid == 0.55

    def test_best_ask_is_min_price_descending(self):
        """Test best ask is lowest price in descending order (Polymarket format)"""
        # Asks in descending order (highest first) - Polymarket CLOB API format
        clob_orderbook = CLOBOrderbook(
            bids=[
                CLOBPriceLevel(price="0.50", size="100"),
            ],
            asks=[
                CLOBPriceLevel(price="0.60", size="100"),
                CLOBPriceLevel(price="0.55", size="200"),
                CLOBPriceLevel(price="0.50", size="300"),
            ],
        )

        update = DataConverter.clob_orderbook_to_update(clob_orderbook, "market_1", is_yes=True)

        # Best ask should be 0.50 (lowest)
        assert update.yes_best_ask == 0.50

    def test_best_ask_is_min_price_ascending(self):
        """Test best ask is lowest price in ascending order"""
        # Asks in ascending order (lowest first)
        clob_orderbook = CLOBOrderbook(
            bids=[
                CLOBPriceLevel(price="0.50", size="100"),
            ],
            asks=[
                CLOBPriceLevel(price="0.50", size="300"),
                CLOBPriceLevel(price="0.55", size="200"),
                CLOBPriceLevel(price="0.60", size="100"),
            ],
        )

        update = DataConverter.clob_orderbook_to_update(clob_orderbook, "market_1", is_yes=True)

        # Best ask should be 0.50 (lowest)
        assert update.yes_best_ask == 0.50

    def test_best_ask_is_min_price_unordered(self):
        """Test best ask is lowest price in unordered format"""
        # Asks in random order
        clob_orderbook = CLOBOrderbook(
            bids=[
                CLOBPriceLevel(price="0.50", size="100"),
            ],
            asks=[
                CLOBPriceLevel(price="0.55", size="200"),
                CLOBPriceLevel(price="0.50", size="300"),
                CLOBPriceLevel(price="0.60", size="100"),
                CLOBPriceLevel(price="0.52", size="150"),
            ],
        )

        update = DataConverter.clob_orderbook_to_update(clob_orderbook, "market_1", is_yes=True)

        # Best ask should be 0.50 (lowest)
        assert update.yes_best_ask == 0.50


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])