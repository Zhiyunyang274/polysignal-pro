"""
Wallet Models - Wallet profile and activity data structures
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from polysignal.utils.time import utc_now


class WalletSpecialization(str, Enum):
    """Wallet trading specialization"""
    CRYPTO = "crypto"
    SPORTS = "sports"
    POLITICS = "politics"
    CELEBRITY = "celebrity"
    GENERALIST = "generalist"


class WatchlistEntry(BaseModel):
    """Watchlist wallet entry"""
    address: str = Field(..., description="Wallet address")
    alias: str | None = Field(None, description="Human-readable alias")
    category: str | None = Field(None, description="Wallet category (whale, researcher, etc.)")
    is_active: bool = Field(True, description="Whether actively monitored")
    added_at: datetime = Field(default_factory=utc_now)
    notes: str | None = None


class WalletActivity(BaseModel):
    """Single wallet activity/trade"""
    wallet_address: str
    market_id: str
    market_category: str
    side: str  # "yes" or "no"
    price: float
    size_usd: float
    timestamp: datetime
    tx_hash: str | None = None
    pnl_usd: float | None = None  # Realized PnL if closed


class WalletActivityHistory(BaseModel):
    """Wallet activity history"""
    wallet_address: str
    activities: list[WalletActivity] = Field(default_factory=list)
    total_trades: int = 0
    total_volume_usd: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    total_pnl_usd: float = 0.0
    first_activity: datetime | None = None
    last_activity: datetime | None = None

    def get_win_rate(self) -> float:
        """Calculate win rate"""
        if self.total_trades == 0:
            return 0.0
        return self.win_count / self.total_trades


class WalletProfile(BaseModel):
    """Wallet profile from historical analysis"""
    wallet_address: str
    alias: str | None = None

    # Basic stats
    total_trades: int = 0
    total_volume_usd: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0

    # Performance
    total_pnl_usd: float = 0.0
    avg_trade_size_usd: float = 0.0
    avg_holding_time_hours: float = 0.0

    # Specialization
    primary_category: WalletSpecialization = WalletSpecialization.GENERALIST
    category_distribution: dict[str, int] = Field(default_factory=dict)

    # Behavior metrics
    copy_ratio: float = 0.0  # 0-1, how much they copy others
    avg_entry_timing: str = "neutral"  # early, mid, late, neutral

    # Risk indicators
    max_drawdown_pct: float = 0.0
    avg_slippage_pct: float = 0.0

    # Component scores (0-100)
    reliability_score: float = 50.0
    performance_score: float = 50.0
    specialization_score: float = 50.0
    discipline_score: float = 50.0

    # Final score
    wallet_score: float = 50.0

    # Metadata
    profile_generated_at: datetime = Field(default_factory=utc_now)
    data_staleness_hours: float = 0.0


class WalletMarketActivity(BaseModel):
    """Wallet activity in a specific market"""
    wallet_address: str
    market_id: str
    side: str  # "yes" or "no"
    price: float
    size_usd: float
    timestamp: datetime
    wallet_score: float  # Wallet's overall score


class WalletConsensus(BaseModel):
    """Wallet consensus for a market"""
    market_id: str
    direction: str | None = None  # "yes", "no", or None if no consensus
    consensus_score: float = 0.0  # 0-100
    active_wallet_count: int = 0
    same_direction_count: int = 0
    same_direction_ratio: float = 0.0
    participating_wallets: list[str] = Field(default_factory=list)


class WalletAssessment(BaseModel):
    """Wallet assessment result for a market"""
    market_id: str

    # Scores
    wallet_score: float = Field(..., ge=0, le=100)
    wallet_consensus_score: float = Field(0.0, ge=0, le=100)
    copy_risk_score: float = Field(0.0, ge=0, le=100)  # 0-100, higher = more risky

    # Consensus info
    consensus: WalletConsensus | None = None

    # Risk flags
    risk_flags: list[str] = Field(default_factory=list)

    # Active wallets
    active_wallets: list[str] = Field(default_factory=list)

    # Explanation
    explanation: str = ""

    # Metadata
    assessed_at: datetime = Field(default_factory=utc_now)

    def get_copy_risk_penalty(self) -> float:
        """Calculate copy risk penalty (0-30)"""
        return self.copy_risk_score * 0.30

    def get_summary(self) -> str:
        """Get assessment summary"""
        return (
            f"Wallet({self.market_id[:8]}): score={self.wallet_score:.1f} "
            f"| consensus={self.wallet_consensus_score:.1f} "
            f"| copy_risk={self.copy_risk_score:.1f}"
        )
