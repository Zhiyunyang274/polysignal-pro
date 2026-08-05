"""
Tests for Telegram Action Handler

Tests the Telegram action handler with:
- Allowed actions
- Forbidden actions
- Idempotency
- Database logging
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from polysignal.interface.telegram_client import TelegramClient
from polysignal.interface.telegram_handler import TelegramActionHandler
from polysignal.models.telegram import TelegramAction, TelegramActionResult
from polysignal.storage.database import Database
from tests.fixtures.telegram import create_test_signal, create_test_risk_decision


class TestTelegramActionHandler:
    """Test Telegram Action Handler"""

    @pytest.fixture
    def mock_db(self):
        """Create mock database"""
        db = MagicMock(spec=Database)
        db.log_telegram_action = AsyncMock()
        db.get_signal = AsyncMock()
        db.get_risk_decision = AsyncMock()
        db.add_ignore_rule = AsyncMock(return_value=True)
        db.add_blacklist = AsyncMock(return_value=True)
        db.add_wallet_to_watchlist = AsyncMock(return_value=True)
        db.is_signal_reviewed = AsyncMock(return_value=False)
        db.mark_signal_reviewed = AsyncMock()
        db.get_recent_orders = AsyncMock(return_value=[])
        return db

    @pytest.fixture
    def telegram_client(self, monkeypatch):
        """Create Telegram client"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        return TelegramClient()

    @pytest.fixture
    def handler(self, telegram_client, mock_db):
        """Create action handler"""
        return TelegramActionHandler(telegram_client, mock_db)

    # =========================================================================
    # Forbidden Actions Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_forbidden_action_buy(self, handler):
        """Test buy action is forbidden"""
        result, message = await handler.handle_action(
            action="buy",
            user_id=123,
        )

        assert result == TelegramActionResult.REJECTED
        assert "forbidden" in message.lower()

    @pytest.mark.asyncio
    async def test_forbidden_action_sell(self, handler):
        """Test sell action is forbidden"""
        result, message = await handler.handle_action(
            action="sell",
            user_id=123,
        )

        assert result == TelegramActionResult.REJECTED
        assert "forbidden" in message.lower()

    @pytest.mark.asyncio
    async def test_forbidden_action_execute(self, handler):
        """Test execute action is forbidden"""
        result, message = await handler.handle_action(
            action="execute",
            user_id=123,
        )

        assert result == TelegramActionResult.REJECTED

    @pytest.mark.asyncio
    async def test_forbidden_action_live_trade(self, handler):
        """Test live_trade action is forbidden"""
        result, message = await handler.handle_action(
            action="live_trade",
            user_id=123,
        )

        assert result == TelegramActionResult.REJECTED

    @pytest.mark.asyncio
    async def test_forbidden_action_paper_trade(self, handler):
        """Test paper_trade action is forbidden (system auto-executes)"""
        result, message = await handler.handle_action(
            action="paper_trade",
            user_id=123,
        )

        assert result == TelegramActionResult.REJECTED

    # =========================================================================
    # Unknown Action Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_unknown_action(self, handler):
        """Test unknown action returns failed"""
        result, message = await handler.handle_action(
            action="unknown_action",
            user_id=123,
        )

        assert result == TelegramActionResult.FAILED
        assert "Unknown" in message

    # =========================================================================
    # Details Action Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_details_missing_signal_id(self, handler):
        """Test details action requires signal_id"""
        result, message = await handler.handle_action(
            action="details",
            user_id=123,
            signal_id=None,
        )

        assert result == TelegramActionResult.FAILED
        assert "Signal ID required" in message

    @pytest.mark.asyncio
    async def test_details_signal_not_found(self, handler, mock_db):
        """Test details action when signal not found"""
        mock_db.get_signal.return_value = None

        result, message = await handler.handle_action(
            action="details",
            user_id=123,
            signal_id="test_signal",
        )

        assert result == TelegramActionResult.FAILED
        assert "not found" in message

    @pytest.mark.asyncio
    async def test_details_success(self, handler, mock_db):
        """Test details action success"""
        signal = create_test_signal()
        decision = create_test_risk_decision()
        mock_db.get_signal.return_value = signal
        mock_db.get_risk_decision.return_value = decision

        result, message = await handler.handle_action(
            action="details",
            user_id=123,
            signal_id="test_signal",
        )

        assert result == TelegramActionResult.SUCCESS
        assert signal.market_title in message

    # =========================================================================
    # Ignore Future Action Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_ignore_future_success(self, handler, mock_db):
        """Test ignore_future action success"""
        result, message = await handler.handle_action(
            action="ignore_future",
            user_id=123,
            market_id="test_market",
            strategy_name="test_strategy",
        )

        assert result == TelegramActionResult.SUCCESS
        assert "ignored" in message.lower()
        mock_db.add_ignore_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignore_future_already_exists(self, handler, mock_db):
        """Test ignore_future action when rule already exists"""
        mock_db.add_ignore_rule.return_value = False

        result, message = await handler.handle_action(
            action="ignore_future",
            user_id=123,
            market_id="test_market",
            strategy_name="test_strategy",
        )

        assert result == TelegramActionResult.ALREADY_EXISTS
        assert "already" in message.lower()

    # =========================================================================
    # Blacklist Action Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_blacklist_market_success(self, handler, mock_db):
        """Test blacklist_market action success"""
        result, message = await handler.handle_action(
            action="blacklist_market",
            user_id=123,
            market_id="test_market",
        )

        assert result == TelegramActionResult.SUCCESS
        assert "blacklist" in message.lower()
        mock_db.add_blacklist.assert_called_once()

    @pytest.mark.asyncio
    async def test_blacklist_market_already_exists(self, handler, mock_db):
        """Test blacklist_market action when already blacklisted"""
        mock_db.add_blacklist.return_value = False

        result, message = await handler.handle_action(
            action="blacklist_market",
            user_id=123,
            market_id="test_market",
        )

        assert result == TelegramActionResult.ALREADY_EXISTS

    # =========================================================================
    # Track Wallet Action Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_track_wallet_success(self, handler, mock_db):
        """Test track_wallet action success"""
        result, message = await handler.handle_action(
            action="track_wallet",
            user_id=123,
            wallet_address="0x123",
        )

        assert result == TelegramActionResult.SUCCESS
        assert "watchlist" in message.lower()
        mock_db.add_wallet_to_watchlist.assert_called_once()

    @pytest.mark.asyncio
    async def test_track_wallet_already_exists(self, handler, mock_db):
        """Test track_wallet action when wallet already tracked"""
        mock_db.add_wallet_to_watchlist.return_value = False

        result, message = await handler.handle_action(
            action="track_wallet",
            user_id=123,
            wallet_address="0x123",
        )

        assert result == TelegramActionResult.ALREADY_EXISTS

    # =========================================================================
    # Pause/Resume Alerts Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_pause_alerts(self, handler, telegram_client):
        """Test pause_alerts action"""
        result, message = await handler.handle_action(
            action="pause_alerts",
            user_id=123,
        )

        assert result == TelegramActionResult.SUCCESS
        assert telegram_client.are_alerts_paused() is True

    @pytest.mark.asyncio
    async def test_resume_alerts(self, handler, telegram_client):
        """Test resume_alerts action"""
        telegram_client.pause_alerts()

        result, message = await handler.handle_action(
            action="resume_alerts",
            user_id=123,
        )

        assert result == TelegramActionResult.SUCCESS
        assert telegram_client.are_alerts_paused() is False

    # =========================================================================
    # Pause/Resume Signals Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_pause_signals(self, handler, telegram_client):
        """Test pause_signals action"""
        result, message = await handler.handle_action(
            action="pause_signals",
            user_id=123,
        )

        assert result == TelegramActionResult.SUCCESS
        assert telegram_client.are_signals_paused() is True

    @pytest.mark.asyncio
    async def test_resume_signals(self, handler, telegram_client):
        """Test resume_signals action"""
        telegram_client.pause_signals()

        result, message = await handler.handle_action(
            action="resume_signals",
            user_id=123,
        )

        assert result == TelegramActionResult.SUCCESS
        assert telegram_client.are_signals_paused() is False

    # =========================================================================
    # Mark Reviewed Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_mark_reviewed_success(self, handler, mock_db):
        """Test mark_reviewed action success"""
        result, message = await handler.handle_action(
            action="mark_reviewed",
            user_id=123,
            signal_id="test_signal",
        )

        assert result == TelegramActionResult.SUCCESS
        assert "reviewed" in message.lower()
        mock_db.mark_signal_reviewed.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_reviewed_already_reviewed(self, handler, mock_db):
        """Test mark_reviewed action when already reviewed"""
        mock_db.is_signal_reviewed.return_value = True

        result, message = await handler.handle_action(
            action="mark_reviewed",
            user_id=123,
            signal_id="test_signal",
        )

        assert result == TelegramActionResult.ALREADY_EXISTS

    # =========================================================================
    # Logging Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_action_logged_to_database(self, handler, mock_db):
        """Test action is logged to database"""
        await handler.handle_action(
            action="pause_alerts",
            user_id=123,
            username="test_user",
        )

        mock_db.log_telegram_action.assert_called_once()
        call_args = mock_db.log_telegram_action.call_args
        assert call_args[1]["action"] == "pause_alerts"
        assert call_args[1]["user_id"] == 123
