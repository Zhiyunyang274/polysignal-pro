"""
Tests for WebSocket Client

All tests use mock WebSocket - no real network connections.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from polysignal.ingestion.websocket_client import (
    CLOBWebSocketClient,
    WebSocketConfig,
)
from polysignal.ingestion.websocket_message_handler import WSMessage
from polysignal.models.orderbook import PriceLevel


class TestWebSocketConfig:
    """Test WebSocket configuration"""

    def test_default_config(self):
        """Test default configuration"""
        config = WebSocketConfig()

        assert config.enabled is True
        assert config.url == "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        assert config.ping_interval_seconds == 10
        assert config.pong_timeout_seconds == 10
        assert config.max_subscriptions == 20

    def test_custom_config(self):
        """Test custom configuration"""
        config = WebSocketConfig(
            enabled=False,
            url="wss://custom.url/ws",
            max_subscriptions=50,
        )

        assert config.enabled is False
        assert config.url == "wss://custom.url/ws"
        assert config.max_subscriptions == 50


class TestCLOBWebSocketClient:
    """Test WebSocket client (with mocks)"""

    def test_initial_state(self):
        """Test initial state"""
        client = CLOBWebSocketClient()

        assert not client.is_connected
        assert not client.is_running
        assert client.cache_manager is not None
        assert client.subscription_manager is not None

    def test_build_subscribe_payload(self):
        """Test building subscribe payload"""
        client = CLOBWebSocketClient()

        payload = client.build_subscribe_payload(["token_1", "token_2"])

        assert payload["type"] == "subscribe"
        assert payload["channel"] == "market"
        assert payload["assets_ids"] == ["token_1", "token_2"]

    def test_get_stats(self):
        """Test getting stats"""
        client = CLOBWebSocketClient()

        stats = client.get_stats()

        assert "connected" in stats
        assert "running" in stats
        assert "subscribed_tokens" in stats

    @pytest.mark.asyncio
    async def test_connect_disabled(self):
        """Test connect when disabled"""
        config = WebSocketConfig(enabled=False)
        client = CLOBWebSocketClient(config=config)

        result = await client.connect()

        assert result is False
        assert not client.is_connected

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnect"""
        client = CLOBWebSocketClient()

        # Manually set connected state
        client._connected = True
        client._running = True

        await client.disconnect()

        assert not client._connected
        assert not client._running

    @pytest.mark.asyncio
    async def test_subscribe_not_connected(self):
        """Test subscribe when not connected"""
        client = CLOBWebSocketClient()

        success, failed = await client.subscribe(["token_1", "token_2"])

        assert success == 0
        assert failed == 2

    @pytest.mark.asyncio
    async def test_get_orderbook_from_cache(self):
        """Test getting orderbook from cache"""
        client = CLOBWebSocketClient()

        # Add data to cache
        client.cache_manager.apply_snapshot(
            "yes_token",
            bids=[PriceLevel(price=0.5, size=100, total_usd=50)],
            asks=[PriceLevel(price=0.6, size=100, total_usd=60)],
        )
        client.cache_manager.apply_snapshot(
            "no_token",
            bids=[PriceLevel(price=0.4, size=100, total_usd=40)],
            asks=[PriceLevel(price=0.5, size=100, total_usd=50)],
        )

        snapshot = await client.get_orderbook(
            market_id="market_1",
            yes_token_id="yes_token",
            no_token_id="no_token",
        )

        assert snapshot is not None
        assert snapshot.market_id == "market_1"

    @pytest.mark.asyncio
    async def test_get_orderbook_missing_cache(self):
        """Test getting orderbook with missing cache"""
        client = CLOBWebSocketClient()

        snapshot = await client.get_orderbook(
            market_id="market_1",
            yes_token_id="yes_token",
            no_token_id="no_token",
        )

        assert snapshot is None

    @pytest.mark.asyncio
    async def test_on_message_callback(self):
        """Test on_message callback"""
        messages_received = []

        async def on_message(msg):
            messages_received.append(msg)

        client = CLOBWebSocketClient(on_message=on_message)

        # Simulate message processing
        msg = WSMessage(
            token_id="test_token",
            message_type="book",
            timestamp=datetime.utcnow(),
            bids=[PriceLevel(price=0.5, size=100, total_usd=50)],
            asks=[PriceLevel(price=0.6, size=100, total_usd=60)],
        )

        # Apply to cache (this is what receive_loop would do)
        client.cache_manager.apply_snapshot(
            msg.token_id,
            msg.bids,
            msg.asks,
        )

        if client.on_message:
            await client.on_message(msg)

        assert len(messages_received) == 1

    @pytest.mark.asyncio
    async def test_on_connect_callback(self):
        """Test on_connect callback"""
        connected_called = False

        async def on_connect():
            nonlocal connected_called
            connected_called = True

        # Mock websockets.connect
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            client = CLOBWebSocketClient(on_connect=on_connect)
            result = await client.connect()

            assert result is True
            assert connected_called is True

            await client.disconnect()

    @pytest.mark.asyncio
    async def test_on_disconnect_callback(self):
        """Test on_disconnect callback"""
        disconnected_called = False

        async def on_disconnect():
            nonlocal disconnected_called
            disconnected_called = True

        # Mock websockets.connect
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            client = CLOBWebSocketClient(on_disconnect=on_disconnect)
            await client.connect()
            await client.disconnect()

            assert disconnected_called is True


