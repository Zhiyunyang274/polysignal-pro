"""
Data Converter - Convert Polymarket API Data to Internal Models

This module converts raw API responses to internal Pydantic models.
It handles defensive parsing with graceful fallbacks for missing/invalid data.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from polysignal.ingestion.api_types import (
    CLOBOrderbook,
    CLOBPriceLevel,
    GammaMarket,
    GammaToken,
)
from polysignal.logging_config import get_logger
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.models.orderbook import (
    OrderBookSide,
    OrderBookSnapshot,
    OrderBookUpdate,
    PriceLevel,
)

logger = get_logger("polysignal.ingestion.data_converter")


# Category mapping from Gamma API to internal enum
CATEGORY_MAP: dict[str, MarketCategory] = {
    "crypto": MarketCategory.CRYPTO,
    "sports": MarketCategory.SPORTS,
    "politics": MarketCategory.POLITICS,
    "geopolitics": MarketCategory.WAR_GEOPOLITICS,
    "war": MarketCategory.WAR_GEOPOLITICS,
    "legal": MarketCategory.LEGAL,
    "entertainment": MarketCategory.CELEBRITY,
    "celebrity": MarketCategory.CELEBRITY,
    "weather": MarketCategory.WEATHER,
    "finance": MarketCategory.MACRO,
    "macro": MarketCategory.MACRO,
    "economics": MarketCategory.MACRO,
}


class DataConverter:
    """
    Convert Polymarket API data to internal models.

    This converter handles defensive parsing:
    - Missing fields → default values
    - Unknown category → MarketCategory.OTHER
    - Invalid token IDs → skip orderbook
    - Invalid datetime → None
    - String number parse fail → 0.0
    """

    @staticmethod
    def parse_float(value: str | float | None, default: float = 0.0) -> float:
        """Safely parse a float from string or number"""
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def parse_datetime(value: str | None) -> datetime | None:
        """Safely parse datetime from ISO format string"""
        if value is None:
            return None
        try:
            # Handle ISO format with Z suffix
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def map_category(category: str | None) -> MarketCategory:
        """Map Gamma API category to internal MarketCategory"""
        if category is None:
            return MarketCategory.OTHER

        category_lower = category.lower().strip()
        return CATEGORY_MAP.get(category_lower, MarketCategory.OTHER)

    @staticmethod
    def determine_status(gamma_market: GammaMarket) -> MarketStatus:
        """Determine market status from Gamma API response"""
        if gamma_market.resolved is True:
            return MarketStatus.RESOLVED
        if gamma_market.closed is True:
            return MarketStatus.CLOSED
        if gamma_market.active is False:
            return MarketStatus.CLOSED
        return MarketStatus.OPEN

    @staticmethod
    def extract_token_ids(
        tokens: list[GammaToken],
    ) -> tuple[str | None, str | None]:
        """
        Extract YES and NO token IDs from tokens list.

        Returns:
            Tuple of (yes_token_id, no_token_id)
        """
        yes_token_id: str | None = None
        no_token_id: str | None = None

        for token in tokens:
            outcome = (token.outcome or "").lower()
            token_id = token.token_id

            if not token_id:
                continue

            if outcome == "yes":
                yes_token_id = token_id
            elif outcome == "no":
                no_token_id = token_id

        return yes_token_id, no_token_id

    @staticmethod
    def extract_token_ids_from_clob_ids(
        clob_token_ids: list[str],
        outcomes: list[str],
    ) -> tuple[str | None, str | None]:
        """
        Extract YES and NO token IDs from clobTokenIds array.

        Gamma API returns token IDs in clobTokenIds field with outcomes
        in a separate outcomes field.

        Args:
            clob_token_ids: List of token IDs from clobTokenIds field
            outcomes: List of outcome names (e.g., ["Yes", "No"])

        Returns:
            Tuple of (yes_token_id, no_token_id)
        """
        if not clob_token_ids or not outcomes:
            return None, None

        yes_token_id: str | None = None
        no_token_id: str | None = None

        for i, outcome in enumerate(outcomes):
            if i >= len(clob_token_ids):
                break

            outcome_lower = outcome.lower()
            if outcome_lower == "yes":
                yes_token_id = clob_token_ids[i]
            elif outcome_lower == "no":
                no_token_id = clob_token_ids[i]

        return yes_token_id, no_token_id

    @staticmethod
    def gamma_to_market(gamma_market: GammaMarket) -> Market | None:
        """
        Convert Gamma API market to internal Market model.

        Args:
            gamma_market: Raw Gamma API market data

        Returns:
            Market model, or None if required fields are missing
        """
        # Required fields
        market_id = gamma_market.id
        if not market_id:
            logger.warning("Gamma market missing id, skipping")
            return None

        title = gamma_market.question or "Unknown Market"

        # Extract token IDs - try multiple methods
        yes_token_id: str | None = None
        no_token_id: str | None = None

        # Method 1: From tokens array (old format)
        if gamma_market.tokens:
            yes_token_id, no_token_id = DataConverter.extract_token_ids(
                gamma_market.tokens
            )

        # Method 2: From clobTokenIds + outcomes (new format)
        if not yes_token_id or not no_token_id:
            # Use model_dump to get extra fields
            market_dict = gamma_market.model_dump()
            clob_token_ids_raw = market_dict.get("clobTokenIds", [])
            outcomes_raw = market_dict.get("outcomes", [])

            # Gamma API may return these as JSON strings, not lists
            # Parse JSON strings if needed
            clob_token_ids: list[str] = []
            outcomes: list[str] = []

            if isinstance(clob_token_ids_raw, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids_raw)
                except (json.JSONDecodeError, TypeError):
                    clob_token_ids = []
            elif isinstance(clob_token_ids_raw, list):
                clob_token_ids = clob_token_ids_raw

            if isinstance(outcomes_raw, str):
                try:
                    outcomes = json.loads(outcomes_raw)
                except (json.JSONDecodeError, TypeError):
                    outcomes = []
            elif isinstance(outcomes_raw, list):
                outcomes = outcomes_raw

            if clob_token_ids and outcomes:
                yes_token_id, no_token_id = DataConverter.extract_token_ids_from_clob_ids(
                    clob_token_ids, outcomes
                )

        # Parse volume
        total_volume = DataConverter.parse_float(gamma_market.volume, 0.0)
        volume_24h = DataConverter.parse_float(gamma_market.volume_24h, 0.0)

        # Parse dates
        created_at = DataConverter.parse_datetime(gamma_market.created_at)
        close_time = DataConverter.parse_datetime(gamma_market.end_date)

        # Determine status
        status = DataConverter.determine_status(gamma_market)

        # Map category
        category = DataConverter.map_category(gamma_market.category)

        # Check if forbidden for auto execution
        forbidden_categories = {
            MarketCategory.POLITICS,
            MarketCategory.WAR_GEOPOLITICS,
            MarketCategory.LEGAL,
            MarketCategory.CELEBRITY,
            MarketCategory.SUBJECTIVE,
        }
        is_forbidden_auto = category in forbidden_categories

        return Market(
            market_id=market_id,
            title=title,
            description=gamma_market.description,
            category=category,
            status=status,
            yes_token_address=yes_token_id,
            no_token_address=no_token_id,
            total_volume_usd=total_volume,
            volume_24h_usd=volume_24h,
            created_at=created_at,
            close_time=close_time,
            resolution_source=gamma_market.resolution_source,
            is_ambiguous=False,  # Will be set by Lifecycle Engine
            is_forbidden_auto=is_forbidden_auto,
            fetched_at=datetime.utcnow(),
        )

    @staticmethod
    def clob_level_to_price_level(level: CLOBPriceLevel) -> PriceLevel | None:
        """
        Convert CLOB price level to internal PriceLevel.

        Args:
            level: CLOB price level

        Returns:
            PriceLevel or None if invalid
        """
        if not level.price or not level.size:
            return None

        try:
            price = float(level.price)
            size = float(level.size)

            if price <= 0 or price > 1:
                return None
            if size <= 0:
                return None

            total_usd = price * size

            return PriceLevel(
                price=price,
                size=size,
                total_usd=total_usd,
            )
        except (ValueError, TypeError):
            return None

    @staticmethod
    def clob_orderbook_to_side(
        levels: list[CLOBPriceLevel],
        is_bid: bool = True,
    ) -> OrderBookSide:
        """
        Convert CLOB price levels to OrderBookSide.

        Args:
            levels: List of CLOB price levels
            is_bid: If True, calculate best bid (highest price).
                    If False, calculate best ask (lowest price).

        Returns:
            OrderBookSide with converted levels
        """
        converted_levels: list[PriceLevel] = []

        for level in levels:
            price_level = DataConverter.clob_level_to_price_level(level)
            if price_level:
                converted_levels.append(price_level)

        side = OrderBookSide(levels=converted_levels)
        side.calculate_best(is_bid=is_bid)

        return side

    @staticmethod
    def clob_orderbooks_to_snapshot(
        yes_orderbook: CLOBOrderbook | None,
        no_orderbook: CLOBOrderbook | None,
        market_id: str,
    ) -> OrderBookSnapshot | None:
        """
        Convert YES and NO CLOB orderbooks to internal OrderBookSnapshot.

        Note: CLOB API returns orderbook for a single token.
        This method combines YES and NO orderbooks into a complete snapshot.

        Args:
            yes_orderbook: YES token orderbook from CLOB API
            no_orderbook: NO token orderbook from CLOB API
            market_id: Market ID

        Returns:
            OrderBookSnapshot or None if both orderbooks are missing
        """
        if yes_orderbook is None and no_orderbook is None:
            logger.warning(
                "Both YES and NO orderbooks are None, cannot create snapshot",
                market_id=market_id,
            )
            return None

        # Convert YES orderbook
        # In CLOB, bids are buy orders, asks are sell orders
        # For YES token: bids = buy YES, asks = sell YES
        yes_bids = OrderBookSide()
        yes_asks = OrderBookSide()

        if yes_orderbook:
            yes_bids = DataConverter.clob_orderbook_to_side(
                yes_orderbook.bids or [],
                is_bid=True,  # bids: best is highest price
            )
            yes_asks = DataConverter.clob_orderbook_to_side(
                yes_orderbook.asks or [],
                is_bid=False,  # asks: best is lowest price
            )

        # Convert NO orderbook
        # For NO token: bids = buy NO, asks = sell NO
        no_bids = OrderBookSide()
        no_asks = OrderBookSide()

        if no_orderbook:
            no_bids = DataConverter.clob_orderbook_to_side(
                no_orderbook.bids or [],
                is_bid=True,  # bids: best is highest price
            )
            no_asks = DataConverter.clob_orderbook_to_side(
                no_orderbook.asks or [],
                is_bid=False,  # asks: best is lowest price
            )

        snapshot = OrderBookSnapshot(
            snapshot_id=str(uuid4()),
            market_id=market_id,
            timestamp=datetime.utcnow(),
            yes_bids=yes_bids,
            yes_asks=yes_asks,
            no_bids=no_bids,
            no_asks=no_asks,
            source="clob",
        )

        snapshot.calculate_metrics()

        return snapshot

    @staticmethod
    def clob_orderbook_to_update(
        orderbook: CLOBOrderbook,
        market_id: str,
        is_yes: bool,
    ) -> OrderBookUpdate:
        """
        Convert CLOB orderbook to lightweight OrderBookUpdate.

        Args:
            orderbook: CLOB orderbook
            market_id: Market ID
            is_yes: Whether this is YES token

        Returns:
            OrderBookUpdate with best prices only
        """
        update = OrderBookUpdate(
            market_id=market_id,
            timestamp=datetime.utcnow(),
            source="clob",
        )

        # Extract best prices using max/min (not [0] index)
        # Polymarket CLOB API may return asks in descending order
        if orderbook.bids:
            # Best bid is highest price
            try:
                best_bid = max(orderbook.bids, key=lambda x: float(x.price) if x.price else 0)
                if best_bid and best_bid.price:
                    price = float(best_bid.price)
                    size = float(best_bid.size) if best_bid.size else 0.0

                    if is_yes:
                        update.yes_best_bid = price
                        update.yes_best_bid_size = size
                    else:
                        update.no_best_bid = price
                        update.no_best_bid_size = size
            except (ValueError, TypeError):
                pass

        if orderbook.asks:
            # Best ask is lowest price
            try:
                best_ask = min(orderbook.asks, key=lambda x: float(x.price) if x.price else float('inf'))
                if best_ask and best_ask.price:
                    price = float(best_ask.price)
                    size = float(best_ask.size) if best_ask.size else 0.0

                    if is_yes:
                        update.yes_best_ask = price
                        update.yes_best_ask_size = size
                    else:
                        update.no_best_ask = price
                        update.no_best_ask_size = size
            except (ValueError, TypeError):
                pass

        return update
