"""
Tests for WebSocket Message Handler
"""


from polysignal.ingestion.websocket_message_handler import (
    WSMessage,
    WSMessageHandler,
)


class TestWSMessageHandler:
    """Test WebSocket message handler"""

    def test_parse_snapshot_message(self):
        """Test parsing orderbook snapshot"""
        data = {
            "type": "book",
            "asset_id": "test_token_123",
            "bids": [[0.5, 100], [0.4, 200]],
            "asks": [[0.6, 150], [0.7, 100]],
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        assert msg.token_id == "test_token_123"
        assert msg.message_type == "book"
        assert len(msg.bids) == 2
        assert len(msg.asks) == 2
        assert msg.bids[0].price == 0.5
        assert msg.bids[0].size == 100

    def test_parse_snapshot_dict_format(self):
        """Test parsing snapshot with dict format"""
        data = {
            "type": "book",
            "token_id": "test_token",
            "bids": [{"price": 0.5, "size": 100}],
            "asks": [{"price": 0.6, "size": 150}],
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        assert len(msg.bids) == 1
        assert len(msg.asks) == 1

    def test_parse_update_message(self):
        """Test parsing incremental update"""
        data = {
            "type": "book_update",
            "asset_id": "test_token",
            "bid_updates": [[0.5, 200], [0.4, 0]],  # Modify and remove
            "ask_updates": [[0.7, 100]],  # Add
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        assert msg.message_type == "book_update"
        assert len(msg.bid_updates) == 2
        assert len(msg.ask_updates) == 1
        assert msg.bid_updates[0] == (0.5, 200)
        assert msg.bid_updates[1] == (0.4, 0)  # Removal

    def test_parse_tick_message(self):
        """Test parsing tick/price message"""
        data = {
            "type": "tick",
            "asset_id": "test_token",
            "best_bid": 0.5,
            "bid_size": 100,
            "best_ask": 0.6,
            "ask_size": 150,
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        assert msg.message_type == "tick"
        assert msg.bid_updates == [(0.5, 100)]
        assert msg.ask_updates == [(0.6, 150)]

    def test_parse_trade_message(self):
        """Test parsing trade message (returns None)"""
        data = {
            "type": "trade",
            "asset_id": "test_token",
            "price": 0.55,
            "size": 50,
        }

        msg = WSMessageHandler.parse_message(data)

        # Trade messages don't return orderbook data
        assert msg is None

    def test_parse_unknown_message_type(self):
        """Test parsing unknown message type"""
        data = {
            "type": "unknown_type",
            "asset_id": "test_token",
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is None

    def test_parse_missing_type(self):
        """Test parsing message missing type - now treated as orderbook if has bids/asks"""
        data = {
            "asset_id": "test_token",
            "bids": [[0.5, 100]],
        }

        msg = WSMessageHandler.parse_message(data)

        # Now treated as orderbook snapshot
        assert msg is not None
        assert msg.message_type == "book"

    def test_parse_missing_token_id(self):
        """Test parsing message missing token_id"""
        data = {
            "type": "book",
            "bids": [[0.5, 100]],
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is None

    def test_parse_invalid_json(self):
        """Test parsing invalid data"""
        msg = WSMessageHandler.parse_message("not a dict")
        assert msg is None

    def test_parse_invalid_price(self):
        """Test parsing with invalid price (skipped)"""
        data = {
            "type": "book",
            "asset_id": "test_token",
            "bids": [[-0.5, 100], [0.5, 100]],  # First is invalid
            "asks": [[1.5, 100], [0.6, 100]],  # First is invalid
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        # Invalid prices should be skipped
        assert len(msg.bids) == 1
        assert len(msg.asks) == 1

    def test_parse_invalid_size(self):
        """Test parsing with invalid size (skipped)"""
        data = {
            "type": "book",
            "asset_id": "test_token",
            "bids": [[0.5, -100], [0.4, 100]],  # First is invalid
            "asks": [[0.6, 0], [0.7, 100]],  # First is invalid (0 size in snapshot)
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        # Invalid sizes should be skipped
        assert len(msg.bids) == 1

    def test_parse_empty_bids_asks(self):
        """Test parsing with empty bids/asks - returns None since no data"""
        data = {
            "type": "book",
            "asset_id": "test_token",
            "bids": [],
            "asks": [],
        }

        msg = WSMessageHandler.parse_message(data)

        # Empty bids/asks means no orderbook data, returns None
        assert msg is None

    def test_parse_delta_message(self):
        """Test parsing delta message (has bids/asks so treated as book)"""
        data = {
            "type": "delta",
            "asset_id": "test_token",
            "bids": [[0.5, 100]],
            "asks": [[0.6, 150]],
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        # Since it has bids/asks, treated as book
        assert msg.message_type == "book"

    def test_parse_with_channel_field(self):
        """Test parsing with 'channel' instead of 'type'"""
        data = {
            "channel": "book",
            "asset_id": "test_token",
            "bids": [[0.5, 100]],
            "asks": [[0.6, 150]],
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        assert msg.message_type == "book"

    def test_parse_with_token_id_field(self):
        """Test parsing with 'token_id' instead of 'asset_id'"""
        data = {
            "type": "book",
            "token_id": "test_token",
            "bids": [[0.5, 100]],
            "asks": [[0.6, 150]],
        }

        msg = WSMessageHandler.parse_message(data)

        assert msg is not None
        assert msg.token_id == "test_token"


class TestWSMessage:
    """Test WSMessage dataclass"""

    def test_ws_message_creation(self):
        """Test creating WSMessage"""
        from datetime import datetime

        msg = WSMessage(
            token_id="test_token",
            message_type="book",
            timestamp=datetime.utcnow(),
        )

        assert msg.token_id == "test_token"
        assert msg.message_type == "book"
        assert msg.bids is None
        assert msg.asks is None
