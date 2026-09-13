"""
Event Models - Event Intelligence Engine data models

IMPORTANT: Event Intelligence Engine can only provide auxiliary scoring.
It CANNOT directly trigger trading execution.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from polysignal.utils.time import utc_now


class SuggestedMode(StrEnum):
    """
    Suggested mode from Event Intelligence Engine.

    IMPORTANT: These modes are suggestions only.
    Risk Governor makes all final decisions.

    "trade" is NOT allowed - Event Engine cannot express trading intent.
    """
    IGNORE = "ignore"              # Event is not relevant
    RESEARCH = "research"          # Needs further research
    ALERT_ONLY = "alert_only"      # Alert but no action
    MANUAL_REVIEW = "manual_review"  # Requires human review
    AVOID = "avoid"                # Market should be avoided


class EventAssessment(BaseModel):
    """
    Event Intelligence Engine Assessment.

    IMPORTANT: This assessment can only provide auxiliary scoring.
    It CANNOT directly trigger trading execution.

    Forbidden fields (not allowed in this model):
    - side, size, order, position, buy, sell, action
    """

    # Identification
    assessment_id: str = Field(default_factory=lambda: str(uuid4()))
    market_id: str
    timestamp: datetime = Field(default_factory=utc_now)

    # Core scores (0-100)
    event_score: float = Field(50.0, ge=0, le=100, description="Overall event signal score")
    evidence_strength: float = Field(50.0, ge=0, le=100, description="Strength of evidence")
    market_relevance: float = Field(50.0, ge=0, le=100, description="Relevance to market")
    ambiguity_risk: float = Field(0.0, ge=0, le=100, description="Risk of ambiguity in rules")

    # Suggested mode (NOT trading decision)
    suggested_mode: SuggestedMode = Field(SuggestedMode.RESEARCH)

    # Risk flags
    risk_flags: list[str] = Field(default_factory=list)

    # Explanation
    explanation: str = Field("")

    # Confidence (0-1)
    confidence: float = Field(0.5, ge=0, le=1)

    # LLM metadata
    llm_provider: str = Field("mock")
    llm_latency_seconds: float = Field(0.0)
    llm_success: bool = Field(True)

    def get_summary(self) -> str:
        """Get assessment summary"""
        return (
            f"Event({self.market_id[:8]}): score={self.event_score:.1f} "
            f"| evidence={self.evidence_strength:.1f} "
            f"| relevance={self.market_relevance:.1f} "
            f"| ambiguity={self.ambiguity_risk:.1f} "
            f"| mode={self.suggested_mode.value}"
        )


class MarketRuleAssessment(BaseModel):
    """
    LLM assessment of market rules.

    IMPORTANT: This assessment can only provide analysis.
    It CANNOT directly trigger trading execution.

    Forbidden fields (not allowed in this model):
    - side, size, order, position, buy, sell, action
    """

    # Rule clarity (0-100)
    rule_clarity: float = Field(50.0, ge=0, le=100, description="How clear are the rules")

    # Resolution source
    resolution_source_type: Literal["oracle", "uma", "manual", "committee", "unknown"] = Field("unknown")
    resolution_source_reliability: float = Field(50.0, ge=0, le=100)

    # Ambiguity detection
    has_ambiguity: bool = Field(False)
    ambiguity_keywords: list[str] = Field(default_factory=list)
    ambiguity_explanation: str = Field("")

    # Category classification
    suggested_category: str = Field("unknown")
    is_forbidden_category: bool = Field(False)

    # Confidence (0-1)
    confidence: float = Field(0.5, ge=0, le=1)

    # Explanation
    explanation: str = Field("")


class LLMResponse(BaseModel):
    """
    LLM Provider Response.

    Contains parsed output and metadata.
    """

    # Success status
    success: bool = Field(True)

    # Parsed output (validated against schema)
    parsed_output: BaseModel | None = None

    # Raw output (for debugging)
    raw_output: str | None = None

    # Confidence (0-1)
    confidence: float = Field(0.5, ge=0, le=1)

    # Error information
    error: str | None = None
    error_type: str | None = None  # "invalid_json", "schema_error", "timeout", "llm_error"

    # Retry count
    retry_count: int = Field(0, ge=0)

    # Provider info
    provider: str = Field("")

    # Latency
    latency_seconds: float = Field(0.0, ge=0)

    # Forbidden field detection
    has_forbidden_trading_fields: bool = Field(False)
    forbidden_fields: list[str] = Field(default_factory=list)

    # Fallback info (set by ProviderRouter when fallback occurs)
    fallback_from: str | None = Field(None, description="Original provider before fallback")


# Forbidden trading fields that LLM output must NOT contain
FORBIDDEN_TRADING_FIELDS = {
    "side",
    "size",
    "order",
    "position",
    "buy",
    "sell",
    "action",
}


def check_forbidden_trading_fields(data: dict) -> tuple[bool, list[str]]:
    """
    Check if data contains forbidden trading fields.

    Args:
        data: Dictionary to check

    Returns:
        Tuple of (has_forbidden, list of forbidden field names)
    """
    found = []
    for field in FORBIDDEN_TRADING_FIELDS:
        if field in data:
            found.append(field)
    return len(found) > 0, found


def create_default_assessment(
    market_id: str,
    error_flag: str,
    explanation: str = "",
) -> EventAssessment:
    """
    Create default assessment for error cases.

    IMPORTANT: Default assessment has:
    - event_score = 50 (neutral)
    - confidence = 0
    - suggested_mode = "research" or "avoid"
    - Does NOT trigger paper_trade, manual_review, or any execution action

    Args:
        market_id: Market ID
        error_flag: Error flag to add
        explanation: Error explanation

    Returns:
        Default EventAssessment with error flag
    """
    return EventAssessment(
        market_id=market_id,
        event_score=50.0,  # Neutral score
        evidence_strength=50.0,
        market_relevance=50.0,
        ambiguity_risk=50.0,
        suggested_mode=SuggestedMode.RESEARCH,
        risk_flags=[error_flag],
        explanation=f"LLM analysis failed: {error_flag}. {explanation}",
        confidence=0.0,  # Zero confidence
        llm_success=False,
    )
