"""
Tests for Orderbook Best Price Extraction - Phase 5A.7

Validates that best_bid and best_ask are correctly extracted from orderbook levels,
regardless of the order in which the API returns them.

Key findings from investigation:
- Polymarket CLOB API returns asks in DESCENDING order (highest price first)
- Polymarket CLOB API returns bids in DESCENDING order (highest price first)
- Current code uses levels[0] which incorrectly takes highest ask instead of lowest ask
- This causes combined_ask to be ~1.98 instead of potentially ~1.0

Correct logic:
- best_bid = max(bid.price) = highest buy price
- best_ask = min(ask.price) = lowest sell price
"""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polysignal.models.orderbook import (
    PriceLevel,
    OrderBookSide,
    OrderBookSnapshot,
)


# =============================================================================
# Test PriceLevel
# =============================================================================

class TestPriceLevel:
    """Test PriceLevel model"""

    def test_price_level_creation(self):
        """Test basic price level creation"""
        level = PriceLevel(price=0.5, size=100.0, total_usd=50.0)
        assert level.price == 0.5
        assert level.size == 100.0
        assert level.total_usd == 50.0

    def test_price_level_validation(self):
        """Test price level validation"""
        # Price must be 0-1
        with pytest.raises(Exception):
            PriceLevel(price=1.5, size=100.0, total_usd=150.0)

        with pytest.raises(Exception):
            PriceLevel(price=-0.1, size=100.0, total_usd=-10.0)


# =============================================================================
# Test OrderBookSide Best Price Extraction
# =============================================================================

class TestOrderBookSideBestPrice:
    """Test OrderBookSide best price extraction"""

    def test_empty_side_has_no_best(self):
        """Test empty orderbook side has no best price"""
        side = OrderBookSide(levels=[])
        side.calculate_best_bid()
        assert side.best_price is None
        assert side.best_size is None

    def test_single_level_best_price(self):
        """Test single level orderbook side"""
        side = OrderBookSide(levels=[
            PriceLevel(price=0.5, size=100.0, total_usd=50.0)
        ])
        side.calculate_best_bid()
        # For a single level, best_price should be that level's price
        assert side.best_price == 0.5
        assert side.best_size == 100.0

    def test_bids_ascending_order(self):
        """Test bids in ascending order (lowest first) - should take highest"""
        # Bids: buy orders - best bid is highest price
        side = OrderBookSide(levels=[
            PriceLevel(price=0.45, size=100.0, total_usd=45.0),
            PriceLevel(price=0.50, size=200.0, total_usd=100.0),
            PriceLevel(price=0.55, size=150.0, total_usd=82.5),
        ])
        side.calculate_best_bid()
        # Best bid should be highest price (0.55)
        assert side.best_price == 0.55
        assert side.best_size == 150.0

    def test_bids_descending_order(self):
        """Test bids in descending order (highest first) - should take first"""
        # Bids: buy orders - best bid is highest price
        side = OrderBookSide(levels=[
            PriceLevel(price=0.55, size=150.0, total_usd=82.5),
            PriceLevel(price=0.50, size=200.0, total_usd=100.0),
            PriceLevel(price=0.45, size=100.0, total_usd=45.0),
        ])
        side.calculate_best_bid()
        # Best bid should be highest price (0.55) - first element in descending order
        assert side.best_price == 0.55
        assert side.best_size == 150.0

    def test_asks_ascending_order(self):
        """Test asks in ascending order (lowest first) - should take first"""
        # Asks: sell orders - best ask is lowest price
        side = OrderBookSide(levels=[
            PriceLevel(price=0.45, size=100.0, total_usd=45.0),
            PriceLevel(price=0.50, size=200.0, total_usd=100.0),
            PriceLevel(price=0.55, size=150.0, total_usd=82.5),
        ])
        side.calculate_best_ask()
        # Best ask should be lowest price (0.45) - first element in ascending order
        assert side.best_price == 0.45
        assert side.best_size == 100.0

    def test_asks_descending_order(self):
        """Test asks in descending order (highest first) - should take last"""
        # Asks: sell orders - best ask is lowest price
        # This is the CRITICAL test - Polymarket returns asks in descending order
        side = OrderBookSide(levels=[
            PriceLevel(price=0.55, size=150.0, total_usd=82.5),
            PriceLevel(price=0.50, size=200.0, total_usd=100.0),
            PriceLevel(price=0.45, size=100.0, total_usd=45.0),
        ])
        side.calculate_best_ask()
        # Best ask should be lowest price (0.45) - LAST element in descending order
        # BUG: Current code takes first element (0.55) instead of last (0.45)
        assert side.best_price == 0.45, "Best ask should be lowest price, not highest"
        assert side.best_size == 100.0

    def test_asks_unordered(self):
        """Test asks in unordered format - should still find lowest"""
        # Asks: sell orders - best ask is lowest price
        side = OrderBookSide(levels=[
            PriceLevel(price=0.52, size=100.0, total_usd=52.0),
            PriceLevel(price=0.45, size=200.0, total_usd=90.0),
            PriceLevel(price=0.58, size=150.0, total_usd=87.0),
            PriceLevel(price=0.48, size=300.0, total_usd=144.0),
        ])
        side.calculate_best_ask()
        # Best ask should be lowest price (0.45)
        assert side.best_price == 0.45
        assert side.best_size == 200.0

    def test_bids_unordered(self):
        """Test bids in unordered format - should still find highest"""
        # Bids: buy orders - best bid is highest price
        side = OrderBookSide(levels=[
            PriceLevel(price=0.52, size=100.0, total_usd=52.0),
            PriceLevel(price=0.58, size=200.0, total_usd=116.0),
            PriceLevel(price=0.45, size=150.0, total_usd=67.5),
            PriceLevel(price=0.55, size=300.0, total_usd=165.0),
        ])
        side.calculate_best_bid()
        # Best bid should be highest price (0.58)
        assert side.best_price == 0.58
        assert side.best_size == 200.0


