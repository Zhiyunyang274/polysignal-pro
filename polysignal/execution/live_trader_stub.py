"""

from __future__ import annotations
Live Trader Stub - Interface for live trading (NOT IMPLEMENTED IN MVP)

IMPORTANT: This is a STUB. It does NOT execute real orders.
Live trading will be implemented in Milestone 3 with proper safeguards.
"""

from typing import Any

from polysignal.models.signal import Signal
from polysignal.models.risk import RiskDecision
from polysignal.models.paper_trade import PaperOrder, OrderStatus


class LiveTraderStub:
    """
    Live Trader Stub - Does NOT execute real orders.

    This is a placeholder for future live trading implementation.
    MVP does NOT support live trading.

    When implemented, it must:
    - Require explicit feature flag
    - Only support LIMIT orders
    - Only support test wallets
    - Only support small amounts
    - Require Risk Governor approval
    - Full audit logging
    """

    def __init__(self, live_trading_enabled: bool = False):
        """
        Initialize live trader stub.

        Args:
            live_trading_enabled: Whether live trading is enabled (default False)
        """
        self.live_trading_enabled = live_trading_enabled

    def execute(
        self,
        signal: Signal,
        risk_decision: RiskDecision,
        **kwargs: Any,
    ) -> PaperOrder:
        """
        Execute a live trade (STUB - does nothing).

        This always returns a stub order that indicates live trading is not available.
        """
        # Create a stub order indicating not implemented
        return PaperOrder(
            signal_id=signal.signal_id,
            risk_decision_id=risk_decision.decision_id,
            market_id=signal.market_id,
            market_title=signal.market_title,
            side="stub",
            price=signal.price,
            size=0,
            status=OrderStatus.CANCELLED,
            strategy_name=signal.strategy_name,
        )

    def is_available(self) -> bool:
        """Check if live trading is available"""
        return False  # Always False in MVP

    def get_status(self) -> dict[str, Any]:
        """Get live trader status"""
        return {
            "available": False,
            "live_trading_enabled": self.live_trading_enabled,
            "message": "Live trading is not implemented in MVP. Use Paper Trader instead.",
        }
