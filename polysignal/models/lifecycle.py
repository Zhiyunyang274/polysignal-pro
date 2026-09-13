"""
Lifecycle Models - Market lifecycle and resolution risk assessment
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from polysignal.utils.time import utc_now


class LifecyclePhase(str, Enum):
    """Market lifecycle phase"""
    EARLY = "early"           # Just opened, < 10% time elapsed
    MID = "mid"               # Middle phase, 10-80% time elapsed
    LATE = "late"             # Late phase, 80-95% time elapsed
    CLOSING = "closing"       # Closing soon, > 95% time elapsed
    CLOSED = "closed"         # Market closed
    RESOLVED = "resolved"     # Market resolved


class AmbiguityLevel(str, Enum):
    """Ambiguity risk level"""
    NONE = "none"             # No ambiguity
    LOW = "low"               # Low ambiguity
    MEDIUM = "medium"         # Medium ambiguity
    HIGH = "high"             # High ambiguity
    CRITICAL = "critical"     # Critical ambiguity, must hard reject


class ResolutionRiskLevel(str, Enum):
    """Resolution risk level"""
    NONE = "none"             # Clear and reliable resolution source
    LOW = "low"               # Mostly clear resolution source
    MEDIUM = "medium"         # Some uncertainty in resolution
    HIGH = "high"             # Unclear resolution source
    CRITICAL = "critical"     # Severely unclear resolution


class LifecycleAssessment(BaseModel):
    """Lifecycle assessment result from Resolution & Lifecycle Engine"""
    market_id: str

    # Phase
    phase: LifecyclePhase
    time_remaining_pct: float | None = Field(None, ge=0, le=1)

    # Score (0-100)
    lifecycle_score: float = Field(..., ge=0, le=100)

    # Risk scores (0-1)
    ambiguity_risk: float = Field(..., ge=0, le=1)
    resolution_risk: float = Field(..., ge=0, le=1)
    close_time_risk: float = Field(..., ge=0, le=1)

    # Status
    is_tradable: bool
    is_auto_allowed: bool

    # Flags
    hard_reject_reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)

    # Levels
    ambiguity_level: AmbiguityLevel = AmbiguityLevel.NONE
    resolution_risk_level: ResolutionRiskLevel = ResolutionRiskLevel.NONE

    # Explanation
    explanation: str = ""

    # Metadata
    assessed_at: datetime = Field(default_factory=utc_now)

    def get_summary(self) -> str:
        """Get assessment summary"""
        return (
            f"Lifecycle({self.market_id[:8]}): {self.phase.value} "
            f"| score={self.lifecycle_score:.1f} "
            f"| tradable={self.is_tradable} "
            f"| ambiguity={self.ambiguity_risk:.2f} "
            f"| resolution={self.resolution_risk:.2f}"
        )