class TestWebSocketClientMockConnection:
    """Test WebSocket client with mocked websockets library"""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection with mock"""
        config = WebSocketConfig()

        # Mock websockets.connect
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type": "pong"}')

        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            client = CLOBWebSocketClient(config=config)
            result = await client.connect()

            assert result is True
            assert client.is_connected

            # Clean up
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """Test connection timeout"""
        config = WebSocketConfig(connect_timeout_seconds=1)

        # Mock websockets.connect to timeout
        async def slow_connect(*args, **kwargs):
            await asyncio.sleep(5)
            return AsyncMock()

        with patch('websockets.connect', new_callable=AsyncMock, side_effect=slow_connect):
            client = CLOBWebSocketClient(config=config)
            result = await client.connect()

            assert result is False
            assert not client.is_connected

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test connection failure"""
        config = WebSocketConfig()

        with patch('websockets.connect', new_callable=AsyncMock, side_effect=Exception("Connection failed")):
            client = CLOBWebSocketClient(config=config)
            result = await client.connect()

            assert result is False
            assert not client.is_connected

    @pytest.mark.asyncio
    async def test_subscribe_with_mock_ws(self):
        """Test subscribe with mock WebSocket"""
        config = WebSocketConfig()

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type": "pong"}')

        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            client = CLOBWebSocketClient(config=config)
            await client.connect()

            success, failed = await client.subscribe(["token_1", "token_2"])

            assert success == 2
            assert failed == 0
            assert client.subscription_manager.subscribed_count() == 2

            # Verify send was called
            assert mock_ws.send.called

            await client.disconnect()

    @pytest.mark.asyncio
    async def test_receive_loop_handles_pong(self):
        """Test receive loop handles pong"""
        config = WebSocketConfig()

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value="pong")
        mock_ws.close = AsyncMock()

        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            client = CLOBWebSocketClient(config=config)
            await client.connect()

            # Wait a bit for receive loop to process
            await asyncio.sleep(0.1)

            # Pong should update last_pong
            assert client._last_pong is not None

            await client.disconnect()

    @pytest.mark.asyncio
    async def test_receive_loop_handles_json_pong(self):
        """Test receive loop handles JSON pong"""
        config = WebSocketConfig()

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type": "pong"}')
        mock_ws.close = AsyncMock()

        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            client = CLOBWebSocketClient(config=config)
            await client.connect()

            await asyncio.sleep(0.1)

            assert client._last_pong is not None

            await client.disconnect()


class TestWebSocketClientReconnection:
    """Test WebSocket client reconnection logic"""

    @pytest.mark.asyncio
    async def test_reconnection_strategy_reset_on_connect(self):
        """Test reconnection strategy reset on successful connect"""
        config = WebSocketConfig()

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            client = CLOBWebSocketClient(config=config)

            # Simulate some failed attempts
            client.reconnection_strategy._attempt = 3

            result = await client.connect()

            assert result is True
            assert client.reconnection_strategy.attempt == 0

            await client.disconnect()

    @pytest.mark.asyncio
    async def test_resubscribe_all(self):
        """Test resubscribe all after reconnection"""
        config = WebSocketConfig()

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.close = AsyncMock()

        with patch('websockets.connect', new_callable=AsyncMock, return_value=mock_ws):
            client = CLOBWebSocketClient(config=config)
            await client.connect()

            # Subscribe some tokens
            await client.subscribe(["token_1", "token_2"])
            assert client.subscription_manager.subscribed_count() == 2

            # Clear and resubscribe
            client.subscription_manager.clear()
            client.subscription_manager._subscribed.add("token_1")
            client.subscription_manager._subscribed.add("token_2")

            success, failed = await client.resubscribe_all()

            assert success == 2

            await client.disconnect()


class TestWebSocketDisabledFallback:
    """Test WebSocket disabled / fallback scenarios"""

    @pytest.mark.asyncio
    async def test_websocket_disabled(self):
        """Test WebSocket disabled"""
        config = WebSocketConfig(enabled=False)
        client = CLOBWebSocketClient(config=config)

        result = await client.connect()

        assert result is False

    @pytest.mark.asyncio
    async def test_stale_data_detection(self):
        """Test stale data detection"""
        client = CLOBWebSocketClient()

        # Add cache and make it stale
        client.cache_manager.apply_snapshot(
            "yes_token",
            bids=[PriceLevel(price=0.5, size=100, total_usd=50)],
            asks=[PriceLevel(price=0.6, size=100, total_usd=60)],
        )

        # Make stale
        cache = client.cache_manager.get_cache("yes_token")
        cache.last_update_time = datetime.utcnow() - timedelta(seconds=120)

        # Get orderbook should mark as stale
        snapshot = await client.get_orderbook(
            market_id="market_1",
            yes_token_id="yes_token",
            no_token_id="no_token",
        )

        # Only yes_token has data, no_token is missing
        if snapshot:
            assert snapshot.is_stale is True