"""
Test Fixtures - Event Intelligence test data
"""

from __future__ import annotations

from datetime import datetime, timedelta

from polysignal.models.event import (
    EventAssessment,
    MarketRuleAssessment,
    SuggestedMode,
)
from polysignal.models.market import Market, MarketCategory, MarketStatus
from polysignal.llm.mock_provider import MockScenario


def create_event_market(
    market_id: str = "event_test_001",
    title: str = "Will Bitcoin reach $100,000 by 2025?",
    description: str = "This market resolves to YES if Bitcoin reaches $100,000 USD before January 1, 2026.",
    category: MarketCategory = MarketCategory.CRYPTO,
    is_ambiguous: bool = False,
) -> Market:
    """Create a test market for event testing"""
    return Market(
        market_id=market_id,
        title=title,
        description=description,
        category=category,
        status=MarketStatus.OPEN,
        total_volume_usd=500000,
        volume_24h_usd=200000,
        close_time=datetime.utcnow() + timedelta(days=30),
        is_ambiguous=is_ambiguous,
    )


def create_ambiguous_market() -> Market:
    """Create an ambiguous market for testing"""
    return create_event_market(
        market_id="ambiguous_test_001",
        title="Will something interesting happen?",
        description="This market is intentionally vague.",
        is_ambiguous=True,
    )


def create_politics_event_market() -> Market:
    """Create a politics market (forbidden category) for testing"""
    return create_event_market(
        market_id="politics_test_001",
        title="Will Candidate X win the election?",
        description="Election market",
        category=MarketCategory.POLITICS,
    )


def create_event_assessment(
    market_id: str = "event_test_001",
    event_score: float = 75.0,
    evidence_strength: float = 80.0,
    market_relevance: float = 70.0,
    ambiguity_risk: float = 20.0,
    suggested_mode: SuggestedMode = SuggestedMode.RESEARCH,
    risk_flags: list[str] = None,
    confidence: float = 0.8,
    llm_success: bool = True,
) -> EventAssessment:
    """Create a test event assessment"""
    if risk_flags is None:
        risk_flags = []
    return EventAssessment(
        market_id=market_id,
        event_score=event_score,
        evidence_strength=evidence_strength,
        market_relevance=market_relevance,
        ambiguity_risk=ambiguity_risk,
        suggested_mode=suggested_mode,
        risk_flags=risk_flags,
        explanation="Test event assessment",
        confidence=confidence,
        llm_success=llm_success,
    )


def create_high_event_score_assessment() -> EventAssessment:
    """Create assessment with high event score"""
    return create_event_assessment(
        event_score=85.0,
        evidence_strength=90.0,
        market_relevance=85.0,
        ambiguity_risk=10.0,
        suggested_mode=SuggestedMode.ALERT_ONLY,
        confidence=0.9,
    )


def create_low_event_score_assessment() -> EventAssessment:
    """Create assessment with low event score"""
    return create_event_assessment(
        event_score=30.0,
        evidence_strength=25.0,
        market_relevance=35.0,
        ambiguity_risk=60.0,
        suggested_mode=SuggestedMode.IGNORE,
        confidence=0.6,
    )


def create_high_ambiguity_assessment() -> EventAssessment:
    """Create assessment with high ambiguity risk"""
    return create_event_assessment(
        event_score=50.0,
        evidence_strength=40.0,
        market_relevance=50.0,
        ambiguity_risk=80.0,
        suggested_mode=SuggestedMode.MANUAL_REVIEW,
        risk_flags=["event_high_ambiguity"],
        confidence=0.5,
    )


def create_weak_evidence_assessment() -> EventAssessment:
    """Create assessment with weak evidence"""
    return create_event_assessment(
        event_score=40.0,
        evidence_strength=25.0,
        market_relevance=50.0,
        ambiguity_risk=30.0,
        suggested_mode=SuggestedMode.RESEARCH,
        risk_flags=["event_weak_evidence"],
        confidence=0.4,
    )


def create_forbidden_category_assessment() -> EventAssessment:
    """Create assessment detecting forbidden category"""
    return create_event_assessment(
        event_score=50.0,
        suggested_mode=SuggestedMode.AVOID,
        risk_flags=["event_forbidden_category"],
        confidence=0.8,
    )


def create_llm_error_assessment(
    market_id: str = "event_test_001",
    error_flag: str = "llm_error",
) -> EventAssessment:
    """Create assessment for LLM error case"""
    from polysignal.models.event import create_default_assessment
    return create_default_assessment(
        market_id=market_id,
        error_flag=error_flag,
        explanation="Test LLM error",
    )


def create_market_rule_assessment(
    rule_clarity: float = 80.0,
    resolution_source_type: str = "oracle",
    resolution_source_reliability: float = 85.0,
    has_ambiguity: bool = False,
    is_forbidden_category: bool = False,
    confidence: float = 0.8,
) -> MarketRuleAssessment:
    """Create a test market rule assessment"""
    return MarketRuleAssessment(
        rule_clarity=rule_clarity,
        resolution_source_type=resolution_source_type,
        resolution_source_reliability=resolution_source_reliability,
        has_ambiguity=has_ambiguity,
        ambiguity_keywords=["unclear"] if has_ambiguity else [],
        ambiguity_explanation="Detected ambiguity" if has_ambiguity else "",
        suggested_category="crypto",
        is_forbidden_category=is_forbidden_category,
        confidence=confidence,
    )
