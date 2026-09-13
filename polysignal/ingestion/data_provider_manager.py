"""
Data Provider Manager - Unified Data Source with Fallback

This module provides a unified interface for market and orderbook data,
with support for mock, real_readonly, and hybrid modes.

Mode behavior:
- mock: Always use mock data
- real_readonly: Always use real API, fail if API unavailable
- hybrid: Try real API first, fallback to mock on failure
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from polysignal.ingestion.api_errors import APIError
from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from polysignal.ingestion.data_converter import DataConverter
from polysignal.ingestion.gamma_client import GammaAPIClient
from polysignal.ingestion.mock_data_provider import MockDataProvider
from polysignal.logging_config import get_logger
from polysignal.models.market import Market, MarketList
from polysignal.models.orderbook import OrderBookSnapshot
from polysignal.utils.time import utc_now

logger = get_logger("polysignal.ingestion.data_provider_manager")


class DataMode(str, Enum):
    """Data source mode"""
    MOCK = "mock"
    REAL_READONLY = "real_readonly"
    HYBRID = "hybrid"


class DataProviderManager:
    """
    Unified data provider with mode switching and fallback.

    This manager provides a unified interface for market and orderbook data,
    supporting three modes:
    - mock: Always use mock data (default)
    - real_readonly: Always use real API
    - hybrid: Try real API first, fallback to mock

    Graceful fallback:
    - API failures in hybrid mode automatically fall back to mock
    - Missing token IDs result in skipped orderbooks
    - Invalid data is logged and skipped
    """

    def __init__(
        self,
        mode: DataMode = DataMode.MOCK,
        gamma_client: GammaAPIClient | None = None,
        clob_client: CLOBReadOnlyClient | None = None,
        mock_provider: MockDataProvider | None = None,
        gamma_base_url: str | None = None,
        clob_base_url: str | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
    ):
        """
        Initialize data provider manager.

        Args:
            mode: Data source mode (default: MOCK)
            gamma_client: Optional pre-configured Gamma client
            clob_client: Optional pre-configured CLOB client
            mock_provider: Optional pre-configured mock provider
            gamma_base_url: Override Gamma API base URL
            clob_base_url: Override CLOB API base URL
            timeout_seconds: API timeout
            max_retries: Maximum API retries
        """
        self.mode = mode

        # Initialize clients based on mode
        if mode == DataMode.MOCK:
            # Mock mode: only use mock provider
            self.gamma_client = None
            self.clob_client = None
        else:
            # Real or hybrid mode: initialize API clients
            self.gamma_client = gamma_client or GammaAPIClient(
                base_url=gamma_base_url,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
            self.clob_client = clob_client or CLOBReadOnlyClient(
                base_url=clob_base_url,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )

        # Always have mock provider as fallback
        self.mock_provider = mock_provider or MockDataProvider(seed=42)

        # Cache for market data
        self._markets_cache: dict[str, Market] = {}
        self._cache_timestamp: datetime | None = None
        self._cache_ttl_seconds = 60

    async def close(self) -> None:
        """Close API clients"""
        if self.gamma_client:
            await self.gamma_client.close()
        if self.clob_client:
            await self.clob_client.close()

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if self._cache_timestamp is None:
            return False
        elapsed = (utc_now() - self._cache_timestamp).total_seconds()
        return elapsed < self._cache_ttl_seconds

    async def get_markets(self) -> MarketList:
        """
        Get markets from configured data source.

        Returns:
            MarketList with markets

        Raises:
            APIError: In real_readonly mode if API fails
        """
        if self.mode == DataMode.MOCK:
            return self.mock_provider.get_markets()

        if self.mode == DataMode.REAL_READONLY:
            return await self._get_real_markets()

        # Hybrid mode: try real, fallback to mock
        try:
            return await self._get_real_markets()
        except APIError as e:
            logger.warning(
                "API failed in hybrid mode, falling back to mock",
                error=str(e),
            )
            return self.mock_provider.get_markets()

    async def _get_real_markets(self) -> MarketList:
        """
        Get markets from real API.

        Returns:
            MarketList with real markets

        Raises:
            APIError: If API fails
        """
        if not self.gamma_client:
            raise APIError("Gamma client not initialized")

        try:
            gamma_markets = await self.gamma_client.get_markets()

            markets: list[Market] = []
            for gamma_market in gamma_markets:
                try:
                    market = DataConverter.gamma_to_market(gamma_market)
                    if market:
                        markets.append(market)
                        self._markets_cache[market.market_id] = market
                except Exception as e:
                    logger.warning(
                        "Failed to convert market",
                        market_id=gamma_market.id,
                        error=str(e),
                    )

            self._cache_timestamp = utc_now()

            logger.info(
                "Fetched markets from real API",
                count=len(markets),
                mode=self.mode.value,
            )

            return MarketList(
                markets=markets,
                total_count=len(markets),
                fetched_at=utc_now(),
            )

        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Failed to get real markets: {e}") from e

    async def get_orderbook(self, market_id: str) -> OrderBookSnapshot | None:
        """
        Get orderbook for a market.

        Args:
            market_id: Market ID

        Returns:
            OrderBookSnapshot or None if unavailable

        Raises:
            APIError: In real_readonly mode if API fails
        """
        if self.mode == DataMode.MOCK:
            return self.mock_provider.get_orderbook_snapshot(market_id)

        if self.mode == DataMode.REAL_READONLY:
            return await self._get_real_orderbook(market_id)

        # Hybrid mode: try real, fallback to mock
        try:
            orderbook = await self._get_real_orderbook(market_id)
            if orderbook:
                return orderbook
            # If no orderbook from real API, fallback to mock
            logger.warning(
                "No orderbook from real API, falling back to mock",
                market_id=market_id,
            )
            return self.mock_provider.get_orderbook_snapshot(market_id)
        except APIError as e:
            logger.warning(
                "API failed in hybrid mode, falling back to mock",
                market_id=market_id,
                error=str(e),
            )
            return self.mock_provider.get_orderbook_snapshot(market_id)

    async def _get_real_orderbook(self, market_id: str) -> OrderBookSnapshot | None:
        """
        Get orderbook from real API.

        Args:
            market_id: Market ID

        Returns:
            OrderBookSnapshot or None if unavailable

        Raises:
            APIError: If API fails
        """
        if not self.clob_client:
            raise APIError("CLOB client not initialized")

        # Get market to find token IDs
        market = self._markets_cache.get(market_id)
        if not market:
            # Try to fetch market info
            market = await self._get_market_info(market_id)

        if not market:
            logger.warning(
                "Market not found for orderbook fetch",
                market_id=market_id,
            )
            return None

        yes_token_id = market.yes_token_address
        no_token_id = market.no_token_address

        if not yes_token_id or not no_token_id:
            logger.warning(
                "Market missing token IDs, cannot fetch orderbook",
                market_id=market_id,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
            )
            return None

        try:
            yes_book, no_book = await self.clob_client.get_market_orderbook(
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
            )

            if yes_book is None and no_book is None:
                return None

            snapshot = DataConverter.clob_orderbooks_to_snapshot(
                yes_orderbook=yes_book,
                no_orderbook=no_book,
                market_id=market_id,
            )

            if snapshot:
                logger.debug(
                    "Fetched orderbook from real API",
                    market_id=market_id,
                    combined_ask=snapshot.combined_ask,
                )

            return snapshot

        except APIError:
            raise
        except Exception as e:
            raise APIError(f"Failed to get real orderbook: {e}") from e

    async def _get_market_info(self, market_id: str) -> Market | None:
        """
        Get market info from cache or API.

        Args:
            market_id: Market ID

        Returns:
            Market or None
        """
        # Check cache first
        if self._is_cache_valid() and market_id in self._markets_cache:
            return self._markets_cache[market_id]

        # Fetch from API
        if not self.gamma_client:
            return None

        try:
            gamma_market = await self.gamma_client.get_market(market_id)
            if gamma_market:
                market = DataConverter.gamma_to_market(gamma_market)
                if market:
                    self._markets_cache[market_id] = market
                    return market
        except Exception as e:
            logger.warning(
                "Failed to get market info",
                market_id=market_id,
                error=str(e),
            )

        return None

    def get_status(self) -> dict[str, Any]:
        """Get manager status"""
        return {
            "mode": self.mode.value,
            "gamma_client": self.gamma_client.get_status() if self.gamma_client else None,
            "clob_client": self.clob_client.get_status() if self.clob_client else None,
            "mock_provider": {
                "num_markets": len(self.mock_provider._markets),
            },
            "cache": {
                "markets_cached": len(self._markets_cache),
                "cache_valid": self._is_cache_valid(),
            },
        }
