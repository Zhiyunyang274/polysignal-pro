"""
Paper Trade Models - Paper trading simulation

IMPORTANT: MVP only supports LIMIT orders. MARKET orders are disabled.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from polysignal.utils.time import utc_now


class OrderSide(StrEnum):
    """Order side"""
    BUY_YES = "buy_yes"
    SELL_YES = "sell_yes"
    BUY_NO = "buy_no"
    SELL_NO = "sell_no"


class OrderStatus(StrEnum):
    """Order status"""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PaperOrder(BaseModel):
    """Paper trading order (LIMIT orders only in MVP)"""
    order_id: str = Field(default_factory=lambda: str(uuid4()))
    signal_id: str
    risk_decision_id: str
    timestamp: datetime = Field(default_factory=utc_now)

    # Market information
    market_id: str
    market_title: str

    # Order details
    side: OrderSide
    order_type: str = Field(default="limit", description="Only LIMIT orders in MVP")
    price: float = Field(..., ge=0, le=1)
    size: float = Field(..., gt=0, description="Size in shares")

    # Fill information
    filled_size: float = Field(default=0.0, ge=0)
    filled_price: float | None = None
    slippage: float = Field(default=0.0, ge=0)

    # Status
    status: OrderStatus = OrderStatus.PENDING

    # Timeout
    timeout_seconds: int = Field(default=20)
    expires_at: datetime | None = None

    # Strategy
    strategy_name: str = Field(default="")

    # PnL tracking
    realized_pnl_usd: float | None = None

    def is_filled(self) -> bool:
        """Check if order is fully filled"""
        return self.status == OrderStatus.FILLED

    def is_active(self) -> bool:
        """Check if order is still active"""
        return self.status in {OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED}

    def get_fill_pct(self) -> float:
        """Get fill percentage"""
        if self.size <= 0:
            return 0.0
        return (self.filled_size / self.size) * 100


class PaperPosition(BaseModel):
    """Paper trading position"""
    position_id: str = Field(default_factory=lambda: str(uuid4()))
    market_id: str
    market_title: str

    # Position details
    side: OrderSide
    size: float = Field(default=0.0, ge=0)
    avg_entry_price: float = Field(default=0.0, ge=0, le=1)

    # Mark-to-market
    current_price: float = Field(default=0.0, ge=0, le=1)

    # PnL
    unrealized_pnl_usd: float = Field(default=0.0)
    realized_pnl_usd: float = Field(default=0.0)

    # Metadata
    opened_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def update_price(self, current_price: float) -> None:
        """Update current price and unrealized PnL"""
        self.current_price = current_price
        self.updated_at = utc_now()

        if self.size > 0 and self.avg_entry_price > 0:
            # Calculate unrealized PnL based on position side
            if self.side in {OrderSide.BUY_YES, OrderSide.BUY_NO}:
                # A purchased outcome token profits when that token price rises.
                self.unrealized_pnl_usd = self.size * (current_price - self.avg_entry_price)
            else:
                # A sold outcome token profits when that token price falls.
                self.unrealized_pnl_usd = self.size * (self.avg_entry_price - current_price)

    def get_total_pnl_usd(self) -> float:
        """Get total PnL"""
        return self.realized_pnl_usd + self.unrealized_pnl_usd


class PaperTradeStats(BaseModel):
    """Paper trading statistics"""
    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    losing_trades: int = Field(default=0, ge=0)
    total_pnl_usd: float = Field(default=0.0)
    win_rate: float = Field(default=0.0, ge=0, le=1)
    avg_win_usd: float = Field(default=0.0)
    avg_loss_usd: float = Field(default=0.0)
    max_drawdown_usd: float = Field(default=0.0)
    sharpe_ratio: float | None = None

    def update_from_trades(self, trades: list[PaperOrder]) -> None:
        """Update statistics from trade list"""
        if not trades:
            return

        self.total_trades = len(trades)
        pnls = [t.realized_pnl_usd for t in trades if t.realized_pnl_usd is not None]

        if pnls:
            self.total_pnl_usd = sum(pnls)
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]

            self.winning_trades = len(wins)
            self.losing_trades = len(losses)

            if self.total_trades > 0:
                self.win_rate = self.winning_trades / self.total_trades

            if wins:
                self.avg_win_usd = sum(wins) / len(wins)
            if losses:
                self.avg_loss_usd = sum(losses) / len(losses)
