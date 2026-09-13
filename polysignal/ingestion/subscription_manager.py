"""
Subscription Manager - Manage WebSocket subscriptions

This module handles subscription to WebSocket market channels.
Market channel uses asset_ids (token IDs), not condition IDs.

IMPORTANT:
- max_subscriptions is per TOKEN, not per market
- Each market has 2 tokens (YES + NO)
- Subscribe in batches with delay to avoid rate limiting
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from polysignal.logging_config import get_logger

logger = get_logger("polysignal.ingestion.subscription_manager")


@dataclass
class SubscriptionManager:
    """
    Manage WebSocket subscriptions for market channel.

    Market channel subscribes by asset_ids (token IDs).
    Each market typically has 2 tokens: YES and NO.

    Usage:
        manager = SubscriptionManager(max_subscriptions=20)
        await manager.subscribe(ws_client, ["yes_token_1", "no_token_1"])
    """

    max_subscriptions: int = 20  # Maximum tokens (not markets)
    batch_size: int = 5
    delay_ms: int = 100

    # Currently subscribed token IDs
    _subscribed: set[str] = field(default_factory=set)

    def can_subscribe(self, token_ids: list[str]) -> list[str]:
        """
        Check which tokens can be subscribed.

        Args:
            token_ids: Token IDs to check

        Returns:
            List of tokens that can be subscribed (not already subscribed, within limit)
        """
        # Filter out already subscribed
        new_tokens = [t for t in token_ids if t not in self._subscribed]

        # Check limit
        available_slots = self.max_subscriptions - len(self._subscribed)
        return new_tokens[:available_slots]

    async def subscribe_batch(
        self,
        send_subscribe: Callable[[list[str]], Awaitable[Any]],
        token_ids: list[str],
    ) -> tuple[int, int]:
        """
        Subscribe to tokens in batches.

        Args:
            send_subscribe: Function to send subscribe message
            token_ids: Token IDs to subscribe

        Returns:
            Tuple of (success_count, failed_count)
        """
        to_subscribe = self.can_subscribe(token_ids)
        if not to_subscribe:
            logger.debug("No new tokens to subscribe")
            return 0, 0

        success_count = 0
        failed_count = 0

        # Subscribe in batches
        for i in range(0, len(to_subscribe), self.batch_size):
            batch = to_subscribe[i:i + self.batch_size]

            try:
                await send_subscribe(batch)
                self._subscribed.update(batch)
                success_count += len(batch)
                logger.info(
                    "Subscribed to tokens",
                    batch_size=len(batch),
                    total_subscribed=len(self._subscribed),
                )
            except Exception as e:
                failed_count += len(batch)
                logger.error(
                    "Failed to subscribe to batch",
                    batch_size=len(batch),
                    error=str(e),
                )

            # Delay between batches
            if i + self.batch_size < len(to_subscribe):
                await asyncio.sleep(self.delay_ms / 1000)

        return success_count, failed_count

    def unsubscribe(self, token_ids: list[str]) -> int:
        """
        Mark tokens as unsubscribed (does not send unsubscribe message).

        Args:
            token_ids: Token IDs to unsubscribe

        Returns:
            Number of tokens unsubscribed
        """
        count = 0
        for token_id in token_ids:
            if token_id in self._subscribed:
                self._subscribed.remove(token_id)
                count += 1
        return count

    def is_subscribed(self, token_id: str) -> bool:
        """Check if a token is subscribed."""
        return token_id in self._subscribed

    def subscribed_tokens(self) -> list[str]:
        """Get list of subscribed token IDs."""
        return list(self._subscribed)

    def subscribed_count(self) -> int:
        """Get number of subscribed tokens."""
        return len(self._subscribed)

    def available_slots(self) -> int:
        """Get number of available subscription slots."""
        return self.max_subscriptions - len(self._subscribed)

    def clear(self) -> None:
        """Clear all subscriptions."""
        self._subscribed.clear()