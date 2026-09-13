"""
Signal Models - Trading signals from strategies
"""


from datetime import datetime
from enum import Enum, StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from polysignal.utils.time import utc_now


class SignalSide(StrEnum):
    """Signal direction"""
    YES = "yes"
    NO = "no"
    BOTH = "both"  # ONLY for YES/NO combined mispricing paper trading


class SignalStrength(str, Enum):
    """Signal strength"""
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


class ComponentScores(BaseModel):
    """Scores from each engine"""
    microstructure_score: float = Field(0.0, ge=0, le=100)
    liquidity_score: float = Field(0.0, ge=0, le=100)
    event_score: float = Field(50.0, ge=0, le=100)  # Default neutral
    wallet_score: float = Field(50.0, ge=0, le=100)  # Default neutral
    lifecycle_score: float = Field(50.0, ge=0, le=100)  # Default neutral


class Signal(BaseModel):
    """Trading signal"""
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)

    # Market information
    market_id: str
    market_title: str
    market_category: str

    # Strategy information
    strategy_name: str
    strategy_version: str = Field("0.1.0")

    # Signal content
    side: SignalSide
    price: float = Field(..., ge=0, le=1)
    target_price: float | None = None

    # Scores
    component_scores: ComponentScores = Field(default_factory=ComponentScores)
    raw_score: float = Field(0.0, ge=0, le=100)

    # Risk flags
    risk_flags: list[str] = Field(default_factory=list)

    # Explanation
    reason: str = Field("")
    explanation: str = Field("")

    # Metadata
    path_type: str = Field("ultra_fast", description="ultra_fast, fast, slow, research")
    data_source: str = Field("mock")

    def add_risk_flag(self, flag: str) -> None:
        """Add a risk flag"""
        if flag not in self.risk_flags:
            self.risk_flags.append(flag)

    def get_summary(self) -> str:
        """Get signal summary"""
        return (
            f"Signal({self.signal_id[:8]}): {self.strategy_name} "
            f"| {self.market_title[:30]}... | {self.side.value} @ {self.price:.4f} "
            f"| Score: {self.raw_score:.1f}"
        )
