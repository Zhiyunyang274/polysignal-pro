"""
Tests for OrderBook Cache
"""

import pytest
from datetime import datetime, timedelta

from polysignal.ingestion.orderbook_cache import (
    TokenOrderBookCache,
    OrderBookCacheManager,
)
from polysignal.models.orderbook import PriceLevel


class TestTokenOrderBookCache:
    """Test token orderbook cache"""

    def test_initial_state(self):
        """Test initial state"""
        cache = TokenOrderBookCache(token_id="test_token")
        assert cache.token_id == "test_token"
        assert len(cache.bids) == 0
        assert len(cache.asks) == 0
        assert cache.last_update_time is None
        assert cache.update_count == 0

    def test_apply_snapshot(self):
        """Test applying snapshot"""
        cache = TokenOrderBookCache(token_id="test_token")

        bids = [
            PriceLevel(price=0.6, size=100, total_usd=60),
            PriceLevel(price=0.5, size=200, total_usd=100),
        ]
        asks = [
            PriceLevel(price=0.7, size=150, total_usd=105),
            PriceLevel(price=0.8, size=100, total_usd=80),
        ]

        cache.apply_snapshot(bids, asks)

        assert len(cache.bids) == 2
        assert len(cache.asks) == 2
        assert cache.bids[0.6] == 100
        assert cache.asks[0.7] == 150
        assert cache.last_update_time is not None
        assert cache.update_count == 1

    def test_apply_update_add(self):
        """Test applying update to add levels"""
        cache = TokenOrderBookCache(token_id="test_token")

        # Add new levels
        cache.apply_update(
            bid_updates=[(0.5, 100), (0.4, 200)],
            ask_updates=[(0.6, 150)],
        )

        assert len(cache.bids) == 2
        assert len(cache.asks) == 1
        assert cache.bids[0.5] == 100
        assert cache.asks[0.6] == 150

    def test_apply_update_modify(self):
        """Test applying update to modify levels"""
        cache = TokenOrderBookCache(token_id="test_token")

        # Initial state
        cache.apply_update(bid_updates=[(0.5, 100)])
        assert cache.bids[0.5] == 100

        # Modify
        cache.apply_update(bid_updates=[(0.5, 200)])
        assert cache.bids[0.5] == 200

    def test_apply_update_remove(self):
        """Test applying update to remove levels (size=0)"""
        cache = TokenOrderBookCache(token_id="test_token")

        # Initial state
        cache.apply_update(bid_updates=[(0.5, 100), (0.4, 200)])
        assert len(cache.bids) == 2

        # Remove one
        cache.apply_update(bid_updates=[(0.5, 0)])
        assert len(cache.bids) == 1
        assert 0.5 not in cache.bids

    def test_get_bid_side(self):
        """Test getting bid side as OrderBookSide"""
        cache = TokenOrderBookCache(token_id="test_token")
        cache.apply_update(bid_updates=[(0.5, 100), (0.6, 200)])

        side = cache.get_bid_side()

        # Bids should be sorted descending
        assert len(side.levels) == 2
        assert side.levels[0].price == 0.6
        assert side.levels[1].price == 0.5
        assert side.best_price == 0.6

    def test_get_ask_side(self):
        """Test getting ask side as OrderBookSide"""
        cache = TokenOrderBookCache(token_id="test_token")
        cache.apply_update(ask_updates=[(0.7, 100), (0.6, 200)])

        side = cache.get_ask_side()

        # Asks should be sorted ascending
        assert len(side.levels) == 2
        assert side.levels[0].price == 0.6
        assert side.levels[1].price == 0.7
        assert side.best_price == 0.6

    def test_is_stale_true(self):
        """Test stale detection - stale"""
        cache = TokenOrderBookCache(token_id="test_token")
        cache.apply_update(bid_updates=[(0.5, 100)])

        # Manually set old timestamp
        cache.last_update_time = datetime.utcnow() - timedelta(seconds=120)

        assert cache.is_stale(threshold_seconds=60) is True

    def test_is_stale_false(self):
        """Test stale detection - not stale"""
        cache = TokenOrderBookCache(token_id="test_token")
        cache.apply_update(bid_updates=[(0.5, 100)])

        assert cache.is_stale(threshold_seconds=60) is False

    def test_is_stale_no_update(self):
        """Test stale detection - no update"""
        cache = TokenOrderBookCache(token_id="test_token")
        assert cache.is_stale() is True

    def test_clear(self):
        """Test clearing cache"""
        cache = TokenOrderBookCache(token_id="test_token")
        cache.apply_update(bid_updates=[(0.5, 100)])

        cache.clear()

        assert len(cache.bids) == 0
        assert len(cache.asks) == 0
        assert cache.last_update_time is None


