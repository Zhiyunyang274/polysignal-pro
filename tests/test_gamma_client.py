"""
Tests for Gamma API Client

Tests the Gamma API client with mocked HTTP responses.
All tests use aioresponses to mock HTTP requests.
"""

from unittest.mock import patch

import httpx
import pytest

from polysignal.ingestion.api_errors import (
    APINotFound,
    APIRateLimit,
    APITimeout,
    GammaAPIError,
)
from polysignal.ingestion.gamma_client import GammaAPIClient
from tests.fixtures.api_responses import (
    create_gamma_market_response,
    create_gamma_markets_list_response,
)


class TestGammaAPIClient:
    """Test Gamma API Client"""

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_default_settings(self):
        """Test default client settings"""
        client = GammaAPIClient()

        assert client.base_url == "https://gamma-api.polymarket.com"
        assert client.timeout_seconds == 10.0
        assert client.max_retries == 3

    def test_custom_settings(self):
        """Test custom client settings"""
        client = GammaAPIClient(
            base_url="https://custom.url",
            timeout_seconds=5.0,
            max_retries=5,
        )

        assert client.base_url == "https://custom.url"
        assert client.timeout_seconds == 5.0
        assert client.max_retries == 5

    def test_get_status(self):
        """Test get_status returns correct info"""
        client = GammaAPIClient()

        status = client.get_status()

        assert status["base_url"] == "https://gamma-api.polymarket.com"
        assert status["timeout_seconds"] == 10.0
        assert status["max_retries"] == 3
        assert status["client_initialized"] is False

    # =========================================================================
    # Get Markets Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_markets_success(self):
        """Test successful get_markets call"""
        client = GammaAPIClient()

        # Mock HTTP response
        mock_response = create_gamma_markets_list_response(3)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(
                200,
                json=mock_response,
            )

            markets = await client.get_markets()

            assert len(markets) == 3
            assert markets[0].id == "test_market_000"
            assert markets[0].question == "Test Market 0?"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_markets_with_params(self):
        """Test get_markets with query parameters"""
        client = GammaAPIClient()

        mock_response = [create_gamma_market_response()]

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(
                200,
                json=mock_response,
            )

            await client.get_markets(
                limit=50,
                offset=10,
                active_only=True,
                category="crypto",
            )

            # Verify request was made with correct params
            call_args = mock_request.call_args
            assert call_args is not None

        await client.close()

    @pytest.mark.asyncio
    async def test_get_markets_rate_limit(self):
        """Test get_markets handles rate limit"""
        client = GammaAPIClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(
                429,
                headers={"retry-after": "60"},
            )

            with pytest.raises((APIRateLimit, GammaAPIError)):
                await client.get_markets()

        await client.close()

    @pytest.mark.asyncio
    async def test_get_markets_not_found(self):
        """Test get_markets handles 404"""
        client = GammaAPIClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(404)

            with pytest.raises((APINotFound, GammaAPIError)):
                await client.get_markets()

        await client.close()

    @pytest.mark.asyncio
    async def test_get_markets_server_error(self):
        """Test get_markets handles server error"""
        client = GammaAPIClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(500)

            with pytest.raises(GammaAPIError):
                await client.get_markets()

        await client.close()

    @pytest.mark.asyncio
    async def test_get_markets_timeout_retry(self):
        """Test get_markets retries on timeout"""
        client = GammaAPIClient(max_retries=2)

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.TimeoutException("Timeout")
            return httpx.Response(200, json=[create_gamma_market_response()])

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            markets = await client.get_markets()

            assert call_count == 2
            assert len(markets) == 1

        await client.close()

    @pytest.mark.asyncio
    async def test_get_markets_connection_error_retry(self):
        """Test get_markets retries on connection error"""
        client = GammaAPIClient(max_retries=2)

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("Connection failed")
            return httpx.Response(200, json=[create_gamma_market_response()])

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            markets = await client.get_markets()

            assert call_count == 2
            assert len(markets) == 1

        await client.close()

    @pytest.mark.asyncio
    async def test_get_markets_max_retries_exceeded(self):
        """Test get_markets fails after max retries"""
        client = GammaAPIClient(max_retries=2)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Timeout")

            with pytest.raises((APITimeout, GammaAPIError)):
                await client.get_markets()

        await client.close()

    # =========================================================================
    # Get Single Market Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_market_success(self):
        """Test successful get_market call"""
        client = GammaAPIClient()

        mock_response = create_gamma_market_response()

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(200, json=mock_response)

            market = await client.get_market("test_market_001")

            assert market is not None
            assert market.id == "test_market_001"
            assert market.question == "Will BTC reach $100k?"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_market_not_found(self):
        """Test get_market returns None for 404"""
        client = GammaAPIClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(404)

            market = await client.get_market("nonexistent")

            assert market is None

        await client.close()

    # =========================================================================
    # Get Market By Slug Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_market_by_slug_success(self):
        """Test successful get_market_by_slug call"""
        client = GammaAPIClient()

        mock_response = [create_gamma_market_response()]

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(200, json=mock_response)

            market = await client.get_market_by_slug("test-slug")

            assert market is not None
            assert market.id == "test_market_001"

        await client.close()

    @pytest.mark.asyncio
    async def test_get_market_by_slug_not_found(self):
        """Test get_market_by_slug returns None for empty response"""
        client = GammaAPIClient(max_retries=1)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(200, json=[])

            market = await client.get_market_by_slug("nonexistent")

            assert market is None

        await client.close()

    # =========================================================================
    # Close Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_close_client(self):
        """Test closing client"""
        client = GammaAPIClient()

        # Initialize client
        _ = await client._get_client()
        assert client._client is not None

        # Close client
        await client.close()
        assert client._client is None
