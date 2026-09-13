"""
LLM Output Schemas - Pydantic models for LLM output validation

IMPORTANT: These schemas define the structure of LLM output.
LLM output must NOT contain forbidden trading fields:
- side, size, order, position, buy, sell, action

If raw LLM output contains these fields, it should be flagged with
llm_forbidden_trading_instruction risk flag.
"""

from typing import Literal

from pydantic import BaseModel, Field


class EventAnalysisSchema(BaseModel):
    """
    Schema for LLM event analysis output.

    IMPORTANT: This schema does NOT contain trading execution fields.
    LLM cannot express trading intent.
    """

    # Core scores (0-100)
    event_score: float = Field(
        ...,
        ge=0,
        le=100,
        description="Overall event signal score (0-100)",
    )
    evidence_strength: float = Field(
        ...,
        ge=0,
        le=100,
        description="Strength of evidence (0-100)",
    )
    market_relevance: float = Field(
        ...,
        ge=0,
        le=100,
        description="Relevance to market (0-100)",
    )
    ambiguity_risk: float = Field(
        ...,
        ge=0,
        le=100,
        description="Risk of ambiguity in rules (0-100)",
    )

    # Suggested mode (NOT trading decision)
    # "trade" is NOT allowed
    suggested_mode: Literal["ignore", "research", "alert_only", "manual_review", "avoid"] = Field(
        "research",
        description="Suggested mode (NOT trading decision)",
    )

    # Risk flags
    risk_flags: list[str] = Field(
        default_factory=list,
        description="List of risk flags",
    )

    # Explanation
    explanation: str = Field(
        "",
        description="Explanation of the analysis",
    )

    # Confidence (0-1)
    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="Confidence of the analysis (0-1)",
    )


class MarketRuleSchema(BaseModel):
    """
    Schema for LLM market rule parsing output.

    IMPORTANT: This schema does NOT contain trading execution fields.
    LLM cannot express trading intent.
    """

    # Rule clarity (0-100)
    rule_clarity: float = Field(
        ...,
        ge=0,
        le=100,
        description="How clear are the rules (0-100)",
    )

    # Resolution source
    resolution_source_type: Literal["oracle", "uma", "manual", "committee", "unknown"] = Field(
        "unknown",
        description="Type of resolution source",
    )
    resolution_source_reliability: float = Field(
        ...,
        ge=0,
        le=100,
        description="Reliability of resolution source (0-100)",
    )

    # Ambiguity detection
    has_ambiguity: bool = Field(
        False,
        description="Whether the rules have ambiguity",
    )
    ambiguity_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords indicating ambiguity",
    )
    ambiguity_explanation: str = Field(
        "",
        description="Explanation of ambiguity",
    )

    # Category classification
    suggested_category: str = Field(
        "unknown",
        description="Suggested market category",
    )
    is_forbidden_category: bool = Field(
        False,
        description="Whether this is a forbidden category for auto-trading",
    )

    # Confidence (0-1)
    confidence: float = Field(
        ...,
        ge=0,
        le=1,
        description="Confidence of the analysis (0-1)",
    )

    # Explanation
    explanation: str = Field(
        "",
        description="Explanation of the rule analysis",
    )