# =============================================================================
# Test OrderBookSnapshot Combined Ask
# =============================================================================

class TestOrderBookSnapshotCombinedAsk:
    """Test OrderBookSnapshot combined_ask calculation"""

    def test_combined_ask_normal_market(self):
        """Test combined_ask in a normal market (should be ~2.0)"""
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.99, size=100.0, total_usd=99.0),
                PriceLevel(price=0.98, size=100.0, total_usd=98.0),
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.99, size=100.0, total_usd=99.0),
                PriceLevel(price=0.98, size=100.0, total_usd=98.0),
            ]),
        )
        snapshot.calculate_metrics()
        # With descending order, best_ask should be 0.98 (lowest), not 0.99 (highest)
        # combined_ask = 0.98 + 0.98 = 1.96
        assert snapshot.combined_ask == 1.96

    def test_combined_ask_mispriced_market(self):
        """Test combined_ask in a mispriced market (should be < 1.0)"""
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.55, size=100.0, total_usd=55.0),
                PriceLevel(price=0.50, size=100.0, total_usd=50.0),
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.45, size=100.0, total_usd=45.0),
                PriceLevel(price=0.40, size=100.0, total_usd=40.0),
            ]),
        )
        snapshot.calculate_metrics()
        # With descending order:
        # YES best_ask = 0.50 (lowest), NO best_ask = 0.40 (lowest)
        # combined_ask = 0.50 + 0.40 = 0.90
        assert snapshot.combined_ask == 0.90

    def test_combined_ask_polymarket_format(self):
        """Test combined_ask with Polymarket CLOB API format (descending asks)"""
        # This simulates the actual Polymarket CLOB API response format
        # Asks are returned in descending order (highest first)
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.99, size=100.0, total_usd=99.0),  # Highest ask
                PriceLevel(price=0.98, size=100.0, total_usd=98.0),
                PriceLevel(price=0.97, size=100.0, total_usd=97.0),
                PriceLevel(price=0.96, size=100.0, total_usd=96.0),
                PriceLevel(price=0.95, size=100.0, total_usd=95.0),  # Lowest ask
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.99, size=100.0, total_usd=99.0),  # Highest ask
                PriceLevel(price=0.98, size=100.0, total_usd=98.0),
                PriceLevel(price=0.97, size=100.0, total_usd=97.0),
                PriceLevel(price=0.96, size=100.0, total_usd=96.0),
                PriceLevel(price=0.95, size=100.0, total_usd=95.0),  # Lowest ask
            ]),
        )
        snapshot.calculate_metrics()
        # Best ask should be 0.95 (lowest), not 0.99 (highest)
        # combined_ask = 0.95 + 0.95 = 1.90
        assert snapshot.combined_ask == 1.90, \
            f"Expected combined_ask=1.90 (using lowest asks), got {snapshot.combined_ask}"

    def test_combined_ask_near_arbitrage(self):
        """Test combined_ask near arbitrage opportunity"""
        # YES at 0.52, NO at 0.45 -> combined = 0.97 (arbitrage opportunity)
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.55, size=100.0, total_usd=55.0),
                PriceLevel(price=0.52, size=100.0, total_usd=52.0),  # Lowest ask
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.50, size=100.0, total_usd=50.0),
                PriceLevel(price=0.45, size=100.0, total_usd=45.0),  # Lowest ask
            ]),
        )
        snapshot.calculate_metrics()
        # combined_ask = 0.52 + 0.45 = 0.97
        assert snapshot.combined_ask == 0.97

    def test_combined_ask_missing_yes_asks(self):
        """Test combined_ask when YES asks are missing"""
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_asks=OrderBookSide(levels=[]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.50, size=100.0, total_usd=50.0),
            ]),
        )
        snapshot.calculate_metrics()
        assert snapshot.combined_ask is None

    def test_combined_ask_missing_no_asks(self):
        """Test combined_ask when NO asks are missing"""
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.50, size=100.0, total_usd=50.0),
            ]),
            no_asks=OrderBookSide(levels=[]),
        )
        snapshot.calculate_metrics()
        assert snapshot.combined_ask is None

    def test_combined_ask_both_missing(self):
        """Test combined_ask when both asks are missing"""
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_asks=OrderBookSide(levels=[]),
            no_asks=OrderBookSide(levels=[]),
        )
        snapshot.calculate_metrics()
        assert snapshot.combined_ask is None


