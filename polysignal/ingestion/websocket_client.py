"""
WebSocket Client - Polymarket CLOB WebSocket Market Channel

This module provides a read-only WebSocket client for Polymarket CLOB.
It connects to the public market channel and subscribes to orderbook updates.

IMPORTANT:
- This is READ-ONLY. No trading operations.
- No authentication required for public market channel.
- No private keys handled.
- No order placement/cancel/approve operations.

Market Channel:
- URL: wss://ws-subscriptions-clob.polymarket.com/ws/market
- Subscribe by asset_ids (token IDs), not condition IDs
- Each market has 2 tokens: YES and NO
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from polysignal.ingestion.orderbook_cache import OrderBookCacheManager
from polysignal.ingestion.reconnection_strategy import ReconnectionStrategy
from polysignal.ingestion.subscription_manager import SubscriptionManager
from polysignal.ingestion.websocket_message_handler import WSMessage, WSMessageHandler
from polysignal.logging_config import get_logger

logger = get_logger("polysignal.ingestion.websocket_client")

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection


@dataclass
class WebSocketConfig:
    """WebSocket configuration."""

    enabled: bool = True
    url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    # Subscribe payload
    subscribe_operation: str = "subscribe"

    # Heartbeat
    ping_interval_seconds: int = 10
    pong_timeout_seconds: int = 10

    # Reconnection
    max_reconnect_attempts: int = 5
    reconnect_delay_seconds: float = 1.0
    reconnect_backoff_multiplier: float = 2.0
    max_reconnect_delay_seconds: float = 60.0

    # Stale detection
    stale_threshold_seconds: int = 60

    # Rate limiting
    max_subscriptions: int = 20  # Per token, not per market
    subscribe_batch_size: int = 5
    subscribe_delay_ms: int = 100

    # Timeouts
    connect_timeout_seconds: int = 10
    message_timeout_seconds: int = 30


class CLOBWebSocketClient:
    """
    Read-only WebSocket client for Polymarket CLOB market channel.

    This client:
    - Connects to public market channel (no auth)
    - Subscribes to orderbook updates by asset_ids (token IDs)
    - Maintains in-memory orderbook cache
    - Provides automatic reconnection
    - Falls back to REST on failure

    This client does NOT:
    - Authenticate (no private keys)
    - Place orders
    - Cancel orders
    - Access account info
    """

    def __init__(
        self,
        config: WebSocketConfig | None = None,
        on_message: Callable[[WSMessage], Awaitable[None]] | None = None,
        on_connect: Callable[[], Awaitable[None]] | None = None,
        on_disconnect: Callable[[], Awaitable[None]] | None = None,
    ):
        """
        Initialize WebSocket client.

        Args:
            config: WebSocket configuration
            on_message: Callback for received messages
            on_connect: Callback for successful connection
            on_disconnect: Callback for disconnection
        """
        self.config = config or WebSocketConfig()
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        # State
        self._ws: ClientConnection | None = None  # WebSocket connection
        self._connected: bool = False
        self._running: bool = False
        self._last_ping: datetime | None = None
        self._last_pong: datetime | None = None

        # Components
        self.cache_manager = OrderBookCacheManager(
            stale_threshold_seconds=self.config.stale_threshold_seconds
        )
        self.subscription_manager = SubscriptionManager(
            max_subscriptions=self.config.max_subscriptions,
            batch_size=self.config.subscribe_batch_size,
            delay_ms=self.config.subscribe_delay_ms,
        )
        self.reconnection_strategy = ReconnectionStrategy(
            max_attempts=self.config.max_reconnect_attempts,
            initial_delay=self.config.reconnect_delay_seconds,
            backoff_multiplier=self.config.reconnect_backoff_multiplier,
            max_delay=self.config.max_reconnect_delay_seconds,
        )
        self.message_handler = WSMessageHandler()

        # Tasks
        self._receive_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._connected and self._ws is not None

    @property
    def is_running(self) -> bool:
        """Check if client is running."""
        return self._running

    def build_subscribe_payload(self, asset_ids: list[str]) -> dict:
        """
        Build subscribe payload for market channel.

        Market channel uses asset_ids (token IDs), not condition IDs.

        Args:
            asset_ids: List of token IDs to subscribe

        Returns:
            Subscribe message dict
        """
        return {
            "type": self.config.subscribe_operation,
            "channel": "market",
            "assets_ids": asset_ids,  # Note: 'assets_ids' not 'asset_ids'
        }

    async def connect(self) -> bool:
        """
        Connect to WebSocket.

        Returns:
            True if connected successfully
        """
        if not self.config.enabled:
            logger.info("WebSocket disabled in config")
            return False

        try:
            import websockets

            logger.info(f"Connecting to WebSocket: {self.config.url}")

            self._ws = await asyncio.wait_for(
                websockets.connect(self.config.url),
                timeout=self.config.connect_timeout_seconds,
            )

            self._connected = True
            self._running = True
            self.reconnection_strategy.reset()

            logger.info("WebSocket connected successfully")

            # Start background tasks
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())

            # Callback
            if self.on_connect:
                await self.on_connect()

            return True

        except TimeoutError:
            logger.error("WebSocket connection timeout")
            return False
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        self._running = False
        self._connected = False

        # Cancel tasks
        if self._receive_task:
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task

        if self._ping_task:
            self._ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ping_task

        # Close connection
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None

        logger.info("WebSocket disconnected")

        # Callback
        if self.on_disconnect:
            await self.on_disconnect()

    async def subscribe(self, token_ids: list[str]) -> tuple[int, int]:
        """
        Subscribe to tokens.

        Args:
            token_ids: List of token IDs to subscribe

        Returns:
            Tuple of (success_count, failed_count)
        """
        if not self.is_connected:
            logger.warning("Cannot subscribe: not connected")
            return 0, len(token_ids)

        async def send_subscribe(batch: list[str]) -> None:
            ws = self._ws
            if ws is None:
                raise RuntimeError("WebSocket is not connected")
            payload = self.build_subscribe_payload(batch)
            await ws.send(json.dumps(payload))

        return await self.subscription_manager.subscribe_batch(send_subscribe, token_ids)

    async def resubscribe_all(self) -> tuple[int, int]:
        """
        Re-subscribe to all previously subscribed tokens.

        Used after reconnection.

        Returns:
            Tuple of (success_count, failed_count)
        """
        tokens = self.subscription_manager.subscribed_tokens()
        self.subscription_manager.clear()
        return await self.subscribe(tokens)

    async def get_orderbook(
        self,
        market_id: str,
        yes_token_id: str,
        no_token_id: str,
    ) -> object | None:
        """
        Get orderbook from cache.

        Args:
            market_id: Market ID
            yes_token_id: YES token ID
            no_token_id: NO token ID

        Returns:
            OrderBookSnapshot or None if not cached
        """
        return self.cache_manager.get_market_orderbook(
            market_id=market_id,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
        )

    async def _receive_loop(self) -> None:
        """Receive and process messages."""
        while self._running and self._ws:
            try:
                message = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=self.config.message_timeout_seconds,
                )

                # Handle pong
                if message == "pong" or message == b"pong":
                    self._last_pong = datetime.utcnow()
                    continue

                # Parse JSON
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.debug("Non-JSON message: {}", message[:100])
                    continue

                # Handle list of messages (Polymarket returns arrays)
                messages = data if isinstance(data, list) else [data]

                for msg_data in messages:
                    # Handle pong in JSON
                    if isinstance(msg_data, dict):
                        if msg_data.get("type") == "pong" or msg_data.get("pong"):
                            self._last_pong = datetime.utcnow()
                            continue

                        # Parse message
                        parsed = self.message_handler.parse_message(msg_data)
                        if not parsed:
                            continue

                        # Apply to cache
                        if parsed.bids is not None and parsed.asks is not None:
                            self.cache_manager.apply_snapshot(
                                token_id=parsed.token_id,
                                bids=parsed.bids,
                                asks=parsed.asks,
                            )
                        elif parsed.bid_updates or parsed.ask_updates:
                            self.cache_manager.apply_update(
                                token_id=parsed.token_id,
                                bid_updates=parsed.bid_updates,
                                ask_updates=parsed.ask_updates,
                            )

                        # Callback
                        if self.on_message:
                            await self.on_message(parsed)

            except TimeoutError:
                # No message received, check connection
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                await self._handle_disconnect()
                break

    async def _ping_loop(self) -> None:
        """Send periodic pings."""
        while self._running:
            try:
                await asyncio.sleep(self.config.ping_interval_seconds)

                if self._ws and self._connected:
                    await self._ws.send("ping")
                    self._last_ping = datetime.utcnow()

                    # Check pong timeout
                    if self._last_ping and self._last_pong:
                        elapsed = (self._last_ping - self._last_pong).total_seconds()
                        if elapsed > self.config.pong_timeout_seconds:
                            logger.warning("Pong timeout, reconnecting")
                            await self._handle_disconnect()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ping loop: {e}")

    async def _handle_disconnect(self) -> None:
        """Handle disconnection and attempt reconnection."""
        self._connected = False

        # Mark caches as potentially stale
        logger.warning("WebSocket disconnected, caches may be stale")

        # Callback
        if self.on_disconnect:
            await self.on_disconnect()

        # Attempt reconnection
        while self._running and not self.reconnection_strategy.is_exhausted:
            delay = self.reconnection_strategy.next_delay()
            if delay is None:
                break

            logger.info(
                f"Reconnecting in {delay:.1f}s (attempt {self.reconnection_strategy.attempt})"
            )
            await asyncio.sleep(delay)

            if await self.connect():
                # Re-subscribe
                await self.resubscribe_all()
                return

        # Exhausted reconnection attempts
        logger.error("WebSocket reconnection failed, giving up")
        self._running = False

    def get_stats(self) -> dict:
        """Get client statistics."""
        return {
            "connected": self._connected,
            "running": self._running,
            "subscribed_tokens": self.subscription_manager.subscribed_count(),
            "cached_tokens": self.cache_manager.subscribed_count(),
            "stale_tokens": len(self.cache_manager.get_stale_tokens()),
            "reconnect_attempts": self.reconnection_strategy.attempt,
        }
