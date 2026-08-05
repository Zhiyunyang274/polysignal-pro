"""
Telegram Models - Data models for Telegram Signal Cockpit

Telegram is a monitoring and control panel, NOT a trading system.
All trading decisions are made by Risk Governor automatically.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TelegramAction(str, Enum):
    """Allowed Telegram actions (non-trading only)"""
    DETAILS = "details"
    IGNORE_FUTURE = "ignore_future"
    BLACKLIST_MARKET = "blacklist_market"
    TRACK_WALLET = "track_wallet"
    VIEW_JOURNAL = "view_journal"
    PAUSE_ALERTS = "pause_alerts"
    RESUME_ALERTS = "resume_alerts"
    PAUSE_SIGNALS = "pause_signals"
    RESUME_SIGNALS = "resume_signals"
    MARK_REVIEWED = "mark_reviewed"


class TelegramActionResult(str, Enum):
    """Result of Telegram action"""
    SUCCESS = "success"
    FAILED = "failed"
    ALREADY_EXISTS = "already_exists"
    REJECTED = "rejected"
    DISABLED = "disabled"


class SystemPauseState(str, Enum):
    """System pause states"""
    RUNNING = "running"
    ALERTS_PAUSED = "alerts_paused"
    SIGNALS_PAUSED = "signals_paused"


class TelegramActionLog(BaseModel):
    """Log entry for Telegram action"""
    action_id: str = Field(..., description="Unique action ID")
    signal_id: Optional[str] = Field(None, description="Associated signal ID")
    action: TelegramAction = Field(..., description="Action type")
    user_id: int = Field(..., description="Telegram user ID")
    username: Optional[str] = Field(None, description="Telegram username")
    market_id: Optional[str] = Field(None, description="Market ID")
    strategy_name: Optional[str] = Field(None, description="Strategy name")
    wallet_address: Optional[str] = Field(None, description="Wallet address")
    result: TelegramActionResult = Field(..., description="Action result")
    result_message: str = Field(..., description="Result message")
    timestamp: str = Field(..., description="Timestamp ISO format")


class IgnoreRule(BaseModel):
    """Rule to ignore future signals"""
    market_id: Optional[str] = Field(None, description="Market ID")
    strategy_name: Optional[str] = Field(None, description="Strategy name")
    added_by: str = Field(..., description="Telegram user ID")
    added_at: str = Field(..., description="Timestamp ISO format")


class BlacklistEntry(BaseModel):
    """Blacklist entry"""
    target_type: str = Field(..., description="Type: market, category, wallet, strategy")
    target_id: str = Field(..., description="Target identifier")
    reason: Optional[str] = Field(None, description="Reason for blacklisting")
    added_by: str = Field(..., description="Telegram user ID")
    added_at: str = Field(..., description="Timestamp ISO format")


class WalletWatchlistRuntime(BaseModel):
    """Runtime wallet watchlist entry (stored in SQLite, not YAML)"""
    wallet_address: str = Field(..., description="Wallet address")
    added_by: str = Field(..., description="Telegram user ID")
    added_at: str = Field(..., description="Timestamp ISO format")
    notes: Optional[str] = Field(None, description="Optional notes")


class SignalReview(BaseModel):
    """Signal review status"""
    signal_id: str = Field(..., description="Signal ID")
    reviewed_by: str = Field(..., description="Telegram user ID")
    reviewed_at: str = Field(..., description="Timestamp ISO format")
    notes: Optional[str] = Field(None, description="Optional notes")


class TelegramAlertMessage(BaseModel):
    """Telegram alert message structure"""
    signal_id: str
    market_title: str
    market_id: str
    strategy_name: str
    side: str
    price: float
    trade_score: float
    component_scores: dict[str, float]
    risk_flags: list[str]
    hard_reject_reasons: list[str]
    action: str
    explanation: str
    paper_order_id: Optional[str] = None
    paper_order_status: Optional[str] = None
    paper_filled_size: Optional[float] = None
    paper_filled_price: Optional[float] = None
    timestamp: str

    def format_message(self) -> str:
        """Format message for Telegram"""
        lines = []

        # Header based on action
        if self.action == "PAPER_TRADE":
            lines.append("📦 Paper Trade Executed")
        elif self.action == "HARD_REJECT":
            lines.append("🚫 Signal Rejected")
        elif self.action == "ALERT":
            lines.append("🔔 Signal Alert")
        elif self.action == "MANUAL_REVIEW":
            lines.append("👁️ Signal for Review")
        else:
            lines.append(f"📊 Signal: {self.action}")

        lines.append("")

        # Market info
        lines.append(f"Market: {self.market_title}")
        lines.append(f"Strategy: {self.strategy_name}")
        lines.append(f"Side: {self.side}")
        lines.append(f"Price: {self.price:.4f}")
        lines.append("")

        # Component scores
        lines.append("📊 Scores:")
        for name, score in self.component_scores.items():
            lines.append(f"  {name}: {score:.1f}")
        lines.append("")
        lines.append(f"📊 Trade Score: {self.trade_score:.1f}")
        lines.append("")

        # Decision
        if self.action == "PAPER_TRADE":
            lines.append("✅ Action: PAPER_TRADE (自动执行)")
        elif self.action == "HARD_REJECT":
            lines.append(f"🚫 Action: HARD_REJECT")
        elif self.action == "ALERT":
            lines.append(f"⚠️ Action: ALERT")
        elif self.action == "MANUAL_REVIEW":
            lines.append(f"👁️ Action: MANUAL_REVIEW")

        # Risk flags
        if self.risk_flags:
            lines.append(f"⚠️ Risk Flags: {', '.join(self.risk_flags)}")

        # Hard reject reasons
        if self.hard_reject_reasons:
            lines.append("🚫 Reject Reasons:")
            for reason in self.hard_reject_reasons:
                lines.append(f"  • {reason}")

        # Paper order info
        if self.paper_order_id:
            lines.append("")
            lines.append("📦 Order Status:")
            lines.append(f"  Order ID: {self.paper_order_id}")
            if self.paper_order_status:
                lines.append(f"  Status: {self.paper_order_status}")
            if self.paper_filled_size and self.paper_filled_price:
                lines.append(f"  Filled: {self.paper_filled_size:.4f} @ {self.paper_filled_price:.4f}")

        # Explanation
        lines.append("")
        lines.append(f"📝 Reason: {self.explanation}")

        # Timestamp
        lines.append("")
        lines.append(f"🕐 {self.timestamp}")

        return "\n".join(lines)
