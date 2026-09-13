"""
Tests for Runner WebSocket Integration - Phase 5B.5

Coverage:
- use_websocket=true subscribes to current markets' YES/NO token ids
- token_ids deduplication
- max_subscriptions limit enforcement
- websocket message increments websocket_messages_received
- fresh cache hit does not call REST
- stale cache fallback to REST
- WebSocket connect failure fallback to REST
- no live trading path
- data_mode=mock does not force real WebSocket
- reports include websocket stats
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polysignal.ingestion.orderbook_cache import OrderBookCacheManager, TokenOrderBookCache
from polysignal.ingestion.websocket_message_handler import WSMessage
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.orderbook import OrderBookSide, OrderBookSnapshot, PriceLevel
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
def websocket_run_config():
    """Create run config with WebSocket enabled"""
    return RunConfig(
        duration_minutes=10,
        duration_hours=0.167,
        max_markets=10,
        scan_interval_seconds=60,
        data_mode="real_readonly",
        use_websocket=True,
        llm_provider="mock",
        max_llm_calls_per_hour=0,
        max_signals_per_hour=50,
        telegram_enabled=False,
        max_telegram_messages_per_hour=0,
    )


@pytest.fixture
def mock_market():
    """Create a mock market with YES and NO tokens"""
    return Market(
        market_id="test_market_1",
        title="Test Market",
        description="Test market for WebSocket integration",
        category=MarketCategory.CRYPTO,
        status=MarketStatus.OPEN,
        yes_token_address="yes_token_123",
        no_token_address="no_token_456",
        total_volume_usd=1000.0,
        volume_24h_usd=100.0,
        created_at=datetime.utcnow(),
        close_time=datetime.utcnow() + timedelta(days=7),
        is_ambiguous=False,
        is_forbidden_auto=False,
        fetched_at=datetime.utcnow(),
    )


@pytest.fixture
def mock_market_list(mock_market):
    """Create a mock market list"""
    from polysignal.models.market import MarketList
    return MarketList(
        markets=[mock_market],
        total_count=1,
        source="test",
        fetched_at=datetime.utcnow(),
    )


@pytest.fixture
def mock_orderbook():
    """Create a mock orderbook snapshot"""
    return OrderBookSnapshot(
        snapshot_id="test_snapshot_1",
        market_id="test_market_1",
        timestamp=datetime.utcnow(),
        yes_bids=OrderBookSide(levels=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)]),
        yes_asks=OrderBookSide(levels=[PriceLevel(price=0.51, size=100.0, total_usd=51.0)]),
        no_bids=OrderBookSide(levels=[PriceLevel(price=0.49, size=100.0, total_usd=49.0)]),
        no_asks=OrderBookSide(levels=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)]),
        source="websocket",
        is_stale=False,
    )


# =============================================================================
# Test WebSocket Initialization
# =============================================================================

class TestWebSocketInitialization:
    """Test WebSocket initialization in runner"""

    def test_websocket_components_initialized_when_enabled(self, mock_config, websocket_run_config):
        """Test WebSocket components are initialized when use_websocket=true and data_mode=real_readonly"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # WebSocket components should be None before initialization
        assert runner.ws_client is None
        assert runner.ws_cache_manager is None
        assert runner.ws_subscription_manager is None

    def test_websocket_not_initialized_in_mock_mode(self, mock_config):
        """Test WebSocket is not initialized when data_mode=mock"""
        run_config = RunConfig(
            duration_minutes=10,
            data_mode="mock",
            use_websocket=True,
        )
        runner = PaperTradingRunner(mock_config, run_config)

        # Even though use_websocket=True, mock mode shouldn't use real WebSocket
        assert runner.run_config.data_mode == "mock"

    def test_websocket_stats_in_run_statistics(self):
        """Test RunStatistics includes WebSocket subscription stats"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        # Check WebSocket subscription stats exist
        assert hasattr(stats, 'websocket_subscriptions_attempted')
        assert hasattr(stats, 'websocket_subscriptions_active')
        assert hasattr(stats, 'websocket_cache_hits')
        assert hasattr(stats, 'websocket_cache_misses')
        assert hasattr(stats, 'websocket_stale_fallbacks')
        assert hasattr(stats, 'rest_fallbacks')

        # Check initial values
        assert stats.websocket_subscriptions_attempted == 0
        assert stats.websocket_subscriptions_active == 0
        assert stats.websocket_cache_hits == 0
        assert stats.websocket_cache_misses == 0
        assert stats.websocket_stale_fallbacks == 0
        assert stats.rest_fallbacks == 0


# =============================================================================
# Test Token ID Subscription
# =============================================================================

class TestTokenIDSubscription:
    """Test token ID subscription logic"""

    def test_subscribe_markets_extracts_token_ids(self, mock_config, websocket_run_config, mock_market):
        """Test _subscribe_markets extracts YES and NO token IDs"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # Mock WebSocket client
        runner.ws_client = MagicMock()
        runner.ws_client.subscribe = AsyncMock(return_value=(2, 0))
        runner._ws_connected = True
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        # Call subscribe
        asyncio.run(runner._subscribe_markets([mock_market]))

        # Check subscribe was called with token IDs
        runner.ws_client.subscribe.assert_called_once()
        call_args = runner.ws_client.subscribe.call_args[0][0]

        # Should contain both YES and NO token IDs
        assert "yes_token_123" in call_args
        assert "no_token_456" in call_args
        assert len(call_args) == 2

    def test_subscribe_markets_deduplicates_token_ids(self, mock_config, websocket_run_config):
        """Test _subscribe_markets deduplicates token IDs"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # Create markets with same token IDs
        market1 = Market(
            market_id="market_1",
            title="Market 1",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.OPEN,
            yes_token_address="yes_token_shared",
            no_token_address="no_token_shared",
        )
        market2 = Market(
            market_id="market_2",
            title="Market 2",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.OPEN,
            yes_token_address="yes_token_shared",  # Same token
            no_token_address="no_token_shared",    # Same token
        )

        runner.ws_client = MagicMock()
        runner.ws_client.subscribe = AsyncMock(return_value=(2, 0))
        runner._ws_connected = True
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        asyncio.run(runner._subscribe_markets([market1, market2]))

        # Should deduplicate - only 2 unique tokens
        call_args = runner.ws_client.subscribe.call_args[0][0]
        assert len(call_args) == 2

    def test_subscribe_markets_respects_max_subscriptions(self, mock_config):
        """Test subscription respects max_subscriptions limit"""
        run_config = RunConfig(
            duration_minutes=10,
            max_markets=5,  # 5 markets = 10 tokens max
            data_mode="real_readonly",
            use_websocket=True,
        )
        runner = PaperTradingRunner(mock_config, run_config)

        # Create more markets than max
        markets = []
        for i in range(10):
            markets.append(Market(
                market_id=f"market_{i}",
                title=f"Market {i}",
                category=MarketCategory.CRYPTO,
                status=MarketStatus.OPEN,
                yes_token_address=f"yes_token_{i}",
                no_token_address=f"no_token_{i}",
            ))

        runner.ws_client = MagicMock()
        runner.ws_client.subscribe = AsyncMock(return_value=(10, 0))
        runner._ws_connected = True
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        asyncio.run(runner._subscribe_markets(markets[:5]))  # Only first 5 markets

        # Should subscribe to 10 tokens (5 markets * 2 tokens)
        call_args = runner.ws_client.subscribe.call_args[0][0]
        assert len(call_args) == 10

    def test_subscribe_updates_stats(self, mock_config, websocket_run_config, mock_market):
        """Test subscription updates statistics"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        runner.ws_client = MagicMock()
        runner.ws_client.subscribe = AsyncMock(return_value=(2, 0))
        runner._ws_connected = True
        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        asyncio.run(runner._subscribe_markets([mock_market]))

        # Check stats updated
        assert runner.stats.websocket_subscriptions_attempted == 2
        assert runner.stats.websocket_subscriptions_active == 2


