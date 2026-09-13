"""
Tests for Market Microstructure Engine
"""

import pytest

from polysignal.engines.market_microstructure import (
    MarketMicrostructureEngine,
)
from tests.fixtures.orderbooks import (
    create_mispricing_orderbook,
    create_mock_orderbook,
    create_thin_depth_orderbook,
    create_wide_spread_orderbook,
)


class TestMarketMicrostructureEngine:
    """Test Market Microstructure Engine"""

    @pytest.fixture
    def engine(self) -> MarketMicrostructureEngine:
        """Create a microstructure engine"""
        return MarketMicrostructureEngine()

    def test_analyze_normal_orderbook(self, engine: MarketMicrostructureEngine):
        """Test analyzing a normal orderbook"""
        orderbook = create_mock_orderbook(
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )

        result = engine.analyze_snapshot(orderbook)

        # Should have metrics
        assert result.spread_pct > 0
        assert result.total_depth_usd > 0
        assert 0 <= result.imbalance_ratio <= 1

        # Should have scores
        assert 0 <= result.microstructure_score <= 100
        assert 0 <= result.liquidity_score <= 100

    def test_analyze_mispricing_orderbook(self, engine: MarketMicrostructureEngine):
        """Test detecting mispricing"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)

        result = engine.analyze_snapshot(orderbook)

        # Should detect mispricing
        assert result.is_mispriced is True
        assert result.combined_ask < 0.985

        # Should have higher score
        assert result.microstructure_score > 50

    def test_analyze_wide_spread(self, engine: MarketMicrostructureEngine):
        """Test analyzing wide spread"""
        orderbook = create_wide_spread_orderbook(spread_pct=0.10)

        result = engine.analyze_snapshot(orderbook)

        # Should have lower liquidity score
        assert result.liquidity_score < 70
        assert result.spread_pct > 0.05

    def test_analyze_thin_depth(self, engine: MarketMicrostructureEngine):
        """Test analyzing thin depth"""
        orderbook = create_thin_depth_orderbook(depth_usd=10)

        result = engine.analyze_snapshot(orderbook)

        # Should have lower liquidity score
        assert result.liquidity_score < 70
        assert result.total_depth_usd < 50

    def test_combined_ask_calculation(self, engine: MarketMicrostructureEngine):
        """Test combined ask calculation"""
        orderbook = create_mock_orderbook(
            yes_ask=0.48,
            no_ask=0.50,
        )

        result = engine.analyze_snapshot(orderbook)

        # Combined ask should be sum
        expected_combined = 0.48 + 0.50
        assert abs(result.combined_ask - expected_combined) < 0.01

    def test_imbalance_calculation(self, engine: MarketMicrostructureEngine):
        """Test imbalance calculation"""
        # Create orderbook with bid-heavy imbalance
        orderbook = create_mock_orderbook(
            yes_bid=0.45,
            yes_ask=0.47,
            yes_depth_usd=200,  # More bid depth
            no_depth_usd=50,
        )

        result = engine.analyze_snapshot(orderbook)

        # Imbalance should reflect bid-heavy
        # Note: imbalance is calculated from YES side
        assert 0 <= result.imbalance_ratio <= 1

    def test_get_component_scores(self, engine: MarketMicrostructureEngine):
        """Test getting component scores"""
        orderbook = create_mispricing_orderbook(combined_ask=0.975)

        scores = engine.get_component_scores(orderbook)

        # Should have all scores
        assert scores.microstructure_score > 0
        assert scores.liquidity_score > 0
        assert scores.event_score == 50  # Default neutral
        assert scores.wallet_score == 50  # Default neutral
        assert scores.lifecycle_score == 50  # Default neutral

    def test_ultra_fast_path_no_llm(self, engine: MarketMicrostructureEngine):
        """Test that engine does not call LLM (ultra-fast path)"""
        # Engine should only do in-memory calculations
        # No external calls
        orderbook = create_mock_orderbook()

        # This should complete quickly without any external calls
        result = engine.analyze_snapshot(orderbook)

        assert result is not None

    def test_result_to_dict(self, engine: MarketMicrostructureEngine):
        """Test result serialization"""
        orderbook = create_mock_orderbook()
        result = engine.analyze_snapshot(orderbook)

        result_dict = result.to_dict()

        assert "spread_pct" in result_dict
        assert "total_depth_usd" in result_dict
        assert "combined_ask" in result_dict
        assert "is_mispriced" in result_dict
        assert "timestamp" in result_dict

    def test_analyze_update(self, engine: MarketMicrostructureEngine):
        """Test analyzing lightweight update"""
        from polysignal.models.orderbook import OrderBookUpdate

        update = OrderBookUpdate(
            market_id="test",
            yes_best_ask=0.48,
            no_best_ask=0.50,
        )

        result = engine.analyze_update(update)

        # Should have combined ask
        assert result.combined_ask is not None
        assert abs(result.combined_ask - 0.98) < 0.01

    def test_thresholds_configurable(self):
        """Test that thresholds are configurable"""
        custom_engine = MarketMicrostructureEngine(
            spread_good_threshold=0.01,
            spread_bad_threshold=0.03,
            depth_good_threshold=500,
            depth_bad_threshold=25,
            combined_ask_threshold=0.990,
        )

        orderbook = create_mispricing_orderbook(combined_ask=0.985)

        result = custom_engine.analyze_snapshot(orderbook)

        # With lower threshold, should still detect
        assert result.is_mispriced is True
