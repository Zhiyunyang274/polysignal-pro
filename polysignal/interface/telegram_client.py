"""
Telegram Client - Signal Cockpit for PolySignal Pro

Telegram is a monitoring and control panel, NOT a trading system.
All trading decisions are made by Risk Governor automatically.

IMPORTANT:
- Lazy loading: Only import python-telegram-bot when enabled
- Graceful fallback: If not configured, fallback to CLI/log mode
- No trading: Telegram cannot trigger live trading
"""

import os
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

import structlog

from polysignal.models.signal import Signal
from polysignal.models.risk import RiskDecision, RiskAction
from polysignal.models.paper_trade import PaperOrder
from polysignal.models.telegram import (
    TelegramAction,
    TelegramActionResult,
    SystemPauseState,
    TelegramAlertMessage,
)


logger = structlog.get_logger()


class TelegramClient:
    """
    Telegram client with lazy loading and graceful degradation.

    This client:
    - Only loads python-telegram-bot when enabled
    - Falls back to CLI/log mode when not configured
    - Cannot trigger live trading
    - Only sends alerts and handles non-trading control actions
    """

    # Forbidden actions that Telegram cannot trigger
    FORBIDDEN_ACTIONS = {
        "buy",
        "sell",
        "execute",
        "live_trade",
        "approve_live",
        "auto_trade",
        "paper_trade",  # System auto-executes, not user-triggered
    }

    # Allowed non-trading actions
    ALLOWED_ACTIONS = {
        TelegramAction.DETAILS,
        TelegramAction.IGNORE_FUTURE,
        TelegramAction.BLACKLIST_MARKET,
        TelegramAction.TRACK_WALLET,
        TelegramAction.VIEW_JOURNAL,
        TelegramAction.PAUSE_ALERTS,
        TelegramAction.RESUME_ALERTS,
        TelegramAction.PAUSE_SIGNALS,
        TelegramAction.RESUME_SIGNALS,
        TelegramAction.MARK_REVIEWED,
    }

    def __init__(self):
        """Initialize Telegram client with lazy loading"""
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.token and self.chat_id)
        self._bot = None
        self._application = None

        # Pause states
        self._alerts_paused = False
        self._signals_paused = False

        if self.enabled:
            logger.info("Telegram client initialized", enabled=True)
        else:
            logger.info(
                "Telegram client initialized",
                enabled=False,
                reason="TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured",
            )

    def _lazy_load_bot(self) -> bool:
        """
        Lazy load the Telegram bot.

        Returns True if bot loaded successfully, False otherwise.
        """
        if self._bot is not None:
            return True

        if not self.enabled:
            return False

        try:
            from telegram import Bot

            self._bot = Bot(token=self.token)
            logger.info("Telegram bot loaded successfully")
            return True
        except ImportError:
            logger.warning(
                "python-telegram-bot not installed, Telegram disabled. "
                "Install with: pip install python-telegram-bot"
            )
            self.enabled = False
            return False
        except Exception as e:
            logger.error(f"Failed to load Telegram bot: {e}")
            self.enabled = False
            return False

    # =========================================================================
    # Pause State Management
    # =========================================================================

    def get_pause_state(self) -> SystemPauseState:
        """Get current pause state"""
        if self._signals_paused:
            return SystemPauseState.SIGNALS_PAUSED
        elif self._alerts_paused:
            return SystemPauseState.ALERTS_PAUSED
        else:
            return SystemPauseState.RUNNING

    def are_alerts_paused(self) -> bool:
        """Check if alerts are paused"""
        return self._alerts_paused

    def are_signals_paused(self) -> bool:
        """Check if signals are paused"""
        return self._signals_paused

    def pause_alerts(self) -> str:
        """Pause Telegram alerts"""
        if self._alerts_paused:
            return "Alerts already paused"
        self._alerts_paused = True
        logger.info("Telegram alerts paused")
        return "✅ Telegram alerts paused. System continues logging and paper trading."

    def resume_alerts(self) -> str:
        """Resume Telegram alerts"""
        if not self._alerts_paused:
            return "Alerts not paused"
        self._alerts_paused = False
        logger.info("Telegram alerts resumed")
        return "✅ Telegram alerts resumed."

    def pause_signals(self) -> str:
        """Pause signal generation and paper trading"""
        if self._signals_paused:
            return "Signals already paused"
        self._signals_paused = True
        logger.info("Signal generation paused")
        return "✅ Signal generation paused. System health monitoring continues."

    def resume_signals(self) -> str:
        """Resume signal generation and paper trading"""
        if not self._signals_paused:
            return "Signals not paused"
        self._signals_paused = False
        logger.info("Signal generation resumed")
        return "✅ Signal generation resumed."

    # =========================================================================
    # Alert Sending
    # =========================================================================

    async def send_alert(
        self,
        signal: Signal,
        decision: RiskDecision,
        paper_order: Optional[PaperOrder] = None,
    ) -> bool:
        """
        Send alert to Telegram.

        Returns True if sent successfully, False otherwise.
        Falls back to CLI/log mode if Telegram is disabled.
        """
        # Check if alerts are paused
        if self._alerts_paused:
            logger.info(
                "Telegram alerts paused, skipping",
                signal_id=signal.signal_id,
            )
            return False

        # Build message
        message = self._build_alert_message(signal, decision, paper_order)

        # Try to send via Telegram
        if not self._lazy_load_bot():
            # Fallback to CLI/log
            logger.info(
                "[TELEGRAM DISABLED] Alert",
                signal_id=signal.signal_id,
                action=decision.action.value,
                trade_score=decision.trade_score,
            )
            return False

        try:
            await self._bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML",
            )
            logger.info(
                "Telegram alert sent",
                signal_id=signal.signal_id,
                action=decision.action.value,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False

    async def send_paper_trade_notification(
        self,
        signal: Signal,
        decision: RiskDecision,
        paper_order: Optional[PaperOrder],
    ) -> bool:
        """Send paper trade execution notification"""
        return await self.send_alert(signal, decision, paper_order)

    async def send_reject_notification(
        self,
        signal: Signal,
        decision: RiskDecision,
    ) -> bool:
        """Send hard reject notification"""
        return await self.send_alert(signal, decision, None)

    async def send_review_request(
        self,
        signal: Signal,
        decision: RiskDecision,
    ) -> bool:
        """Send manual review request"""
        return await self.send_alert(signal, decision, None)

    # =========================================================================
    # Message Building
    # =========================================================================

    def _build_alert_message(
        self,
        signal: Signal,
        decision: RiskDecision,
        paper_order: Optional[PaperOrder] = None,
    ) -> str:
        """Build Telegram alert message"""
        lines = []

        # Header based on action
        if decision.action == RiskAction.PAPER_TRADE:
            lines.append("📦 Paper Trade Executed")
        elif decision.action == RiskAction.HARD_REJECT:
            lines.append("🚫 Signal Rejected")
        elif decision.action == RiskAction.ALERT:
            lines.append("🔔 Signal Alert")
        elif decision.action == RiskAction.MANUAL_REVIEW:
            lines.append("👁️ Signal for Review")
        elif decision.action == RiskAction.IGNORE:
            lines.append("⏭️ Signal Ignored")
        else:
            lines.append(f"📊 Signal: {decision.action.value}")

        lines.append("")

        # Market info
        lines.append(f"<b>Market:</b> {signal.market_title}")
        lines.append(f"<b>Strategy:</b> {signal.strategy_name}")
        lines.append(f"<b>Side:</b> {signal.side.value}")
        lines.append(f"<b>Price:</b> {signal.price:.4f}")
        lines.append("")

        # Component scores
        if hasattr(signal, 'component_scores') and signal.component_scores:
            lines.append("<b>📊 Scores:</b>")
            lines.append(f"  Microstructure: {signal.component_scores.microstructure_score:.1f}")
            lines.append(f"  Liquidity: {signal.component_scores.liquidity_score:.1f}")
            lines.append(f"  Event: {signal.component_scores.event_score:.1f}")
            lines.append(f"  Wallet: {signal.component_scores.wallet_score:.1f}")
            lines.append(f"  Lifecycle: {signal.component_scores.lifecycle_score:.1f}")
            lines.append("")

        lines.append(f"<b>📊 Trade Score:</b> {decision.trade_score:.1f}")
        lines.append("")

        # Decision
        if decision.action == RiskAction.PAPER_TRADE:
            lines.append("✅ <b>Action:</b> PAPER_TRADE (自动执行)")
        elif decision.action == RiskAction.HARD_REJECT:
            lines.append("🚫 <b>Action:</b> HARD_REJECT")
        elif decision.action == RiskAction.ALERT:
            lines.append("⚠️ <b>Action:</b> ALERT")
        elif decision.action == RiskAction.MANUAL_REVIEW:
            lines.append("👁️ <b>Action:</b> MANUAL_REVIEW")
        elif decision.action == RiskAction.IGNORE:
            lines.append("⏭️ <b>Action:</b> IGNORE")

        # Risk flags
        if signal.risk_flags:
            lines.append(f"⚠️ <b>Risk Flags:</b> {', '.join(signal.risk_flags)}")

        # Hard reject reasons
        if decision.hard_reject_reasons:
            lines.append("🚫 <b>Reject Reasons:</b>")
            for reason in decision.hard_reject_reasons:
                lines.append(f"  • {reason}")

        # Paper order info
        if paper_order:
            lines.append("")
            lines.append("<b>📦 Order Status:</b>")
            lines.append(f"  Order ID: <code>{paper_order.order_id}</code>")
            lines.append(f"  Status: {paper_order.status.value}")
            if paper_order.filled_size and paper_order.filled_price:
                lines.append(f"  Filled: {paper_order.filled_size:.4f} @ {paper_order.filled_price:.4f}")

        # Explanation
        if decision.explanation:
            lines.append("")
            lines.append(f"📝 <b>Reason:</b> {decision.explanation}")

        # Timestamp
        lines.append("")
        lines.append(f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

        return "\n".join(lines)

    # =========================================================================
    # Status
    # =========================================================================

    def get_status(self) -> dict[str, Any]:
        """Get Telegram client status"""
        return {
            "enabled": self.enabled,
            "token_configured": bool(self.token),
            "chat_id_configured": bool(self.chat_id),
            "bot_loaded": self._bot is not None,
            "alerts_paused": self._alerts_paused,
            "signals_paused": self._signals_paused,
            "pause_state": self.get_pause_state().value,
        }