class TestOrderBookCacheManager:
    """Test orderbook cache manager"""

    def test_get_or_create_cache(self):
        """Test get or create cache"""
        manager = OrderBookCacheManager()

        cache1 = manager.get_or_create_cache("token_1")
        assert cache1.token_id == "token_1"

        cache2 = manager.get_or_create_cache("token_1")
        assert cache2 is cache1  # Same instance

    def test_apply_snapshot(self):
        """Test applying snapshot"""
        manager = OrderBookCacheManager()

        bids = [PriceLevel(price=0.5, size=100, total_usd=50)]
        asks = [PriceLevel(price=0.6, size=100, total_usd=60)]

        manager.apply_snapshot("token_1", bids, asks)

        cache = manager.get_cache("token_1")
        assert cache is not None
        assert len(cache.bids) == 1
        assert len(cache.asks) == 1

    def test_apply_update(self):
        """Test applying update"""
        manager = OrderBookCacheManager()

        manager.apply_update("token_1", bid_updates=[(0.5, 100)])

        cache = manager.get_cache("token_1")
        assert cache is not None
        assert cache.bids[0.5] == 100

    def test_get_market_orderbook(self):
        """Test getting market orderbook (YES + NO combined)"""
        manager = OrderBookCacheManager()

        # Set up YES token cache
        manager.apply_snapshot(
            "yes_token",
            bids=[PriceLevel(price=0.5, size=100, total_usd=50)],
            asks=[PriceLevel(price=0.6, size=100, total_usd=60)],
            market_id="market_1",
            is_yes_token=True,
        )

        # Set up NO token cache
        manager.apply_snapshot(
            "no_token",
            bids=[PriceLevel(price=0.4, size=200, total_usd=80)],
            asks=[PriceLevel(price=0.5, size=200, total_usd=100)],
            market_id="market_1",
            is_yes_token=False,
        )

        # Get combined orderbook
        snapshot = manager.get_market_orderbook(
            market_id="market_1",
            yes_token_id="yes_token",
            no_token_id="no_token",
        )

        assert snapshot is not None
        assert snapshot.market_id == "market_1"
        assert len(snapshot.yes_bids.levels) == 1
        assert len(snapshot.no_bids.levels) == 1
        assert snapshot.is_stale is False

    def test_get_market_orderbook_missing_cache(self):
        """Test getting market orderbook with missing cache"""
        manager = OrderBookCacheManager()

        snapshot = manager.get_market_orderbook(
            market_id="market_1",
            yes_token_id="yes_token",
            no_token_id="no_token",
        )

        assert snapshot is None

    def test_get_stale_tokens(self):
        """Test getting stale tokens"""
        manager = OrderBookCacheManager(stale_threshold_seconds=60)

        # Add cache and make it stale
        manager.apply_update("token_1", bid_updates=[(0.5, 100)])
        cache = manager.get_cache("token_1")
        cache.last_update_time = datetime.utcnow() - timedelta(seconds=120)

        # Add fresh cache
        manager.apply_update("token_2", bid_updates=[(0.5, 100)])

        stale = manager.get_stale_tokens()
        assert "token_1" in stale
        assert "token_2" not in stale

    def test_subscribed_count(self):
        """Test subscribed count"""
        manager = OrderBookCacheManager()

        assert manager.subscribed_count() == 0

        manager.apply_update("token_1", bid_updates=[(0.5, 100)])
        assert manager.subscribed_count() == 1

        manager.apply_update("token_2", bid_updates=[(0.5, 100)])
        assert manager.subscribed_count() == 2

    def test_clear_all(self):
        """Test clearing all caches"""
        manager = OrderBookCacheManager()

        manager.apply_update("token_1", bid_updates=[(0.5, 100)])
        manager.apply_update("token_2", bid_updates=[(0.5, 100)])

        manager.clear_all()

        assert manager.subscribed_count() == 0
