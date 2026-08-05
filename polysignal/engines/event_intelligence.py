"""
Event Intelligence Engine - Event analysis and market rule parsing

IMPORTANT: Event Intelligence Engine can only provide auxiliary scoring.
It CANNOT directly trigger trading execution.
It CANNOT decide hard reject (only Risk Governor can).

Key responsibilities:
1. Parse market title/description/resolution rules
2. Analyze event relevance and evidence strength
3. Detect ambiguity risk
4. Generate structured EventAssessment

Output flows to:
- Signal.component_scores.event_score
- Signal.risk_flags (event-related flags)

Risk Governor makes all final decisions.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from polysignal.models.event import (
    EventAssessment,
    MarketRuleAssessment,
    SuggestedMode,
    LLMResponse,
    create_default_assessment,
    check_forbidden_trading_fields,
)
from polysignal.models.market import Market
from polysignal.llm.base import LLMProvider
from polysignal.llm.mock_provider import MockLLMProvider, MockScenario
from polysignal.llm.schemas import EventAnalysisSchema, MarketRuleSchema


class EventIntelligenceEngine:
    """
    Event Intelligence Engine.

    IMPORTANT:
    - Can only provide auxiliary scoring
    - CANNOT directly trigger trading execution
    - CANNOT decide hard reject (only Risk Governor can)
    - LLM output must be validated and checked for forbidden fields
    """

    # Minimum confidence threshold
    MIN_CONFIDENCE = 0.5

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        scenario: MockScenario = MockScenario.SUCCESS,
    ):
        """
        Initialize Event Intelligence Engine.

        Args:
            llm_provider: LLM provider to use (default: MockLLMProvider)
            scenario: Mock scenario (for testing)
        """
        self.llm_provider = llm_provider or MockLLMProvider(scenario=scenario)
        self._assessment_count = 0

    def get_status(self) -> dict:
        """Get engine status"""
        return {
            "engine": "EventIntelligenceEngine",
            "llm_provider": self.llm_provider.get_provider_name(),
            "assessment_count": self._assessment_count,
            "min_confidence": self.MIN_CONFIDENCE,
        }

    def assess(
        self,
        market: Market,
        event_context: Optional[str] = None,
    ) -> EventAssessment:
        """
        Assess market for event intelligence.

        This is a synchronous wrapper for async assess method.

        Args:
            market: Market to assess
            event_context: Optional additional event context

        Returns:
            EventAssessment with scores and flags
        """
        import asyncio
        return asyncio.run(self.assess_async(market, event_context))

    async def assess_async(
        self,
        market: Market,
        event_context: Optional[str] = None,
    ) -> EventAssessment:
        """
        Assess market for event intelligence (async).

        Args:
            market: Market to assess
            event_context: Optional additional event context

        Returns:
            EventAssessment with scores and flags
        """
        self._assessment_count += 1
        start_time = time.time()

        # Build prompt for LLM
        prompt = self._build_prompt(market, event_context)

        # Call LLM
        response = await self.llm_provider.analyze(
            prompt=prompt,
            response_schema=EventAnalysisSchema,
        )

        latency = time.time() - start_time

        # Handle LLM response
        return self._process_response(market.market_id, response, latency)

    def _build_prompt(self, market: Market, event_context: Optional[str]) -> str:
        """Build prompt for LLM analysis"""
        prompt_parts = [
            f"Market ID: {market.market_id}",
            f"Title: {market.title}",
            f"Description: {market.description}",
            f"Category: {market.category.value}",
            f"Status: {market.status.value}",
        ]

        if market.resolution_source:
            prompt_parts.append(f"Resolution Source: {market.resolution_source}")

        if event_context:
            prompt_parts.append(f"Event Context: {event_context}")

        # Add market-specific keywords for mock detection
        if market.is_ambiguous:
            prompt_parts.append("Note: Market is marked as ambiguous")

        return "\n".join(prompt_parts)

    def _process_response(
        self,
        market_id: str,
        response: LLMResponse,
        latency: float,
    ) -> EventAssessment:
        """
        Process LLM response and create EventAssessment.

        Handles various error cases:
        - Invalid JSON
        - Schema validation failure
        - Low confidence
        - Missing fields
        - Forbidden trading fields

        IMPORTANT: Default assessment (on error) has:
        - event_score = 50 (neutral)
        - confidence = 0
        - suggested_mode = "research"
        - Does NOT trigger paper_trade, manual_review, or any execution action
        """
        # Handle LLM failure cases
        if not response.success:
            return self._handle_failure(market_id, response, latency)

        # Handle low confidence
        if response.confidence < self.MIN_CONFIDENCE:
            return create_default_assessment(
                market_id=market_id,
                error_flag="llm_low_confidence",
                explanation=f"Confidence {response.confidence:.2f} below threshold {self.MIN_CONFIDENCE}",
            )

        # Handle forbidden trading fields
        if response.has_forbidden_trading_fields:
            return create_default_assessment(
                market_id=market_id,
                error_flag="llm_forbidden_trading_instruction",
                explanation=f"LLM output contains forbidden trading fields: {response.forbidden_fields}",
            )

        # Parse successful response
        if response.parsed_output is None:
            return create_default_assessment(
                market_id=market_id,
                error_flag="llm_no_parsed_output",
                explanation="LLM response has no parsed output",
            )

        parsed = response.parsed_output

        # Build EventAssessment from parsed output
        risk_flags = list(parsed.risk_flags)

        # Add risk flags based on scores
        if parsed.ambiguity_risk >= 70:
            if "event_high_ambiguity" not in risk_flags:
                risk_flags.append("event_high_ambiguity")

        if parsed.evidence_strength < 40:
            if "event_weak_evidence" not in risk_flags:
                risk_flags.append("event_weak_evidence")

        if parsed.market_relevance < 40:
            if "event_low_relevance" not in risk_flags:
                risk_flags.append("event_low_relevance")

        return EventAssessment(
            market_id=market_id,
            event_score=parsed.event_score,
            evidence_strength=parsed.evidence_strength,
            market_relevance=parsed.market_relevance,
            ambiguity_risk=parsed.ambiguity_risk,
            suggested_mode=SuggestedMode(parsed.suggested_mode),
            risk_flags=risk_flags,
            explanation=parsed.explanation,
            confidence=parsed.confidence,
            llm_provider=response.provider,
            llm_latency_seconds=latency,
            llm_success=True,
        )

    def _handle_failure(
        self,
        market_id: str,
        response: LLMResponse,
        latency: float,
    ) -> EventAssessment:
        """
        Handle LLM failure.

        Maps error types to appropriate error flags.
        Returns default assessment with:
        - event_score = 50 (neutral)
        - confidence = 0
        - suggested_mode = "research"
        """
        error_type = response.error_type or "llm_error"

        error_flag_map = {
            "invalid_json": "llm_invalid_json",
            "schema_error": "llm_schema_validation_failed",
            "timeout": "llm_timeout",
            "llm_error": "llm_error",
        }

        error_flag = error_flag_map.get(error_type, "llm_error")

        return create_default_assessment(
            market_id=market_id,
            error_flag=error_flag,
            explanation=response.error or "Unknown LLM error",
        )

    async def analyze_market_rules(
        self,
        market: Market,
    ) -> MarketRuleAssessment:
        """
        Analyze market rules using LLM.

        Args:
            market: Market to analyze

        Returns:
            MarketRuleAssessment with rule analysis
        """
        prompt = self._build_rule_prompt(market)

        response = await self.llm_provider.analyze(
            prompt=prompt,
            response_schema=MarketRuleSchema,
        )

        return self._process_rule_response(response)

    def _build_rule_prompt(self, market: Market) -> str:
        """Build prompt for rule analysis"""
        return "\n".join([
            f"Analyze market rules for: {market.title}",
            f"Description: {market.description}",
            f"Category: {market.category.value}",
            f"Resolution Source: {market.resolution_source or 'Unknown'}",
        ])

    def _process_rule_response(self, response: LLMResponse) -> MarketRuleAssessment:
        """Process rule analysis response"""
        if not response.success or response.parsed_output is None:
            return MarketRuleAssessment(
                rule_clarity=50.0,
                resolution_source_reliability=50.0,
                confidence=0.0,
                explanation=f"LLM analysis failed: {response.error}",
            )

        parsed = response.parsed_output

        return MarketRuleAssessment(
            rule_clarity=parsed.rule_clarity,
            resolution_source_type=parsed.resolution_source_type,
            resolution_source_reliability=parsed.resolution_source_reliability,
            has_ambiguity=parsed.has_ambiguity,
            ambiguity_keywords=list(parsed.ambiguity_keywords),
            ambiguity_explanation=parsed.ambiguity_explanation,
            suggested_category=parsed.suggested_category,
            is_forbidden_category=parsed.is_forbidden_category,
            confidence=parsed.confidence,
            explanation=parsed.explanation,
        )

    # =========================================================================
    # Score Calculation Helpers
    # =========================================================================

    @staticmethod
    def calculate_event_score(
        evidence_strength: float,
        market_relevance: float,
        ambiguity_risk: float,
        confidence: float,
    ) -> float:
        """
        Calculate event_score from components.

        Formula:
        event_score =
          0.40 * evidence_strength
          + 0.30 * market_relevance
          + 0.20 * (100 - ambiguity_risk)
          + 0.10 * confidence * 100

        Args:
            evidence_strength: Strength of evidence (0-100)
            market_relevance: Relevance to market (0-100)
            ambiguity_risk: Risk of ambiguity (0-100)
            confidence: Confidence level (0-1)

        Returns:
            event_score (0-100)
        """
        score = (
            0.40 * evidence_strength
            + 0.30 * market_relevance
            + 0.20 * (100 - ambiguity_risk)
            + 0.10 * confidence * 100
        )
        return max(0, min(100, score))

    @staticmethod
    def calculate_evidence_strength(
        source_reliability: float,
        evidence_concreteness: float,
        verification_status: float,
        timeliness: float,
    ) -> float:
        """
        Calculate evidence_strength from components.

        Formula:
        evidence_strength =
          0.30 * source_reliability
          + 0.30 * evidence_concreteness
          + 0.20 * verification_status
          + 0.20 * timeliness

        All inputs are 0-100.
        """
        return (
            0.30 * source_reliability
            + 0.30 * evidence_concreteness
            + 0.20 * verification_status
            + 0.20 * timeliness
        )

    @staticmethod
    def calculate_market_relevance(
        direct_causation: float,
        rule_alignment: float,
        category_match: float,
    ) -> float:
        """
        Calculate market_relevance from components.

        Formula:
        market_relevance =
          0.40 * direct_causation
          + 0.30 * rule_alignment
          + 0.30 * category_match

        All inputs are 0-100.
        """
        return (
            0.40 * direct_causation
            + 0.30 * rule_alignment
            + 0.30 * category_match
        )

    @staticmethod
    def calculate_ambiguity_risk(
        rule_clarity: float,
        resolution_source_clarity: float,
        edge_case_risk: float,
        historical_controversy: float,
    ) -> float:
        """
        Calculate ambiguity_risk from components.

        Formula:
        ambiguity_risk =
          0.35 * (100 - rule_clarity)
          + 0.25 * (100 - resolution_source_clarity)
          + 0.20 * edge_case_risk
          + 0.20 * historical_controversy

        All inputs are 0-100.
        """
        return (
            0.35 * (100 - rule_clarity)
            + 0.25 * (100 - resolution_source_clarity)
            + 0.20 * edge_case_risk
            + 0.20 * historical_controversy
        )
