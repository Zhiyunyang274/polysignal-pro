"""
WebSocket Message Handler - Parse Polymarket WebSocket messages

This module parses messages from Polymarket CLOB WebSocket market channel.

Message types expected:
- book: Full orderbook snapshot
- book_update / delta: Incremental update
- trade: Trade execution
- tick: Price tick

IMPORTANT: This is read-only. No trading instructions are parsed or executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from polysignal.logging_config import get_logger
from polysignal.models.orderbook import PriceLevel
from polysignal.utils.time import utc_now

logger = get_logger("polysignal.ingestion.websocket_message_handler")


@dataclass
class WSMessage:
    """Parsed WebSocket message."""

    token_id: str
    message_type: str
    timestamp: datetime

    # For snapshot messages
    bids: list[PriceLevel] | None = None
    asks: list[PriceLevel] | None = None

    # For update messages
    bid_updates: list[tuple[float, float]] | None = None  # (price, size)
    ask_updates: list[tuple[float, float]] | None = None

    # Raw message for debugging
    raw: dict | None = None


class WSMessageHandler:
    """
    Parse WebSocket messages from Polymarket CLOB.

    Handles defensive parsing:
    - Unknown message types → None
    - Missing fields → None
    - Invalid price/size → skip that level
    - JSON parse error → None
    """

    @staticmethod
    def parse_message(data: dict) -> WSMessage | None:
        """
        Parse a WebSocket message.

        Args:
            data: Raw message dict

        Returns:
            WSMessage or None if unparseable
        """
        if not isinstance(data, dict):
            return None

        # Get token ID - try multiple field names
        token_id = (
            data.get("asset_id")
            or data.get("token_id")
            or data.get("market")
            or data.get("condition_id")
        )

        # If no type but has bids/asks, treat as orderbook snapshot
        # Polymarket returns orderbook data directly without a type field
        if data.get("bids") or data.get("asks"):
            if not token_id:
                logger.debug("Orderbook message missing token_id")
                return None
            return WSMessageHandler._parse_snapshot(data, token_id, "book", utc_now())

        # Determine message type
        msg_type = data.get("type") or data.get("channel") or data.get("event")
        if not msg_type:
            logger.debug("Message missing type field")
            return None

        msg_type_lower = msg_type.lower()

        if not token_id:
            logger.debug(f"Message missing token_id, type={msg_type}")
            return None

        timestamp = datetime.now(UTC)

        # Parse based on type
        if msg_type_lower in ("book", "orderbook", "snapshot"):
            return WSMessageHandler._parse_snapshot(data, token_id, msg_type, timestamp)
        elif msg_type_lower in ("book_update", "delta", "update"):
            return WSMessageHandler._parse_update(data, token_id, msg_type, timestamp)
        elif msg_type_lower in ("trade", "trades"):
            # Trade messages - log but don't return orderbook data
            logger.debug(f"Received trade message for {token_id[:20]}")
            return None
        elif msg_type_lower in ("tick", "price"):
            # Tick messages - could update best bid/ask
            return WSMessageHandler._parse_tick(data, token_id, msg_type, timestamp)
        else:
            logger.debug(f"Unknown message type: {msg_type}")
            return None

    @staticmethod
    def _parse_snapshot(
        data: dict,
        token_id: str,
        msg_type: str,
        timestamp: datetime,
    ) -> WSMessage | None:
        """Parse orderbook snapshot message."""
        # Try various field names for bids/asks
        bids_data = data.get("bids") or data.get("buy") or []
        asks_data = data.get("asks") or data.get("sell") or []

        if not bids_data and not asks_data:
            logger.debug(f"Snapshot missing bids/asks for {token_id[:20]}")
            return None

        bids = WSMessageHandler._parse_price_levels(bids_data)
        asks = WSMessageHandler._parse_price_levels(asks_data)

        return WSMessage(
            token_id=token_id,
            message_type=msg_type,
            timestamp=timestamp,
            bids=bids,
            asks=asks,
            raw=data,
        )

    @staticmethod
    def _parse_update(
        data: dict,
        token_id: str,
        msg_type: str,
        timestamp: datetime,
    ) -> WSMessage | None:
        """Parse incremental update message."""
        # Try various field names
        bid_updates_data = data.get("bid_updates") or data.get("bids") or []
        ask_updates_data = data.get("ask_updates") or data.get("asks") or []

        bid_updates = WSMessageHandler._parse_updates(bid_updates_data)
        ask_updates = WSMessageHandler._parse_updates(ask_updates_data)

        if not bid_updates and not ask_updates:
            logger.debug(f"Update missing changes for {token_id[:20]}")
            return None

        return WSMessage(
            token_id=token_id,
            message_type=msg_type,
            timestamp=timestamp,
            bid_updates=bid_updates,
            ask_updates=ask_updates,
            raw=data,
        )

    @staticmethod
    def _parse_tick(
        data: dict,
        token_id: str,
        msg_type: str,
        timestamp: datetime,
    ) -> WSMessage | None:
        """Parse tick/price message."""
        # Tick might have best bid/ask
        best_bid = data.get("best_bid") or data.get("bid")
        best_ask = data.get("best_ask") or data.get("ask")
        bid_size = data.get("bid_size") or data.get("bid_amount")
        ask_size = data.get("ask_size") or data.get("ask_amount")

        bid_updates = None
        ask_updates = None

        if best_bid is not None and bid_size is not None:
            try:
                price = float(best_bid)
                size = float(bid_size)
                if 0 < price <= 1 and size > 0:
                    bid_updates = [(price, size)]
            except (ValueError, TypeError):
                pass

        if best_ask is not None and ask_size is not None:
            try:
                price = float(best_ask)
                size = float(ask_size)
                if 0 < price <= 1 and size > 0:
                    ask_updates = [(price, size)]
            except (ValueError, TypeError):
                pass

        if not bid_updates and not ask_updates:
            return None

        return WSMessage(
            token_id=token_id,
            message_type=msg_type,
            timestamp=timestamp,
            bid_updates=bid_updates,
            ask_updates=ask_updates,
            raw=data,
        )

    @staticmethod
    def _parse_price_levels(data: list) -> list[PriceLevel]:
        """
        Parse price levels from message.

        Args:
            data: List of [price, size] or {"price": ..., "size": ...}

        Returns:
            List of PriceLevel objects
        """
        levels: list[PriceLevel] = []

        if not isinstance(data, list):
            return levels

        for item in data:
            try:
                if isinstance(item, (list, tuple)):
                    if len(item) >= 2:
                        price = float(item[0])
                        size = float(item[1])
                    else:
                        continue
                elif isinstance(item, dict):
                    price = float(item.get("price", 0))
                    size = float(item.get("size", 0))
                else:
                    continue

                # Validate
                if price <= 0 or price > 1:
                    continue
                if size <= 0:
                    continue

                levels.append(PriceLevel(price=price, size=size, total_usd=price * size))

            except (ValueError, TypeError, KeyError):
                continue

        return levels

    @staticmethod
    def _parse_updates(data: list) -> list[tuple[float, float]]:
        """
        Parse update tuples from message.

        Args:
            data: List of [price, size] or {"price": ..., "size": ...}

        Returns:
            List of (price, size) tuples
        """
        updates: list[tuple[float, float]] = []

        if not isinstance(data, list):
            return updates

        for item in data:
            try:
                if isinstance(item, (list, tuple)):
                    if len(item) >= 2:
                        price = float(item[0])
                        size = float(item[1])
                    else:
                        continue
                elif isinstance(item, dict):
                    price = float(item.get("price", 0))
                    size = float(item.get("size", 0))
                else:
                    continue

                # Validate price (size can be 0 for removal)
                if price <= 0 or price > 1:
                    continue

                updates.append((price, size))

            except (ValueError, TypeError, KeyError):
                continue

        return updates