# =============================================================================
# Test Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases for best price extraction"""

    def test_very_small_spread(self):
        """Test orderbook with very small spread"""
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_bids=OrderBookSide(levels=[
                PriceLevel(price=0.499, size=100.0, total_usd=49.9),
            ]),
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.501, size=100.0, total_usd=50.1),
            ]),
        )
        snapshot.calculate_metrics()
        assert snapshot.spread_yes == pytest.approx(0.002, abs=0.0001)
        assert snapshot.spread_pct_yes == pytest.approx(0.004, abs=0.001)

    def test_total_depth_calculation(self):
        """Test total depth calculation"""
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_bids=OrderBookSide(levels=[
                PriceLevel(price=0.45, size=100.0, total_usd=45.0),
                PriceLevel(price=0.40, size=200.0, total_usd=80.0),
            ]),
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.55, size=100.0, total_usd=55.0),
                PriceLevel(price=0.60, size=200.0, total_usd=120.0),
            ]),
            no_bids=OrderBookSide(levels=[
                PriceLevel(price=0.35, size=100.0, total_usd=35.0),
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.65, size=100.0, total_usd=65.0),
            ]),
        )
        snapshot.calculate_metrics()
        # YES depth = 45 + 80 + 55 + 120 = 300
        # NO depth = 35 + 65 = 100
        # Total = 400
        assert snapshot.get_yes_depth_usd() == 300.0
        assert snapshot.get_no_depth_usd() == 100.0
        assert snapshot.get_total_depth_usd() == 400.0

    def test_single_price_level(self):
        """Test orderbook with single price level on each side"""
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_bids=OrderBookSide(levels=[
                PriceLevel(price=0.40, size=100.0, total_usd=40.0),
            ]),
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.60, size=100.0, total_usd=60.0),
            ]),
            no_bids=OrderBookSide(levels=[
                PriceLevel(price=0.30, size=100.0, total_usd=30.0),
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.70, size=100.0, total_usd=70.0),
            ]),
        )
        snapshot.calculate_metrics()
        assert snapshot.yes_bids.best_price == 0.40
        assert snapshot.yes_asks.best_price == 0.60
        assert snapshot.no_bids.best_price == 0.30
        assert snapshot.no_asks.best_price == 0.70


