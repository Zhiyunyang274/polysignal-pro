"""
Telegram Action Handler - Handle non-trading control actions

This handler processes Telegram button actions for:
- Details view
- Ignore future signals
- Blacklist market
- Track wallet
- Pause/Resume alerts
- Pause/Resume signals
- Mark reviewed

IMPORTANT: This handler cannot trigger trading actions.
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

import structlog

from polysignal.models.telegram import (
    TelegramAction,
    TelegramActionResult,
)
from polysignal.interface.telegram_client import TelegramClient
from polysignal.storage.database import Database


logger = structlog.get_logger()


class TelegramActionHandler:
    """
    Handler for Telegram button actions.

    Only handles non-trading control actions.
    Cannot trigger live trading or paper trading.
    """

    def __init__(
        self,
        telegram_client: TelegramClient,
        db: Database,
    ):
        """
        Initialize handler.

        Args:
            telegram_client: Telegram client instance
            db: Database instance
        """
        self.telegram_client = telegram_client
        self.db = db

    # =========================================================================
    # Action Handling
    # =========================================================================

    async def handle_action(
        self,
        action: str,
        user_id: int,
        username: Optional[str] = None,
        signal_id: Optional[str] = None,
        market_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        wallet_address: Optional[str] = None,
    ) -> tuple[TelegramActionResult, str]:
        """
        Handle a Telegram action.

        Returns:
            Tuple of (result, message)
        """
        # Check for forbidden actions
        if action in TelegramClient.FORBIDDEN_ACTIONS:
            logger.warning(
                "Forbidden Telegram action attempted",
                action=action,
                user_id=user_id,
            )
            return TelegramActionResult.REJECTED, f"Action '{action}' is forbidden"

        # Validate action
        try:
            telegram_action = TelegramAction(action)
        except ValueError:
            return TelegramActionResult.FAILED, f"Unknown action '{action}'"

        # Handle each action
        handler_map = {
            TelegramAction.DETAILS: self._handle_details,
            TelegramAction.IGNORE_FUTURE: self._handle_ignore_future,
            TelegramAction.BLACKLIST_MARKET: self._handle_blacklist,
            TelegramAction.TRACK_WALLET: self._handle_track_wallet,
            TelegramAction.PAUSE_ALERTS: self._handle_pause_alerts,
            TelegramAction.RESUME_ALERTS: self._handle_resume_alerts,
            TelegramAction.PAUSE_SIGNALS: self._handle_pause_signals,
            TelegramAction.RESUME_SIGNALS: self._handle_resume_signals,
            TelegramAction.MARK_REVIEWED: self._handle_mark_reviewed,
            TelegramAction.VIEW_JOURNAL: self._handle_view_journal,
        }

        handler = handler_map.get(telegram_action)
        if not handler:
            return TelegramActionResult.FAILED, f"No handler for action '{action}'"

        return await handler(
            user_id=user_id,
            username=username,
            signal_id=signal_id,
            market_id=market_id,
            strategy_name=strategy_name,
            wallet_address=wallet_address,
        )

    # =========================================================================
    # Individual Action Handlers
    # =========================================================================

    async def _handle_details(
        self,
        user_id: int,
        username: Optional[str],
        signal_id: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Details action"""
        if not signal_id:
            return TelegramActionResult.FAILED, "Signal ID required"

        signal = await self.db.get_signal(signal_id)
        if not signal:
            return TelegramActionResult.FAILED, f"Signal {signal_id} not found"

        decision = await self.db.get_risk_decision(signal_id)

        # Log action
        await self._log_action(
            action=TelegramAction.DETAILS,
            user_id=user_id,
            username=username,
            signal_id=signal_id,
            result=TelegramActionResult.SUCCESS,
            result_message="Details viewed",
        )

        # Build details message
        lines = [
            f"📋 <b>Signal Details</b>",
            "",
            f"<b>Signal ID:</b> <code>{signal_id}</code>",
            f"<b>Market:</b> {signal.market_title}",
            f"<b>Market ID:</b> <code>{signal.market_id}</code>",
            f"<b>Category:</b> {signal.market_category}",
            f"<b>Strategy:</b> {signal.strategy_name}",
            f"<b>Side:</b> {signal.side.value}",
            f"<b>Price:</b> {signal.price:.4f}",
            "",
        ]

        if hasattr(signal, 'component_scores') and signal.component_scores:
            lines.append("<b>Component Scores:</b>")
            lines.append(f"  • Microstructure: {signal.component_scores.microstructure_score:.1f}")
            lines.append(f"  • Liquidity: {signal.component_scores.liquidity_score:.1f}")
            lines.append(f"  • Event: {signal.component_scores.event_score:.1f}")
            lines.append(f"  • Wallet: {signal.component_scores.wallet_score:.1f}")
            lines.append(f"  • Lifecycle: {signal.component_scores.lifecycle_score:.1f}")
            lines.append("")

        if signal.risk_flags:
            lines.append(f"<b>Risk Flags:</b> {', '.join(signal.risk_flags)}")

        if decision:
            lines.append("")
            lines.append(f"<b>Trade Score:</b> {decision.trade_score:.1f}")
            lines.append(f"<b>Action:</b> {decision.action.value}")
            if decision.hard_reject_reasons:
                lines.append(f"<b>Hard Reject Reasons:</b> {', '.join(decision.hard_reject_reasons)}")

        return TelegramActionResult.SUCCESS, "\n".join(lines)

    async def _handle_ignore_future(
        self,
        user_id: int,
        username: Optional[str],
        market_id: Optional[str],
        strategy_name: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Ignore Future action"""
        if not market_id and not strategy_name:
            return TelegramActionResult.FAILED, "Market ID or strategy name required"

        # Add ignore rule
        added = await self.db.add_ignore_rule(
            market_id=market_id,
            strategy_name=strategy_name,
            added_by=str(user_id),
        )

        result = TelegramActionResult.SUCCESS if added else TelegramActionResult.ALREADY_EXISTS
        message = (
            f"✅ Future signals from {market_id or 'all markets'} / {strategy_name or 'all strategies'} will be ignored."
            if added
            else f"⚠️ Ignore rule already exists for {market_id or 'all'} / {strategy_name or 'all'}"
        )

        # Log action
        await self._log_action(
            action=TelegramAction.IGNORE_FUTURE,
            user_id=user_id,
            username=username,
            market_id=market_id,
            strategy_name=strategy_name,
            result=result,
            result_message=message,
        )

        return result, message

    async def _handle_blacklist(
        self,
        user_id: int,
        username: Optional[str],
        market_id: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Blacklist Market action"""
        if not market_id:
            return TelegramActionResult.FAILED, "Market ID required"

        # Add to blacklist
        added = await self.db.add_blacklist(
            target_type="market",
            target_id=market_id,
            added_by=str(user_id),
            reason="Blacklisted via Telegram",
        )

        result = TelegramActionResult.SUCCESS if added else TelegramActionResult.ALREADY_EXISTS
        message = (
            f"✅ Market {market_id} added to blacklist. Future signals will be hard rejected."
            if added
            else f"⚠️ Market {market_id} is already blacklisted"
        )

        # Log action
        await self._log_action(
            action=TelegramAction.BLACKLIST_MARKET,
            user_id=user_id,
            username=username,
            market_id=market_id,
            result=result,
            result_message=message,
        )

        return result, message

    async def _handle_track_wallet(
        self,
        user_id: int,
        username: Optional[str],
        wallet_address: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Track Wallet action"""
        if not wallet_address:
            return TelegramActionResult.FAILED, "Wallet address required"

        # Add to runtime watchlist (not YAML)
        added = await self.db.add_wallet_to_watchlist(
            wallet_address=wallet_address,
            added_by=str(user_id),
        )

        result = TelegramActionResult.SUCCESS if added else TelegramActionResult.ALREADY_EXISTS
        message = (
            f"✅ Wallet {wallet_address} added to watchlist."
            if added
            else f"⚠️ Wallet {wallet_address} is already in watchlist"
        )

        # Log action
        await self._log_action(
            action=TelegramAction.TRACK_WALLET,
            user_id=user_id,
            username=username,
            wallet_address=wallet_address,
            result=result,
            result_message=message,
        )

        return result, message

    async def _handle_pause_alerts(
        self,
        user_id: int,
        username: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Pause Alerts action"""
        message = self.telegram_client.pause_alerts()

        # Log action
        await self._log_action(
            action=TelegramAction.PAUSE_ALERTS,
            user_id=user_id,
            username=username,
            result=TelegramActionResult.SUCCESS,
            result_message=message,
        )

        return TelegramActionResult.SUCCESS, message

    async def _handle_resume_alerts(
        self,
        user_id: int,
        username: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Resume Alerts action"""
        message = self.telegram_client.resume_alerts()

        # Log action
        await self._log_action(
            action=TelegramAction.RESUME_ALERTS,
            user_id=user_id,
            username=username,
            result=TelegramActionResult.SUCCESS,
            result_message=message,
        )

        return TelegramActionResult.SUCCESS, message

    async def _handle_pause_signals(
        self,
        user_id: int,
        username: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Pause Signals action"""
        message = self.telegram_client.pause_signals()

        # Log action
        await self._log_action(
            action=TelegramAction.PAUSE_SIGNALS,
            user_id=user_id,
            username=username,
            result=TelegramActionResult.SUCCESS,
            result_message=message,
        )

        return TelegramActionResult.SUCCESS, message

    async def _handle_resume_signals(
        self,
        user_id: int,
        username: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Resume Signals action"""
        message = self.telegram_client.resume_signals()

        # Log action
        await self._log_action(
            action=TelegramAction.RESUME_SIGNALS,
            user_id=user_id,
            username=username,
            result=TelegramActionResult.SUCCESS,
            result_message=message,
        )

        return TelegramActionResult.SUCCESS, message

    async def _handle_mark_reviewed(
        self,
        user_id: int,
        username: Optional[str],
        signal_id: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle Mark Reviewed action"""
        if not signal_id:
            return TelegramActionResult.FAILED, "Signal ID required"

        # Check if already reviewed
        if await self.db.is_signal_reviewed(signal_id):
            return TelegramActionResult.ALREADY_EXISTS, f"⚠️ Signal {signal_id} already reviewed"

        # Mark as reviewed
        await self.db.mark_signal_reviewed(
            signal_id=signal_id,
            reviewed_by=str(user_id),
        )

        message = f"✅ Signal {signal_id} marked as reviewed."

        # Log action
        await self._log_action(
            action=TelegramAction.MARK_REVIEWED,
            user_id=user_id,
            username=username,
            signal_id=signal_id,
            result=TelegramActionResult.SUCCESS,
            result_message=message,
        )

        return TelegramActionResult.SUCCESS, message

    async def _handle_view_journal(
        self,
        user_id: int,
        username: Optional[str],
        market_id: Optional[str],
        **kwargs,
    ) -> tuple[TelegramActionResult, str]:
        """Handle View Journal action"""
        # Get recent orders
        orders = await self.db.get_recent_orders(limit=10)

        if not orders:
            return TelegramActionResult.SUCCESS, "📋 No paper orders found."

        # Build journal message
        lines = ["📋 <b>Paper Trade Journal</b>", ""]
        for order in orders:
            lines.append(f"• {order.market_title}")
            lines.append(f"  Side: {order.side.value}, Price: {order.price:.4f}")
            lines.append(f"  Status: {order.status.value}")
            lines.append(f"  Time: {order.timestamp.strftime('%Y-%m-%d %H:%M')}")
            lines.append("")

        # Log action
        await self._log_action(
            action=TelegramAction.VIEW_JOURNAL,
            user_id=user_id,
            username=username,
            market_id=market_id,
            result=TelegramActionResult.SUCCESS,
            result_message="Journal viewed",
        )

        return TelegramActionResult.SUCCESS, "\n".join(lines)

    # =========================================================================
    # Logging
    # =========================================================================

    async def _log_action(
        self,
        action: TelegramAction,
        user_id: int,
        username: Optional[str],
        result: TelegramActionResult,
        result_message: str,
        signal_id: Optional[str] = None,
        market_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        wallet_address: Optional[str] = None,
    ) -> None:
        """Log Telegram action to database"""
        action_id = str(uuid4())

        await self.db.log_telegram_action(
            action_id=action_id,
            action=action.value,
            user_id=user_id,
            result=result.value,
            result_message=result_message,
            signal_id=signal_id,
            username=username,
            market_id=market_id,
            strategy_name=strategy_name,
            wallet_address=wallet_address,
        )

        logger.info(
            "Telegram action logged",
            action_id=action_id,
            action=action.value,
            user_id=user_id,
            result=result.value,
        )