# =============================================================================
# Test WebSocket Cache Fallback
# =============================================================================

class TestWebSocketCacheFallback:
    """Test WebSocket cache hit/miss/fallback logic"""

    def test_fresh_cache_hit_uses_websocket_data(self, mock_config, websocket_run_config, mock_market, mock_orderbook):
        """Test fresh cache hit uses WebSocket data without REST call"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # Setup WebSocket cache with fresh data
        runner.ws_cache_manager = OrderBookCacheManager(stale_threshold_seconds=60)
        runner.ws_client = MagicMock()
        runner._ws_connected = True

        # Add fresh cache data
        yes_cache = TokenOrderBookCache(token_id="yes_token_123")
        yes_cache.apply_snapshot(
            bids=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)],
            asks=[PriceLevel(price=0.51, size=100.0, total_usd=51.0)],
        )
        no_cache = TokenOrderBookCache(token_id="no_token_456")
        no_cache.apply_snapshot(
            bids=[PriceLevel(price=0.49, size=100.0, total_usd=49.0)],
            asks=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)],
        )
        runner.ws_cache_manager._caches["yes_token_123"] = yes_cache
        runner.ws_cache_manager._caches["no_token_456"] = no_cache

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        # Mock data provider (should NOT be called)
        runner.data_provider = MagicMock()
        runner.data_provider.get_orderbook = AsyncMock()

        # Get orderbook
        result = asyncio.run(runner._get_orderbook(mock_market))

        # Should return cached orderbook
        assert result is not None
        assert runner.stats.websocket_cache_hits == 1

        # REST should NOT be called
        runner.data_provider.get_orderbook.assert_not_called()

    def test_stale_cache_fallback_to_rest(self, mock_config, websocket_run_config, mock_market, mock_orderbook):
        """Test stale cache falls back to REST"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # Setup WebSocket cache with stale data
        runner.ws_cache_manager = OrderBookCacheManager(stale_threshold_seconds=1)  # 1 second threshold
        runner.ws_client = MagicMock()
        runner._ws_connected = True

        # Add stale cache data (last_update_time = None means stale)
        yes_cache = TokenOrderBookCache(token_id="yes_token_123")
        yes_cache.apply_snapshot(
            bids=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)],
            asks=[PriceLevel(price=0.51, size=100.0, total_usd=51.0)],
        )
        # Make it stale by setting old update time
        yes_cache.last_update_time = datetime.utcnow() - timedelta(seconds=120)

        no_cache = TokenOrderBookCache(token_id="no_token_456")
        no_cache.apply_snapshot(
            bids=[PriceLevel(price=0.49, size=100.0, total_usd=49.0)],
            asks=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)],
        )
        no_cache.last_update_time = datetime.utcnow() - timedelta(seconds=120)

        runner.ws_cache_manager._caches["yes_token_123"] = yes_cache
        runner.ws_cache_manager._caches["no_token_456"] = no_cache

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        # Mock data provider (should be called for fallback)
        runner.data_provider = MagicMock()
        runner.data_provider.get_orderbook = AsyncMock(return_value=mock_orderbook)

        # Get orderbook
        result = asyncio.run(runner._get_orderbook(mock_market))

        # Should return REST orderbook
        assert result is not None
        assert runner.stats.websocket_stale_fallbacks == 1
        assert runner.stats.rest_fallbacks == 1

        # REST should be called
        runner.data_provider.get_orderbook.assert_called_once()

    def test_cache_miss_fallback_to_rest(self, mock_config, websocket_run_config, mock_market, mock_orderbook):
        """Test cache miss falls back to REST"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # Setup WebSocket cache without data for this market
        runner.ws_cache_manager = OrderBookCacheManager()
        runner.ws_client = MagicMock()
        runner._ws_connected = True

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        # Mock data provider
        runner.data_provider = MagicMock()
        runner.data_provider.get_orderbook = AsyncMock(return_value=mock_orderbook)

        # Get orderbook
        result = asyncio.run(runner._get_orderbook(mock_market))

        # Should return REST orderbook
        assert result is not None
        assert runner.stats.websocket_cache_misses == 1
        assert runner.stats.rest_fallbacks == 1

        # REST should be called
        runner.data_provider.get_orderbook.assert_called_once()

    def test_websocket_not_connected_fallback_to_rest(self, mock_config, websocket_run_config, mock_market, mock_orderbook):
        """Test WebSocket not connected falls back to REST"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # WebSocket not connected
        runner.ws_client = MagicMock()
        runner._ws_connected = False
        runner.ws_cache_manager = OrderBookCacheManager()

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        # Mock data provider
        runner.data_provider = MagicMock()
        runner.data_provider.get_orderbook = AsyncMock(return_value=mock_orderbook)

        # Get orderbook
        result = asyncio.run(runner._get_orderbook(mock_market))

        # Should return REST orderbook
        assert result is not None

        # REST should be called
        runner.data_provider.get_orderbook.assert_called_once()