# =============================================================================
# Test Real-World Scenarios
# =============================================================================

class TestRealWorldScenarios:
    """Test real-world orderbook scenarios"""

    def test_polymarket_orderbook_format(self):
        """Test with actual Polymarket CLOB API orderbook format"""
        # Polymarket returns asks in descending order (highest first)
        # and bids in descending order (highest first)
        snapshot = OrderBookSnapshot(
            market_id="540816",
            yes_bids=OrderBookSide(levels=[
                PriceLevel(price=0.05, size=1000.0, total_usd=50.0),
                PriceLevel(price=0.04, size=2000.0, total_usd=80.0),
                PriceLevel(price=0.03, size=3000.0, total_usd=90.0),
            ]),
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.99, size=100.0, total_usd=99.0),  # Highest
                PriceLevel(price=0.98, size=200.0, total_usd=196.0),
                PriceLevel(price=0.97, size=300.0, total_usd=291.0),
                PriceLevel(price=0.96, size=400.0, total_usd=384.0),
                PriceLevel(price=0.95, size=500.0, total_usd=475.0),  # Lowest
            ]),
            no_bids=OrderBookSide(levels=[
                PriceLevel(price=0.05, size=1000.0, total_usd=50.0),
                PriceLevel(price=0.04, size=2000.0, total_usd=80.0),
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.99, size=100.0, total_usd=99.0),  # Highest
                PriceLevel(price=0.98, size=200.0, total_usd=196.0),
                PriceLevel(price=0.97, size=300.0, total_usd=291.0),
                PriceLevel(price=0.96, size=400.0, total_usd=384.0),
                PriceLevel(price=0.95, size=500.0, total_usd=475.0),  # Lowest
            ]),
        )
        snapshot.calculate_metrics()

        # Best bid should be highest (0.05)
        assert snapshot.yes_bids.best_price == 0.05
        assert snapshot.no_bids.best_price == 0.05

        # Best ask should be lowest (0.95), NOT highest (0.99)
        assert snapshot.yes_asks.best_price == 0.95, \
            f"YES best_ask should be 0.95 (lowest), got {snapshot.yes_asks.best_price}"
        assert snapshot.no_asks.best_price == 0.95, \
            f"NO best_ask should be 0.95 (lowest), got {snapshot.no_asks.best_price}"

        # Combined ask should be 1.90, NOT 1.98
        assert snapshot.combined_ask == 1.90, \
            f"combined_ask should be 1.90, got {snapshot.combined_ask}"

    def test_mispricing_detection_scenario(self):
        """Test scenario where mispricing should be detected"""
        # YES at 0.48, NO at 0.48 -> combined = 0.96 (mispricing!)
        snapshot = OrderBookSnapshot(
            market_id="test_market",
            yes_asks=OrderBookSide(levels=[
                PriceLevel(price=0.55, size=100.0, total_usd=55.0),
                PriceLevel(price=0.50, size=100.0, total_usd=50.0),
                PriceLevel(price=0.48, size=100.0, total_usd=48.0),  # Lowest ask
            ]),
            no_asks=OrderBookSide(levels=[
                PriceLevel(price=0.55, size=100.0, total_usd=55.0),
                PriceLevel(price=0.50, size=100.0, total_usd=50.0),
                PriceLevel(price=0.48, size=100.0, total_usd=48.0),  # Lowest ask
            ]),
        )
        snapshot.calculate_metrics()
        # combined_ask = 0.48 + 0.48 = 0.96 (below 0.985 threshold)
        assert snapshot.combined_ask == 0.96
        assert snapshot.combined_ask < 0.985, "Should detect mispricing opportunity"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
