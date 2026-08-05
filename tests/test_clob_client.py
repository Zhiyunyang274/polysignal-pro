"""
Tests for CLOB Read-Only Client

Tests the CLOB API client with mocked HTTP responses.
All tests use mocked HTTP requests.
"""

import pytest
from unittest.mock import patch
import httpx

from polysignal.ingestion.clob_client import CLOBReadOnlyClient
from polysignal.ingestion.api_errors import (
    APINotFound,
    APIRateLimit,
    APITimeout,
    CLOBError,
)
from tests.fixtures.api_responses import (
    create_clob_orderbook_response,
    create_clob_tickers_list_response,
    create_clob_orderbook_mispricing,
)


class TestCLOBReadOnlyClient:
    """Test CLOB Read-Only Client"""

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_default_settings(self):
        """Test default client settings"""
        client = CLOBReadOnlyClient()

        assert client.base_url == "https://clob.polymarket.com"
        assert client.timeout_seconds == 10.0
        assert client.max_retries == 3

    def test_custom_settings(self):
        """Test custom client settings"""
        client = CLOBReadOnlyClient(
            base_url="https://custom.url",
            timeout_seconds=5.0,
            max_retries=5,
        )

        assert client.base_url == "https://custom.url"
        assert client.timeout_seconds == 5.0
        assert client.max_retries == 5

    def test_get_status(self):
        """Test get_status returns correct info"""
        client = CLOBReadOnlyClient()

        status = client.get_status()

        assert status["base_url"] == "https://clob.polymarket.com"
        assert status["timeout_seconds"] == 10.0
        assert status["max_retries"] == 3
        assert status["client_initialized"] is False

    # =========================================================================
    # Get Orderbook Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_orderbook_success(self):
        """Test successful get_orderbook call"""
        client = CLOBReadOnlyClient()

        mock_response = create_clob_orderbook_response()

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(200, json=mock_response)

            orderbook = await client.get_orderbook("token_yes_001")

            assert orderbook is not None
            assert orderbook.asset_id == "token_yes_001"
            assert len(orderbook.bids) == 3
            assert len(orderbook.asks) == 3

        await client.close()

    @pytest.mark.asyncio
    async def test_get_orderbook_not_found(self):
        """Test get_orderbook returns None for 404"""
        client = CLOBReadOnlyClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(404)

            orderbook = await client.get_orderbook("nonexistent")

            assert orderbook is None

        await client.close()

    @pytest.mark.asyncio
    async def test_get_orderbook_rate_limit(self):
        """Test get_orderbook handles rate limit"""
        client = CLOBReadOnlyClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(429)

            with pytest.raises((APIRateLimit, CLOBError)):
                await client.get_orderbook("token_id")

        await client.close()

    # =========================================================================
    # Get Price Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_price_success(self):
        """Test successful get_price call"""
        client = CLOBReadOnlyClient()

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(
                200,
                json={"price": "0.45"},
            )

            price = await client.get_price("token_yes_001")

            assert price == 0.45

        await client.close()

    @pytest.mark.asyncio
    async def test_get_price_not_found(self):
        """Test get_price returns None for 404"""
        client = CLOBReadOnlyClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(404)

            price = await client.get_price("nonexistent")

            assert price is None

        await client.close()

    # =========================================================================
    # Get Tickers Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_tickers_success(self):
        """Test successful get_tickers call"""
        client = CLOBReadOnlyClient()

        mock_response = create_clob_tickers_list_response(3)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(200, json=mock_response)

            tickers = await client.get_tickers()

            assert len(tickers) == 3
            assert tickers[0].market == "test_market_000"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_tickers_empty(self):
        """Test get_tickers with empty response"""
        client = CLOBReadOnlyClient()

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(200, json=[])

            tickers = await client.get_tickers()

            assert len(tickers) == 0

        await client.close()

    # =========================================================================
    # Get Market Orderbook Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_market_orderbook_success(self):
        """Test successful get_market_orderbook call"""
        client = CLOBReadOnlyClient()

        yes_response, no_response = create_clob_orderbook_mispricing("0.48", "0.48")

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json=yes_response)
            else:
                return httpx.Response(200, json=no_response)

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            yes_book, no_book = await client.get_market_orderbook(
                yes_token_id="token_yes",
                no_token_id="token_no",
            )

            assert yes_book is not None
            assert no_book is not None
            assert yes_book.asset_id == "token_yes"
            assert no_book.asset_id == "token_no"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_market_orderbook_partial_failure(self):
        """Test get_market_orderbook with one token failing"""
        client = CLOBReadOnlyClient()

        yes_response = create_clob_orderbook_response(asset_id="token_yes")

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json=yes_response)
            else:
                return httpx.Response(404)

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            yes_book, no_book = await client.get_market_orderbook(
                yes_token_id="token_yes",
                no_token_id="token_no",
            )

            assert yes_book is not None
            assert no_book is None

        await client.close()

    @pytest.mark.asyncio
    async def test_get_market_orderbook_both_failure(self):
        """Test get_market_orderbook with both tokens failing"""
        client = CLOBReadOnlyClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(404)

            yes_book, no_book = await client.get_market_orderbook(
                yes_token_id="token_yes",
                no_token_id="token_no",
            )

            assert yes_book is None
            assert no_book is None

        await client.close()

    # =========================================================================
    # Close Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_close_client(self):
        """Test closing client"""
        client = CLOBReadOnlyClient()

        # Initialize client
        _ = await client._get_client()
        assert client._client is not None

        # Close client
        await client.close()
        assert client._client is None

    # =========================================================================
    # Retry Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_orderbook_retry_on_timeout(self):
        """Test get_orderbook retries on timeout"""
        client = CLOBReadOnlyClient(max_retries=2)

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.TimeoutException("Timeout")
            return httpx.Response(200, json=create_clob_orderbook_response())

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            orderbook = await client.get_orderbook("token_id")

            assert call_count == 2
            assert orderbook is not None

        await client.close()

    @pytest.mark.asyncio
    async def test_get_orderbook_max_retries_exceeded(self):
        """Test get_orderbook fails after max retries"""
        client = CLOBReadOnlyClient(max_retries=2)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Timeout")

            with pytest.raises((APITimeout, CLOBError)):
                await client.get_orderbook("token_id")

        await client.close()