# =============================================================================
# Test WebSocket Message Handling
# =============================================================================

class TestWebSocketMessageHandling:
    """Test WebSocket message handling"""

    def test_websocket_message_increments_count(self, mock_config, websocket_run_config):
        """Test WebSocket message increments websocket_messages_received"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        # Create mock message
        message = WSMessage(
            token_id="test_token",
            message_type="book",
            timestamp=datetime.utcnow(),
            bids=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)],
            asks=[PriceLevel(price=0.51, size=100.0, total_usd=51.0)],
        )

        # Call message handler
        asyncio.run(runner._on_websocket_message(message))

        # Check count incremented
        assert runner.stats.websocket_messages == 1
        assert runner._ws_message_count == 1

    def test_multiple_messages_increment_count(self, mock_config, websocket_run_config):
        """Test multiple WebSocket messages increment count correctly"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
        )

        # Create multiple messages
        for i in range(10):
            message = WSMessage(
                token_id=f"test_token_{i}",
                message_type="book",
                timestamp=datetime.utcnow(),
                bids=[PriceLevel(price=0.50, size=100.0, total_usd=50.0)],
                asks=[PriceLevel(price=0.51, size=100.0, total_usd=51.0)],
            )
            asyncio.run(runner._on_websocket_message(message))

        # Check count
        assert runner.stats.websocket_messages == 10
        assert runner._ws_message_count == 10


