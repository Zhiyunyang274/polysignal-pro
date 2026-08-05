"""
Gamma API Client - Polymarket Gamma API for Market Discovery

This module provides a read-only client for the Polymarket Gamma API.
It fetches market information without authentication.

IMPORTANT: This client is READ-ONLY. It does not support:
- Order placement
- Authentication
- Private key handling
- Any write operations
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from polysignal.ingestion.api_types import GammaMarket
from polysignal.ingestion.api_errors import (
    APIConnectionError,
    APIInvalidResponse,
    APINotFound,
    APIRateLimit,
    APIServerError,
    APITimeout,
    GammaAPIError,
)
from polysignal.logging_config import get_logger


logger = get_logger("polysignal.ingestion.gamma_client")


class GammaAPIClient:
    """
    Gamma API client for market discovery.

    This client is READ-ONLY. It fetches public market data from
    the Polymarket Gamma API without authentication.

    Base URL: https://gamma-api.polymarket.com
    """

    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
    ):
        """
        Initialize Gamma API client.

        Args:
            base_url: Override base URL (for testing)
            timeout_seconds: Request timeout
            max_retries: Maximum retry attempts
        """
        self.base_url = base_url or self.BASE_URL
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_seconds),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Make HTTP request with retry logic.

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters

        Returns:
            JSON response

        Raises:
            GammaAPIError: On API failure after retries
        """
        client = await self._get_client()
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = await client.request(method, endpoint, params=params)

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 404:
                    raise APINotFound(f"Resource not found: {endpoint}")

                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    raise APIRateLimit(
                        "Rate limit exceeded",
                        retry_after=int(retry_after) if retry_after else None,
                    )

                if 500 <= response.status_code < 600:
                    raise APIServerError(
                        f"Server error: {response.status_code}",
                        status_code=response.status_code,
                    )

                raise GammaAPIError(f"Unexpected status code: {response.status_code}")

            except httpx.TimeoutException as e:
                last_error = APITimeout(f"Request timeout: {endpoint}")
                logger.warning(
                    "Gamma API timeout",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )

            except httpx.ConnectError as e:
                last_error = APIConnectionError(f"Connection error: {endpoint}")
                logger.warning(
                    "Gamma API connection error",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )

            except (APINotFound, APIRateLimit, APIServerError):
                raise

            except Exception as e:
                last_error = GammaAPIError(f"Unexpected error: {e}")
                logger.error(
                    "Gamma API unexpected error",
                    endpoint=endpoint,
                    error=str(e),
                )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(1.0 * (attempt + 1))

        raise last_error or GammaAPIError("Unknown error")

    async def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active_only: bool = True,
        category: Optional[str] = None,
    ) -> list[GammaMarket]:
        """
        Get markets from Gamma API.

        Args:
            limit: Maximum number of markets to return
            offset: Offset for pagination
            active_only: Only return active markets
            category: Filter by category

        Returns:
            List of GammaMarket objects
        """
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }

        if active_only:
            params["active"] = "true"

        if category:
            params["category"] = category

        try:
            data = await self._request_with_retry("GET", "/markets", params=params)

            if not isinstance(data, list):
                raise APIInvalidResponse("Expected list response")

            markets = []
            for item in data:
                try:
                    market = GammaMarket(**item)
                    markets.append(market)
                except Exception as e:
                    logger.warning(
                        "Failed to parse Gamma market",
                        error=str(e),
                        item=str(item)[:100],
                    )

            logger.info(
                "Fetched markets from Gamma API",
                count=len(markets),
                limit=limit,
                offset=offset,
            )

            return markets

        except GammaAPIError:
            raise
        except Exception as e:
            raise GammaAPIError(f"Failed to get markets: {e}")

    async def get_market(self, market_id: str) -> Optional[GammaMarket]:
        """
        Get a single market by ID.

        Args:
            market_id: Market ID

        Returns:
            GammaMarket or None if not found
        """
        try:
            data = await self._request_with_retry("GET", f"/markets/{market_id}")
            return GammaMarket(**data)

        except APINotFound:
            return None
        except Exception as e:
            logger.warning(
                "Failed to get market",
                market_id=market_id,
                error=str(e),
            )
            raise GammaAPIError(f"Failed to get market {market_id}: {e}")

    async def get_market_by_slug(self, slug: str) -> Optional[GammaMarket]:
        """
        Get a market by slug.

        Args:
            slug: Market slug

        Returns:
            GammaMarket or None if not found
        """
        try:
            data = await self._request_with_retry(
                "GET", "/markets", params={"slug": slug}
            )

            if isinstance(data, list) and len(data) > 0:
                return GammaMarket(**data[0])

            return None

        except APINotFound:
            return None
        except Exception as e:
            logger.warning(
                "Failed to get market by slug",
                slug=slug,
                error=str(e),
            )
            raise GammaAPIError(f"Failed to get market by slug {slug}: {e}")

    def get_status(self) -> dict[str, Any]:
        """Get client status"""
        return {
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "client_initialized": self._client is not None,
        }
