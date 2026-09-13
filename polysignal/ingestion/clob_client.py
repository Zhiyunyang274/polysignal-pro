"""
CLOB Read-Only Client - Polymarket CLOB API for Orderbook Data

This module provides a read-only client for the Polymarket CLOB API.
It fetches orderbook data without authentication.

IMPORTANT: This client is READ-ONLY. It does not support:
- Order placement
- Order cancellation
- Authentication
- Private key handling
- Any write operations
- WebSocket connections (Phase 4B)

TODO: verify exact WebSocket URL and subscription payload against official docs
before enabling real websocket mode.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx

from polysignal.ingestion.api_errors import (
    APIConnectionError,
    APIInvalidResponse,
    APINotFound,
    APIRateLimit,
    APIServerError,
    APITimeout,
    CLOBError,
)
from polysignal.ingestion.api_types import CLOBOrderbook, CLOBTicker
from polysignal.logging_config import get_logger

logger = get_logger("polysignal.ingestion.clob_client")


class CLOBReadOnlyClient:
    """
    CLOB API client for orderbook data.

    This client is READ-ONLY. It fetches public orderbook data from
    the Polymarket CLOB API without authentication.

    Base URL: https://clob.polymarket.com

    Key points:
    - Orderbook is fetched by token_id (not market_id)
    - Each market has YES token and NO token
    - To get full market orderbook, must request both tokens separately
    """

    BASE_URL = "https://clob.polymarket.com"

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
    ):
        """
        Initialize CLOB API client.

        Args:
            base_url: Override base URL (for testing)
            timeout_seconds: Request timeout
            max_retries: Maximum retry attempts
        """
        self.base_url = base_url or self.BASE_URL
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

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
        params: dict[str, Any] | None = None,
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
            CLOBError: On API failure after retries
        """
        client = await self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await client.request(method, endpoint, params=params)

                if response.status_code == 200:
                    return cast(dict[str, Any], response.json())

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

                raise CLOBError(f"Unexpected status code: {response.status_code}")

            except httpx.TimeoutException:
                last_error = APITimeout(f"Request timeout: {endpoint}")
                logger.warning(
                    "CLOB API timeout",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )

            except httpx.ConnectError:
                last_error = APIConnectionError(f"Connection error: {endpoint}")
                logger.warning(
                    "CLOB API connection error",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                )

            except (APINotFound, APIRateLimit, APIServerError):
                raise

            except Exception as e:
                last_error = CLOBError(f"Unexpected error: {e}")
                logger.error(
                    "CLOB API unexpected error",
                    endpoint=endpoint,
                    error=str(e),
                )

            if attempt < self.max_retries - 1:
                await asyncio.sleep(1.0 * (attempt + 1))

        raise last_error or CLOBError("Unknown error")

    async def get_orderbook(
        self,
        token_id: str,
    ) -> CLOBOrderbook | None:
        """
        Get orderbook for a single token.

        Note: This returns orderbook for ONE token (YES or NO).
        To get full market orderbook, use get_market_orderbook().

        Args:
            token_id: Token ID (YES or NO token)

        Returns:
            CLOBOrderbook or None if not found
        """
        try:
            data = await self._request_with_retry(
                "GET", "/book", params={"token_id": token_id}
            )

            return CLOBOrderbook(**data)

        except APINotFound:
            return None
        except Exception as e:
            logger.warning(
                "Failed to get orderbook",
                token_id=token_id,
                error=str(e),
            )
            raise CLOBError(f"Failed to get orderbook for token {token_id}: {e}") from e

    async def get_price(self, token_id: str) -> float | None:
        """
        Get current price for a token.

        Args:
            token_id: Token ID

        Returns:
            Price as float, or None if not found
        """
        try:
            data = await self._request_with_retry(
                "GET", "/price", params={"token_id": token_id}
            )

            price_str = data.get("price")
            if price_str is not None:
                return float(price_str)

            return None

        except APINotFound:
            return None
        except Exception as e:
            logger.warning(
                "Failed to get price",
                token_id=token_id,
                error=str(e),
            )
            raise CLOBError(f"Failed to get price for token {token_id}: {e}") from e

    async def get_tickers(self) -> list[CLOBTicker]:
        """
        Get all market tickers.

        Returns:
            List of CLOBTicker objects
        """
        try:
            data = await self._request_with_retry("GET", "/tickers")

            if not isinstance(data, list):
                raise APIInvalidResponse("Expected list response")

            tickers = []
            for item in data:
                try:
                    ticker = CLOBTicker(**item)
                    tickers.append(ticker)
                except Exception as e:
                    logger.warning(
                        "Failed to parse CLOB ticker",
                        error=str(e),
                        item=str(item)[:100],
                    )

            logger.info(
                "Fetched tickers from CLOB API",
                count=len(tickers),
            )

            return tickers

        except CLOBError:
            raise
        except Exception as e:
            raise CLOBError(f"Failed to get tickers: {e}") from e

    async def get_market_orderbook(
        self,
        yes_token_id: str,
        no_token_id: str,
    ) -> tuple[CLOBOrderbook | None, CLOBOrderbook | None]:
        """
        Get orderbook for both YES and NO tokens of a market.

        This method fetches orderbooks for both tokens concurrently.
        Each token's orderbook is fetched separately from the CLOB API.

        Args:
            yes_token_id: YES token ID
            no_token_id: NO token ID

        Returns:
            Tuple of (yes_orderbook, no_orderbook)
            Either may be None if fetch failed
        """
        try:
            # Fetch both orderbooks concurrently
            yes_book, no_book = await asyncio.gather(
                self.get_orderbook(yes_token_id),
                self.get_orderbook(no_token_id),
                return_exceptions=True,
            )

            # Handle exceptions from gather
            if isinstance(yes_book, Exception):
                logger.warning(
                    "Failed to fetch YES orderbook",
                    token_id=yes_token_id,
                    error=str(yes_book),
                )
                yes_book = None

            if isinstance(no_book, Exception):
                logger.warning(
                    "Failed to fetch NO orderbook",
                    token_id=no_token_id,
                    error=str(no_book),
                )
                no_book = None

            if isinstance(yes_book, BaseException):
                yes_book = None
            if isinstance(no_book, BaseException):
                no_book = None

            return yes_book, no_book

        except Exception as e:
            logger.error(
                "Failed to get market orderbook",
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                error=str(e),
            )
            return None, None

    def get_status(self) -> dict[str, Any]:
        """Get client status"""
        return {
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "client_initialized": self._client is not None,
        }