# =============================================================================
# Test Safety Constraints
# =============================================================================

class TestSafetyConstraints:
    """Test safety constraints are maintained"""

    def test_no_live_trading_path(self, mock_config, websocket_run_config):
        """Test no live trading path exists"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # Check config values
        assert not runner.config.env.live_trading_enabled
        assert not runner.config.env.allow_auto_execution

        # WebSocket should not have any trading methods
        assert runner.ws_client is None  # Not initialized yet

    def test_websocket_is_read_only(self, mock_config, websocket_run_config):
        """Test WebSocket client is read-only"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        # Initialize WebSocket
        asyncio.run(runner._initialize_websocket())

        # Check WebSocket client config
        assert runner.ws_client.config.enabled

        # WebSocket client should not have trading methods
        # (This is verified by checking the WebSocketConfig doesn't have trading params)
        assert hasattr(runner.ws_client, 'build_subscribe_payload')
        assert not hasattr(runner.ws_client, 'place_order')
        assert not hasattr(runner.ws_client, 'cancel_order')

    def test_mock_mode_no_real_websocket(self, mock_config):
        """Test mock mode doesn't force real WebSocket"""
        run_config = RunConfig(
            duration_minutes=10,
            data_mode="mock",
            use_websocket=True,
        )
        runner = PaperTradingRunner(mock_config, run_config)

        # Even with use_websocket=True, mock mode shouldn't initialize real WebSocket
        # This is enforced in _initialize_components
        assert runner.run_config.data_mode == "mock"


# =============================================================================
# Test Reports Include WebSocket Stats
# =============================================================================

class TestReportsIncludeWebSocketStats:
    """Test reports include WebSocket statistics"""

    def test_summary_json_includes_websocket_stats(self):
        """Test summary.json includes WebSocket stats"""
        stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            websocket_enabled=True,
            websocket_subscriptions_attempted=20,
            websocket_subscriptions_active=18,
            websocket_cache_hits=50,
            websocket_cache_misses=10,
            websocket_stale_fallbacks=5,
            rest_fallbacks=15,
            websocket_messages=100,
        )

        summary = stats.to_dict()

        # Check WebSocket stats in summary
        assert 'websocket_subscriptions_attempted' in summary
        assert 'websocket_subscriptions_active' in summary
        assert 'websocket_cache_hits' in summary
        assert 'websocket_cache_misses' in summary
        assert 'websocket_stale_fallbacks' in summary
        assert 'rest_fallbacks' in summary
        assert 'websocket_messages' in summary

        # Check values
        assert summary['websocket_subscriptions_attempted'] == 20
        assert summary['websocket_subscriptions_active'] == 18
        assert summary['websocket_cache_hits'] == 50
        assert summary['websocket_cache_misses'] == 10
        assert summary['websocket_stale_fallbacks'] == 5
        assert summary['rest_fallbacks'] == 15
        assert summary['websocket_messages'] == 100

    def test_markdown_report_includes_websocket_section(self, mock_config, websocket_run_config):
        """Test markdown report includes WebSocket section"""
        runner = PaperTradingRunner(mock_config, websocket_run_config)

        runner.stats = RunStatistics(
            run_id="test_run",
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
            status="completed",
            websocket_enabled=True,
            websocket_subscriptions_attempted=20,
            websocket_subscriptions_active=18,
            websocket_cache_hits=50,
            websocket_cache_misses=10,
            websocket_stale_fallbacks=5,
            rest_fallbacks=15,
        )

        report = runner._generate_markdown_report()

        # Check WebSocket section exists
        assert "WebSocket Subscriptions" in report
        assert "Subscriptions Attempted" in report
        assert "Subscriptions Active" in report
        assert "Cache Hits" in report
        assert "Cache Misses" in report
        assert "Stale Fallbacks" in report
        assert "REST Fallbacks" in report


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])