"""
Tests for Data Provider Manager

Tests the unified data provider with mode switching and fallback.
"""

from unittest.mock import patch

import httpx
import pytest

from polysignal.ingestion.api_errors import APIError
from polysignal.ingestion.data_provider_manager import (
    DataMode,
    DataProviderManager,
)
from polysignal.models.market import MarketCategory, MarketStatus
from tests.fixtures.api_responses import (
    create_clob_orderbook_mispricing,
    create_gamma_markets_list_response,
)


class TestDataProviderManager:
    """Test Data Provider Manager"""

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_default_mode_is_mock(self):
        """Test default mode is MOCK"""
        manager = DataProviderManager()

        assert manager.mode == DataMode.MOCK
        assert manager.gamma_client is None
        assert manager.clob_client is None
        assert manager.mock_provider is not None

    def test_mock_mode_no_api_clients(self):
        """Test MOCK mode doesn't initialize API clients"""
        manager = DataProviderManager(mode=DataMode.MOCK)

        assert manager.gamma_client is None
        assert manager.clob_client is None

    def test_real_readonly_mode_initializes_clients(self):
        """Test REAL_READONLY mode initializes API clients"""
        manager = DataProviderManager(mode=DataMode.REAL_READONLY)

        assert manager.gamma_client is not None
        assert manager.clob_client is not None

    def test_hybrid_mode_initializes_clients(self):
        """Test HYBRID mode initializes API clients"""
        manager = DataProviderManager(mode=DataMode.HYBRID)

        assert manager.gamma_client is not None
        assert manager.clob_client is not None

    def test_custom_clients(self):
        """Test using custom clients"""
        from polysignal.ingestion.clob_client import CLOBReadOnlyClient
        from polysignal.ingestion.gamma_client import GammaAPIClient

        custom_gamma = GammaAPIClient(base_url="https://custom.gamma")
        custom_clob = CLOBReadOnlyClient(base_url="https://custom.clob")

        manager = DataProviderManager(
            mode=DataMode.REAL_READONLY,
            gamma_client=custom_gamma,
            clob_client=custom_clob,
        )

        assert manager.gamma_client is custom_gamma
        assert manager.clob_client is custom_clob

    def test_get_status(self):
        """Test get_status returns correct info"""
        manager = DataProviderManager(mode=DataMode.HYBRID)

        status = manager.get_status()

        assert status["mode"] == "hybrid"
        assert status["gamma_client"] is not None
        assert status["clob_client"] is not None
        assert status["mock_provider"] is not None

    # =========================================================================
    # Get Markets Tests - Mock Mode
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_markets_mock_mode(self):
        """Test get_markets in MOCK mode"""
        manager = DataProviderManager(mode=DataMode.MOCK)

        markets = await manager.get_markets()

        assert markets.total_count > 0
        assert all(m.market_id.startswith("mock_market_") for m in markets.markets)

    # =========================================================================
    # Get Markets Tests - Real Readonly Mode
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_markets_real_readonly_success(self):
        """Test get_markets in REAL_READONLY mode"""
        manager = DataProviderManager(mode=DataMode.REAL_READONLY)

        mock_response = create_gamma_markets_list_response(3)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(200, json=mock_response)

            markets = await manager.get_markets()

            assert markets.total_count == 3
            assert markets.markets[0].market_id == "test_market_000"

        await manager.close()

    @pytest.mark.asyncio
    async def test_get_markets_real_readonly_failure_raises(self):
        """Test get_markets in REAL_READONLY mode raises on failure"""
        manager = DataProviderManager(mode=DataMode.REAL_READONLY)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Timeout")

            with pytest.raises(APIError):
                await manager.get_markets()

        await manager.close()

    # =========================================================================
    # Get Markets Tests - Hybrid Mode
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_markets_hybrid_success(self):
        """Test get_markets in HYBRID mode with successful API"""
        manager = DataProviderManager(mode=DataMode.HYBRID)

        mock_response = create_gamma_markets_list_response(2)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.return_value = httpx.Response(200, json=mock_response)

            markets = await manager.get_markets()

            assert markets.total_count == 2

        await manager.close()

    @pytest.mark.asyncio
    async def test_get_markets_hybrid_fallback_to_mock(self):
        """Test get_markets in HYBRID mode falls back to mock on failure"""
        manager = DataProviderManager(mode=DataMode.HYBRID)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Timeout")

            markets = await manager.get_markets()

            # Should fall back to mock
            assert markets.total_count > 0
            assert all(m.market_id.startswith("mock_market_") for m in markets.markets)

        await manager.close()

    # =========================================================================
    # Get Orderbook Tests - Mock Mode
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_orderbook_mock_mode(self):
        """Test get_orderbook in MOCK mode"""
        manager = DataProviderManager(mode=DataMode.MOCK)

        orderbook = await manager.get_orderbook("mock_market_000")

        assert orderbook is not None
        assert orderbook.market_id == "mock_market_000"
        assert orderbook.source == "mock"

    # =========================================================================
    # Get Orderbook Tests - Real Readonly Mode
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_orderbook_real_readonly_success(self):
        """Test get_orderbook in REAL_READONLY mode"""
        manager = DataProviderManager(mode=DataMode.REAL_READONLY)

        # First, set up market cache with token IDs
        from polysignal.models.market import Market
        manager._markets_cache["test_market_001"] = Market(
            market_id="test_market_001",
            title="Test Market",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.OPEN,
            yes_token_address="token_yes",
            no_token_address="token_no",
        )

        yes_data, no_data = create_clob_orderbook_mispricing("0.48", "0.48")

        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call is for YES orderbook
                return httpx.Response(200, json=yes_data)
            else:
                # Second call is for NO orderbook
                return httpx.Response(200, json=no_data)

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            orderbook = await manager.get_orderbook("test_market_001")

            assert orderbook is not None
            assert orderbook.market_id == "test_market_001"
            assert orderbook.source == "clob"

        await manager.close()

    @pytest.mark.asyncio
    async def test_get_orderbook_real_readonly_missing_tokens(self):
        """Test get_orderbook when market has no token IDs"""
        manager = DataProviderManager(mode=DataMode.REAL_READONLY)

        from polysignal.models.market import Market
        manager._markets_cache["test_market"] = Market(
            market_id="test_market",
            title="Test Market",
            category=MarketCategory.CRYPTO,
            status=MarketStatus.OPEN,
            yes_token_address=None,  # Missing
            no_token_address=None,   # Missing
        )

        orderbook = await manager.get_orderbook("test_market")

        assert orderbook is None

        await manager.close()

    # =========================================================================
    # Get Orderbook Tests - Hybrid Mode
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_orderbook_hybrid_fallback_to_mock(self):
        """Test get_orderbook in HYBRID mode falls back to mock on failure"""
        manager = DataProviderManager(mode=DataMode.HYBRID)

        with patch.object(httpx.AsyncClient, "request") as mock_request:
            mock_request.side_effect = httpx.TimeoutException("Timeout")

            orderbook = await manager.get_orderbook("mock_market_000")

            # Should fall back to mock
            assert orderbook is not None
            assert orderbook.source == "mock"

        await manager.close()

    # =========================================================================
    # Cache Tests
    # =========================================================================

    def test_cache_valid_initially_false(self):
        """Test cache is initially invalid"""
        manager = DataProviderManager()

        assert manager._is_cache_valid() is False

    def test_cache_valid_after_set(self):
        """Test cache is valid after setting timestamp"""
        from datetime import datetime

        manager = DataProviderManager()
        manager._cache_timestamp = datetime.utcnow()

        assert manager._is_cache_valid() is True

    # =========================================================================
    # Close Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_close_mock_mode(self):
        """Test closing manager in MOCK mode"""
        manager = DataProviderManager(mode=DataMode.MOCK)

        # Should not raise
        await manager.close()

    @pytest.mark.asyncio
    async def test_close_real_mode(self):
        """Test closing manager in REAL_READONLY mode"""
        manager = DataProviderManager(mode=DataMode.REAL_READONLY)

        # Initialize clients
        _ = await manager.gamma_client._get_client()

        await manager.close()

        assert manager.gamma_client._client is None
        assert manager.clob_client._client is None
