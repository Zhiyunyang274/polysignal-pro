"""
OrderBook Cache - In-memory cache for WebSocket orderbook data

This module maintains orderbook state per token_id.
Complete market orderbook is synthesized from YES + NO token caches.

IMPORTANT: Cache is maintained per token_id, not per market_id.
Each market has two tokens: YES token and NO token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from polysignal.logging_config import get_logger
from polysignal.models.orderbook import (
    OrderBookSide,
    OrderBookSnapshot,
    PriceLevel,
)

logger = get_logger("polysignal.ingestion.orderbook_cache")


@dataclass
class TokenOrderBookCache:
    """
    In-memory orderbook cache for a single token.

    Maintains bid and ask levels as price -> size mappings.
    """

    token_id: str
    market_id: str | None = None
    is_yes_token: bool | None = None

    # Price levels: price -> size
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)

    # Metadata
    last_update_time: datetime | None = None
    last_snapshot_time: datetime | None = None
    update_count: int = 0

    def apply_snapshot(self, bids: list[PriceLevel], asks: list[PriceLevel]) -> None:
        """
        Replace entire orderbook with snapshot.

        Args:
            bids: List of bid price levels
            asks: List of ask price levels
        """
        self.bids = {level.price: level.size for level in bids}
        self.asks = {level.price: level.size for level in asks}
        self.last_snapshot_time = datetime.utcnow()
        self.last_update_time = datetime.utcnow()
        self.update_count += 1

    def apply_update(
        self,
        bid_updates: list[tuple[float, float]] | None = None,
        ask_updates: list[tuple[float, float]] | None = None,
    ) -> None:
        """
        Apply incremental update.

        Size of 0 means remove the level.

        Args:
            bid_updates: List of (price, size) tuples for bids
            ask_updates: List of (price, size) tuples for asks
        """
        if bid_updates:
            for price, size in bid_updates:
                if size == 0:
                    self.bids.pop(price, None)
                else:
                    self.bids[price] = size

        if ask_updates:
            for price, size in ask_updates:
                if size == 0:
                    self.asks.pop(price, None)
                else:
                    self.asks[price] = size

        self.last_update_time = datetime.utcnow()
        self.update_count += 1

    def get_bid_side(self) -> OrderBookSide:
        """Get bid side as OrderBookSide."""
        levels = [
            PriceLevel(price=p, size=s, total_usd=p * s)
            for p, s in sorted(self.bids.items(), reverse=True)
        ]
        side = OrderBookSide(levels=levels)
        side.calculate_best_bid()
        return side

    def get_ask_side(self) -> OrderBookSide:
        """Get ask side as OrderBookSide."""
        levels = [
            PriceLevel(price=p, size=s, total_usd=p * s)
            for p, s in sorted(self.asks.items())
        ]
        side = OrderBookSide(levels=levels)
        side.calculate_best_ask()
        return side

    def is_stale(self, threshold_seconds: int = 60) -> bool:
        """
        Check if data is stale.

        Args:
            threshold_seconds: Stale threshold in seconds

        Returns:
            True if no update received within threshold
        """
        if not self.last_update_time:
            return True
        age = (datetime.utcnow() - self.last_update_time).total_seconds()
        return age > threshold_seconds

    def clear(self) -> None:
        """Clear all cached data."""
        self.bids.clear()
        self.asks.clear()
        self.last_update_time = None
        self.last_snapshot_time = None
        self.update_count = 0


@dataclass
class OrderBookCacheManager:
    """
    Manages orderbook caches for multiple tokens.

    IMPORTANT: Caches are per token_id, not per market_id.
    Each market has two tokens (YES + NO).

    Usage:
        manager = OrderBookCacheManager(stale_threshold_seconds=60)

        # Apply WebSocket message
        manager.apply_snapshot(token_id, bids, asks)
        manager.apply_update(token_id, bid_updates, ask_updates)

        # Get market orderbook (combines YES + NO tokens)
        snapshot = manager.get_market_orderbook(
            market_id="market_1",
            yes_token_id="yes_token",
            no_token_id="no_token",
        )
    """

    stale_threshold_seconds: int = 60

    # token_id -> cache
    _caches: dict[str, TokenOrderBookCache] = field(default_factory=dict)

    def get_cache(self, token_id: str) -> TokenOrderBookCache | None:
        """Get cache for a token."""
        return self._caches.get(token_id)

    def get_or_create_cache(
        self,
        token_id: str,
        market_id: str | None = None,
        is_yes_token: bool | None = None,
    ) -> TokenOrderBookCache:
        """Get or create cache for a token."""
        if token_id not in self._caches:
            self._caches[token_id] = TokenOrderBookCache(
                token_id=token_id,
                market_id=market_id,
                is_yes_token=is_yes_token,
            )
        return self._caches[token_id]

    def apply_snapshot(
        self,
        token_id: str,
        bids: list[PriceLevel],
        asks: list[PriceLevel],
        market_id: str | None = None,
        is_yes_token: bool | None = None,
    ) -> None:
        """
        Apply orderbook snapshot to cache.

        Args:
            token_id: Token ID
            bids: Bid price levels
            asks: Ask price levels
            market_id: Optional market ID
            is_yes_token: Whether this is YES token
        """
        cache = self.get_or_create_cache(token_id, market_id, is_yes_token)
        cache.apply_snapshot(bids, asks)
        logger.debug(
            "Applied snapshot to cache",
            token_id=token_id[:20],
            bid_count=len(bids),
            ask_count=len(asks),
        )

    def apply_update(
        self,
        token_id: str,
        bid_updates: list[tuple[float, float]] | None = None,
        ask_updates: list[tuple[float, float]] | None = None,
    ) -> None:
        """
        Apply incremental update to cache.

        Args:
            token_id: Token ID
            bid_updates: List of (price, size) tuples for bids
            ask_updates: List of (price, size) tuples for asks
        """
        cache = self._caches.get(token_id)
        if not cache:
            logger.warning(
                "Received update for unknown token, creating new cache",
                token_id=token_id[:20],
            )
            cache = self.get_or_create_cache(token_id)

        cache.apply_update(bid_updates, ask_updates)
        logger.debug(
            "Applied update to cache",
            token_id=token_id[:20],
            bid_updates=len(bid_updates or []),
            ask_updates=len(ask_updates or []),
        )

    def get_market_orderbook(
        self,
        market_id: str,
        yes_token_id: str,
        no_token_id: str,
    ) -> OrderBookSnapshot | None:
        """
        Get combined orderbook for a market.

        Combines YES token cache + NO token cache into a single snapshot.

        Args:
            market_id: Market ID
            yes_token_id: YES token ID
            no_token_id: NO token ID

        Returns:
            OrderBookSnapshot combining both tokens, or None if caches missing
        """
        yes_cache = self._caches.get(yes_token_id)
        no_cache = self._caches.get(no_token_id)

        if not yes_cache and not no_cache:
            return None

        # Check if stale
        is_stale = False
        if yes_cache and yes_cache.is_stale(self.stale_threshold_seconds):
            is_stale = True
        if no_cache and no_cache.is_stale(self.stale_threshold_seconds):
            is_stale = True

        # Build snapshot
        from uuid import uuid4

        snapshot = OrderBookSnapshot(
            snapshot_id=str(uuid4()),
            market_id=market_id,
            timestamp=datetime.utcnow(),
            yes_bids=yes_cache.get_bid_side() if yes_cache else OrderBookSide(),
            yes_asks=yes_cache.get_ask_side() if yes_cache else OrderBookSide(),
            no_bids=no_cache.get_bid_side() if no_cache else OrderBookSide(),
            no_asks=no_cache.get_ask_side() if no_cache else OrderBookSide(),
            source="websocket",
            is_stale=is_stale,
        )

        snapshot.calculate_metrics()
        return snapshot

    def get_stale_tokens(self) -> list[str]:
        """Get list of token IDs with stale data."""
        return [
            token_id
            for token_id, cache in self._caches.items()
            if cache.is_stale(self.stale_threshold_seconds)
        ]

    def clear_all(self) -> None:
        """Clear all caches."""
        for cache in self._caches.values():
            cache.clear()
        self._caches.clear()

    def subscribed_count(self) -> int:
        """Get number of subscribed tokens."""
        return len(self._caches)
