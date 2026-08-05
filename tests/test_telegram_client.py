"""
Tests for Telegram Client

Tests the Telegram Signal Cockpit client with:
- Lazy loading
- Graceful fallback
- Pause states
- Message building
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from polysignal.interface.telegram_client import TelegramClient
from polysignal.models.signal import SignalSide
from polysignal.models.risk import RiskAction
from tests.fixtures.telegram import (
    create_test_signal,
    create_test_risk_decision,
)


class TestTelegramClient:
    """Test Telegram Client"""

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_client_disabled_when_no_token(self, monkeypatch):
        """Test client is disabled when TELEGRAM_BOT_TOKEN is not set"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        client = TelegramClient()

        assert client.enabled is False
        assert client.token is None
        assert client.chat_id is None

    def test_client_disabled_when_no_chat_id(self, monkeypatch):
        """Test client is disabled when TELEGRAM_CHAT_ID is not set"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        client = TelegramClient()

        assert client.enabled is False

    def test_client_enabled_with_valid_config(self, monkeypatch):
        """Test client is enabled with valid config"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test_chat_id")

        client = TelegramClient()

        assert client.enabled is True
        assert client.token == "test_token"
        assert client.chat_id == "test_chat_id"

    # =========================================================================
    # Lazy Loading Tests
    # =========================================================================

    def test_lazy_load_bot_disabled_client(self, monkeypatch):
        """Test lazy load returns False when client is disabled"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()

        assert client._lazy_load_bot() is False
        assert client._bot is None

    def test_lazy_load_bot_import_error(self, monkeypatch):
        """Test lazy load handles ImportError gracefully"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test_chat_id")

        client = TelegramClient()

        # Simulate ImportError by mocking the import to fail
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "telegram":
                raise ImportError("No module named 'telegram'")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, '__import__', side_effect=mock_import):
            result = client._lazy_load_bot()

        assert result is False
        assert client.enabled is False

    # =========================================================================
    # Pause State Tests
    # =========================================================================

    def test_initial_pause_state(self, monkeypatch):
        """Test initial pause state is running"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()

        assert client.are_alerts_paused() is False
        assert client.are_signals_paused() is False

    def test_pause_alerts(self, monkeypatch):
        """Test pause_alerts sets state correctly"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()

        result = client.pause_alerts()

        assert "paused" in result.lower()
        assert client.are_alerts_paused() is True

    def test_resume_alerts(self, monkeypatch):
        """Test resume_alerts sets state correctly"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()
        client.pause_alerts()

        result = client.resume_alerts()

        assert "resumed" in result.lower()
        assert client.are_alerts_paused() is False

    def test_pause_signals(self, monkeypatch):
        """Test pause_signals sets state correctly"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()

        result = client.pause_signals()

        assert "paused" in result.lower()
        assert client.are_signals_paused() is True

    def test_resume_signals(self, monkeypatch):
        """Test resume_signals sets state correctly"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()
        client.pause_signals()

        result = client.resume_signals()

        assert "resumed" in result.lower()
        assert client.are_signals_paused() is False

    def test_pause_alerts_idempotent(self, monkeypatch):
        """Test pause_alerts is idempotent"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()

        client.pause_alerts()
        result = client.pause_alerts()

        assert "already paused" in result.lower()

    # =========================================================================
    # Alert Sending Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_send_alert_disabled_client(self, monkeypatch):
        """Test send_alert returns False when client is disabled"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()
        signal = create_test_signal()
        decision = create_test_risk_decision()

        result = await client.send_alert(signal, decision)

        assert result is False

    @pytest.mark.asyncio
    async def test_send_alert_paused_alerts(self, monkeypatch):
        """Test send_alert returns False when alerts are paused"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()
        client.pause_alerts()
        signal = create_test_signal()
        decision = create_test_risk_decision()

        result = await client.send_alert(signal, decision)

        assert result is False

    # =========================================================================
    # Message Building Tests
    # =========================================================================

    def test_build_paper_trade_message(self, monkeypatch):
        """Test building paper trade message"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()
        signal = create_test_signal()
        decision = create_test_risk_decision(action=RiskAction.PAPER_TRADE)

        message = client._build_alert_message(signal, decision)

        assert "Paper Trade Executed" in message
        assert signal.market_title in message
        assert signal.strategy_name in message
        assert "PAPER_TRADE" in message

    def test_build_hard_reject_message(self, monkeypatch):
        """Test building hard reject message"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()
        signal = create_test_signal()
        decision = create_test_risk_decision(
            action=RiskAction.HARD_REJECT,
            hard_reject_reasons=["forbidden_category"],
        )

        message = client._build_alert_message(signal, decision)

        assert "Signal Rejected" in message
        assert "HARD_REJECT" in message
        assert "forbidden_category" in message

    def test_build_alert_message(self, monkeypatch):
        """Test building alert message"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()
        signal = create_test_signal()
        decision = create_test_risk_decision(action=RiskAction.ALERT)

        message = client._build_alert_message(signal, decision)

        assert "Signal Alert" in message
        assert "ALERT" in message

    # =========================================================================
    # Status Tests
    # =========================================================================

    def test_get_status_disabled(self, monkeypatch):
        """Test get_status for disabled client"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()
        status = client.get_status()

        assert status["enabled"] is False
        assert status["token_configured"] is False
        assert status["chat_id_configured"] is False
        assert status["alerts_paused"] is False
        assert status["signals_paused"] is False

    def test_get_status_enabled(self, monkeypatch):
        """Test get_status for enabled client"""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "test_chat_id")

        client = TelegramClient()
        status = client.get_status()

        assert status["enabled"] is True
        assert status["token_configured"] is True
        assert status["chat_id_configured"] is True

    # =========================================================================
    # Forbidden Actions Tests
    # =========================================================================

    def test_forbidden_actions_defined(self, monkeypatch):
        """Test forbidden actions are defined"""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

        client = TelegramClient()

        assert "buy" in client.FORBIDDEN_ACTIONS
        assert "sell" in client.FORBIDDEN_ACTIONS
        assert "execute" in client.FORBIDDEN_ACTIONS
        assert "live_trade" in client.FORBIDDEN_ACTIONS
        assert "paper_trade" in client.FORBIDDEN_ACTIONS
